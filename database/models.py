import asyncpg
from datetime import datetime
from typing import Optional, List
import config


class SoldOutError(Exception):
    """Билеты на мероприятие закончились (или мероприятие неактивно)."""


class AlreadyHasTicketError(Exception):
    """У пользователя уже есть купленный билет на это мероприятие."""


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(config.DATABASE_URL)
        await self.create_tables()

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    added_at TIMESTAMP DEFAULT NOW()
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    date TIMESTAMP NOT NULL,
                    location TEXT,
                    price INTEGER,
                    post_url TEXT,
                    price_list INTEGER,
                    price_nolist INTEGER,
                    total_tickets INTEGER NOT NULL,
                    available_tickets INTEGER NOT NULL,
                    image_url TEXT,
                    created_by BIGINT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    id SERIAL PRIMARY KEY,
                    event_id INTEGER REFERENCES events(id),
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    qr_code TEXT UNIQUE NOT NULL,
                    ticket_type TEXT DEFAULT 'purchased',
                    ticket_tier TEXT,
                    price INTEGER,
                    gifted_by BIGINT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT NOW(),
                    used_at TIMESTAMP,
                    used_by_admin BIGINT
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS support_requests (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT NOW(),
                    resolved_at TIMESTAMP
                )
            ''')

            # ---- Миграции для баз, созданных старой версией бота (безопасно запускать повторно) ----
            await conn.execute('ALTER TABLE events ADD COLUMN IF NOT EXISTS post_url TEXT')
            await conn.execute('ALTER TABLE events ADD COLUMN IF NOT EXISTS price_list INTEGER')
            await conn.execute('ALTER TABLE events ADD COLUMN IF NOT EXISTS price_nolist INTEGER')
            await conn.execute('ALTER TABLE events ALTER COLUMN price DROP NOT NULL')
            # Старые события с одной ценой: обе цены равны прежней
            await conn.execute('UPDATE events SET price_list = price WHERE price_list IS NULL AND price IS NOT NULL')
            await conn.execute('UPDATE events SET price_nolist = price WHERE price_nolist IS NULL AND price IS NOT NULL')

            await conn.execute('ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ticket_tier TEXT')
            await conn.execute('ALTER TABLE tickets ADD COLUMN IF NOT EXISTS price INTEGER')
            await conn.execute('''
                UPDATE tickets t SET price = e.price
                FROM events e
                WHERE t.event_id = e.id AND t.price IS NULL
                  AND t.ticket_type = 'purchased' AND e.price IS NOT NULL
            ''')

            # Защита от ухода остатка билетов в минус (NOT VALID — не ломает старые данные)
            await conn.execute('''
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'events_available_nonneg'
                    ) THEN
                        ALTER TABLE events
                        ADD CONSTRAINT events_available_nonneg CHECK (available_tickets >= 0) NOT VALID;
                    END IF;
                END $$;
            ''')

            await conn.execute('CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_tickets_event ON tickets(event_id)')

    # ---------- Админы ----------

    async def add_admin(self, user_id: int, username: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO admins (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING',
                user_id, username
            )

    async def is_admin(self, user_id: int) -> bool:
        """Админ — это главный админ из ADMIN_IDS или пользователь из таблицы admins."""
        if user_id in config.ADMIN_IDS:
            return True
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT EXISTS(SELECT 1 FROM admins WHERE user_id = $1)', user_id)

    async def get_admin_ids(self) -> List[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('SELECT user_id FROM admins')
            return [row['user_id'] for row in rows]

    # ---------- События ----------

    async def create_event(self, name: str, date: datetime, post_url: str,
                           price_list: int, price_nolist: int,
                           total_tickets: int, created_by: int) -> int:
        async with self.pool.acquire() as conn:
            event_id = await conn.fetchval('''
                INSERT INTO events (name, date, post_url, price_list, price_nolist,
                                    total_tickets, available_tickets, created_by)
                VALUES ($1, $2, $3, $4, $5, $6, $6, $7)
                RETURNING id
            ''', name, date, post_url, price_list, price_nolist, total_tickets, created_by)
            return event_id

    async def get_active_events(self) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM events
                WHERE is_active = TRUE AND date > NOW()
                ORDER BY date ASC
            ''')
            return [dict(row) for row in rows]

    async def get_event(self, event_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM events WHERE id = $1', event_id)
            return dict(row) if row else None

    # ---------- Билеты ----------

    async def create_ticket(self, event_id: int, user_id: int, username: str,
                            qr_code: str, ticket_type: str = 'purchased', gifted_by: int = None,
                            ticket_tier: str = None, price: int = None) -> int:
        """Атомарно выдаёт билет.

        ticket_type: 'purchased' | 'gifted'
        ticket_tier: 'list' (по списку) | 'nolist' (без списка) — только для купленных
        price: цена, по которой куплен билет (для выручки)

        Остаток уменьшается условным UPDATE ... WHERE available_tickets > 0 — это блокирует
        строку события и исключает гонки. При ошибке транзакция откатывается целиком.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                updated = await conn.fetchval('''
                    UPDATE events
                    SET available_tickets = available_tickets - 1
                    WHERE id = $1 AND available_tickets > 0 AND is_active = TRUE
                    RETURNING id
                ''', event_id)
                if updated is None:
                    raise SoldOutError()

                if ticket_type == 'purchased':
                    already = await conn.fetchval('''
                        SELECT EXISTS(
                            SELECT 1 FROM tickets
                            WHERE event_id = $1 AND user_id = $2
                              AND ticket_type = 'purchased' AND status = 'active'
                        )
                    ''', event_id, user_id)
                    if already:
                        raise AlreadyHasTicketError()

                ticket_id = await conn.fetchval('''
                    INSERT INTO tickets (event_id, user_id, username, qr_code, ticket_type,
                                         ticket_tier, price, gifted_by, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'active')
                    RETURNING id
                ''', event_id, user_id, username, qr_code, ticket_type, ticket_tier, price, gifted_by)

                return ticket_id

    async def get_user_tickets(self, user_id: int) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT t.*, e.name as event_name, e.date as event_date
                FROM tickets t
                JOIN events e ON t.event_id = e.id
                WHERE t.user_id = $1 AND t.status = 'active'
                ORDER BY e.date DESC
            ''', user_id)
            return [dict(row) for row in rows]

    async def validate_and_use_ticket(self, qr_code: str, admin_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # FOR UPDATE — два админа не смогут одновременно активировать один билет
                ticket = await conn.fetchrow('''
                    SELECT t.*, e.name as event_name, e.date as event_date,
                           e.is_active as event_is_active
                    FROM tickets t
                    JOIN events e ON t.event_id = e.id
                    WHERE t.qr_code = $1
                    FOR UPDATE OF t
                ''', qr_code)

                if not ticket:
                    return None

                result = dict(ticket)

                if ticket['status'] == 'active' and not ticket['used_at']:
                    await conn.execute('''
                        UPDATE tickets
                        SET used_at = NOW(), used_by_admin = $2
                        WHERE qr_code = $1
                    ''', qr_code, admin_id)
                    result['just_used'] = True
                else:
                    result['just_used'] = False

                return result

    # ---------- Статистика ----------

    async def get_event_statistics(self, event_id: int) -> dict:
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow('''
                SELECT
                    COUNT(*) FILTER (WHERE ticket_type = 'purchased') as purchased_count,
                    COUNT(*) FILTER (WHERE ticket_type = 'purchased' AND ticket_tier = 'list') as list_count,
                    COUNT(*) FILTER (WHERE ticket_type = 'purchased' AND ticket_tier = 'nolist') as nolist_count,
                    COUNT(*) FILTER (WHERE ticket_type = 'gifted') as gifted_count,
                    COUNT(*) FILTER (WHERE used_at IS NOT NULL) as used_count,
                    COUNT(*) as total_sold,
                    COALESCE(SUM(price) FILTER (WHERE ticket_type = 'purchased'), 0) as revenue
                FROM tickets
                WHERE event_id = $1 AND status = 'active'
            ''', event_id)
            return dict(stats) if stats else {}

    async def get_all_statistics(self) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT
                    e.id,
                    e.name,
                    e.date,
                    e.total_tickets,
                    e.available_tickets,
                    COUNT(t.id) FILTER (WHERE t.ticket_type = 'purchased') as purchased_count,
                    COUNT(t.id) FILTER (WHERE t.ticket_type = 'purchased' AND t.ticket_tier = 'list') as list_count,
                    COUNT(t.id) FILTER (WHERE t.ticket_type = 'purchased' AND t.ticket_tier = 'nolist') as nolist_count,
                    COUNT(t.id) FILTER (WHERE t.ticket_type = 'gifted') as gifted_count,
                    COUNT(t.id) FILTER (WHERE t.used_at IS NOT NULL) as used_count,
                    COUNT(t.id) as total_sold,
                    COALESCE(SUM(t.price) FILTER (WHERE t.ticket_type = 'purchased'), 0) as revenue
                FROM events e
                LEFT JOIN tickets t ON e.id = t.event_id AND t.status = 'active'
                WHERE e.is_active = TRUE
                GROUP BY e.id
                ORDER BY e.date ASC
            ''')
            return [dict(row) for row in rows]

    # ---------- Поддержка ----------

    async def create_support_request(self, user_id: int, username: str, message: str) -> int:
        async with self.pool.acquire() as conn:
            request_id = await conn.fetchval('''
                INSERT INTO support_requests (user_id, username, message)
                VALUES ($1, $2, $3)
                RETURNING id
            ''', user_id, username, message)
            return request_id


db = Database()
