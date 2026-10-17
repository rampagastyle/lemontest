import secrets
import asyncpg
from datetime import datetime
from typing import Optional, List
import config


class SoldOutError(Exception):
    """Билеты на мероприятие закончились (или мероприятие неактивно)."""


class AlreadyHasTicketError(Exception):
    """У пользователя уже есть купленный билет на это мероприятие."""


class ListQuotaError(Exception):
    """Места «По списку» на это мероприятие закончились."""


class ListLimitError(Exception):
    """У пользователя уже есть билет «По списку» на это мероприятие (один на человека)."""


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

            # ---- Проверка списков ----
            await conn.execute('ALTER TABLE events ADD COLUMN IF NOT EXISTS vk_post_url TEXT')
            await conn.execute('ALTER TABLE events ADD COLUMN IF NOT EXISTS vk_post_owner BIGINT')
            await conn.execute('ALTER TABLE events ADD COLUMN IF NOT EXISTS vk_post_id BIGINT')
            await conn.execute('ALTER TABLE events ADD COLUMN IF NOT EXISTS list_quota INTEGER')
            await conn.execute('ALTER TABLE tickets ADD COLUMN IF NOT EXISTS list_verified BOOLEAN DEFAULT FALSE')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS vk_links (
                    user_id BIGINT PRIMARY KEY,
                    vk_id BIGINT UNIQUE NOT NULL,
                    vk_name TEXT,
                    linked_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS vk_link_codes (
                    code TEXT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS vk_comments (
                    owner_id BIGINT NOT NULL,
                    comment_id BIGINT NOT NULL,
                    post_id BIGINT NOT NULL,
                    vk_id BIGINT NOT NULL,
                    valid BOOLEAN NOT NULL,
                    tagged INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (owner_id, comment_id)
                )
            ''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_vk_comments_lookup ON vk_comments(vk_id, owner_id, post_id)')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS list_access (
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT,
                    note TEXT,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (event_id, user_id)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS story_submissions (
                    id SERIAL PRIMARY KEY,
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    file_id TEXT,
                    file_unique_id TEXT,
                    img_hash TEXT,
                    ai_json TEXT,
                    decision TEXT NOT NULL,
                    note TEXT,
                    reviewed_by BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_story_event ON story_submissions(event_id)')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS list_bans (
                    user_id BIGINT PRIMARY KEY,
                    reason TEXT,
                    banned_by BIGINT,
                    banned_at TIMESTAMP DEFAULT NOW()
                )
            ''')

            # Перенос постов ВК из прежней версии проверки списков (таблица events_vk), если она есть.
            # Переносятся только ссылки вида wall-123_456; повторный запуск ничего не меняет.
            await conn.execute('''
                DO $$
                BEGIN
                    IF to_regclass('events_vk') IS NOT NULL THEN
                        UPDATE events e
                        SET vk_post_url = 'https://vk.com/wall' || substring(v.vk_post_url from 'wall(-?[0-9]+_[0-9]+)'),
                            vk_post_owner = substring(v.vk_post_url from 'wall(-?[0-9]+)_[0-9]+')::bigint,
                            vk_post_id = substring(v.vk_post_url from 'wall-?[0-9]+_([0-9]+)')::bigint
                        FROM events_vk v
                        WHERE v.event_id = e.id AND e.vk_post_url IS NULL
                          AND v.vk_post_url ~ 'wall-?[0-9]+_[0-9]+';
                    END IF;
                END $$;
            ''')

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
                           total_tickets: int, created_by: int,
                           vk_post_url: str = None, vk_post_owner: int = None,
                           vk_post_id: int = None, list_quota: int = None) -> int:
        async with self.pool.acquire() as conn:
            event_id = await conn.fetchval('''
                INSERT INTO events (name, date, post_url, price_list, price_nolist,
                                    total_tickets, available_tickets, created_by,
                                    vk_post_url, vk_post_owner, vk_post_id, list_quota)
                VALUES ($1, $2, $3, $4, $5, $6, $6, $7, $8, $9, $10, $11)
                RETURNING id
            ''', name, date, post_url, price_list, price_nolist, total_tickets, created_by,
                vk_post_url, vk_post_owner, vk_post_id, list_quota)
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

    async def get_all_events(self) -> List[dict]:
        """Все мероприятия (активные и неактивные), для управления."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM events
                ORDER BY date DESC
            ''')
            return [dict(row) for row in rows]

    async def set_event_active(self, event_id: int, is_active: bool) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                'UPDATE events SET is_active = $2 WHERE id = $1',
                event_id, is_active
            )
            return result.endswith('1')

    async def update_event(self, event_id: int, *, name: str = None, date: datetime = None,
                           post_url: str = None, price_list: int = None,
                           price_nolist: int = None) -> bool:
        """Обновляет переданные поля мероприятия."""
        fields = []
        values = []
        idx = 1
        if name is not None:
            fields.append(f'name = ${idx}')
            values.append(name)
            idx += 1
        if date is not None:
            fields.append(f'date = ${idx}')
            values.append(date)
            idx += 1
        if post_url is not None:
            fields.append(f'post_url = ${idx}')
            values.append(post_url)
            idx += 1
        if price_list is not None:
            fields.append(f'price_list = ${idx}')
            values.append(price_list)
            idx += 1
        if price_nolist is not None:
            fields.append(f'price_nolist = ${idx}')
            values.append(price_nolist)
            idx += 1
        if not fields:
            return False
        values.append(event_id)
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE events SET {', '.join(fields)} WHERE id = ${idx}",
                *values
            )
            return result.endswith('1')

    async def add_tickets_to_event(self, event_id: int, count: int) -> bool:
        """Увеличивает total_tickets и available_tickets на count."""
        if count <= 0:
            return False
        async with self.pool.acquire() as conn:
            result = await conn.execute('''
                UPDATE events
                SET total_tickets = total_tickets + $2,
                    available_tickets = available_tickets + $2
                WHERE id = $1
            ''', event_id, count)
            return result.endswith('1')

    # ---------- Билеты ----------

    async def create_ticket(self, event_id: int, user_id: int, username: str,
                            qr_code: str, ticket_type: str = 'purchased', gifted_by: int = None,
                            ticket_tier: str = None, price: int = None,
                            list_verified: bool = False) -> int:
        """Атомарно выдаёт билет.

        ticket_type: 'purchased' | 'gifted'
        ticket_tier: 'list' (по списку) | 'nolist' (без списка) — только для купленных
        price: цена, по которой куплен билет (для выручки)

        Можно покупать несколько билетов на одно мероприятие.
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

                # Строка события уже заблокирована UPDATE-ом выше, поэтому проверки квоты
                # «По списку» и лимита «один на человека» не гоняются между покупателями.
                if ticket_type == 'purchased' and ticket_tier == 'list' and config.LIST_VERIFICATION:
                    quota = await conn.fetchval('SELECT list_quota FROM events WHERE id = $1', event_id)
                    if quota is not None:
                        used = await conn.fetchval('''
                            SELECT COUNT(*) FROM tickets
                            WHERE event_id = $1 AND ticket_type = 'purchased'
                              AND ticket_tier = 'list' AND status = 'active'
                        ''', event_id)
                        if used >= quota:
                            raise ListQuotaError()
                    has_list = await conn.fetchval('''
                        SELECT EXISTS(
                            SELECT 1 FROM tickets
                            WHERE event_id = $1 AND user_id = $2 AND ticket_type = 'purchased'
                              AND ticket_tier = 'list' AND status = 'active'
                        )
                    ''', event_id, user_id)
                    if has_list:
                        raise ListLimitError()

                ticket_id = await conn.fetchval('''
                    INSERT INTO tickets (event_id, user_id, username, qr_code, ticket_type,
                                         ticket_tier, price, gifted_by, status, list_verified)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'active', $9)
                    RETURNING id
                ''', event_id, user_id, username, qr_code, ticket_type, ticket_tier, price, gifted_by,
                    list_verified)

                return ticket_id

    async def count_user_tickets_for_event(self, user_id: int, event_id: int) -> int:
        """Сколько активных билетов у пользователя на мероприятие (любого типа)."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                SELECT COUNT(*) FROM tickets
                WHERE user_id = $1 AND event_id = $2 AND status = 'active'
            ''', user_id, event_id) or 0

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

    async def get_user_events_with_tickets(self, user_id: int) -> List[dict]:
        """Мероприятия, на которые у пользователя есть активные билеты."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT e.id, e.name, e.date,
                       COUNT(t.id) as tickets_count
                FROM events e
                JOIN tickets t ON t.event_id = e.id
                WHERE t.user_id = $1 AND t.status = 'active'
                GROUP BY e.id, e.name, e.date
                ORDER BY e.date DESC
            ''', user_id)
            return [dict(row) for row in rows]

    async def get_user_tickets_for_event(self, user_id: int, event_id: int) -> List[dict]:
        """Билеты пользователя на конкретное мероприятие."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT t.*, e.name as event_name, e.date as event_date
                FROM tickets t
                JOIN events e ON t.event_id = e.id
                WHERE t.user_id = $1 AND t.event_id = $2 AND t.status = 'active'
                ORDER BY t.created_at ASC
            ''', user_id, event_id)
            return [dict(row) for row in rows]

    async def validate_and_use_ticket(self, qr_code: str, admin_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # FOR UPDATE — два админа не смогут одновременно активировать один билет
                ticket = await conn.fetchrow('''
                    SELECT t.*, e.name as event_name, e.date as event_date,
                           e.is_active as event_is_active,
                           e.price_list as event_price_list, e.price_nolist as event_price_nolist
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

    # ---------- Проверка списков ----------

    async def create_link_code(self, user_id: int) -> str:
        """Одноразовый код, который человек отправляет в личку сообщества ВК, чтобы привязать аккаунт."""
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        code = "LEMON-" + "".join(secrets.choice(alphabet) for _ in range(6))
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM vk_link_codes WHERE user_id = $1 OR created_at < NOW() - INTERVAL '1 day'",
                    user_id)
                await conn.execute('INSERT INTO vk_link_codes (code, user_id) VALUES ($1, $2)', code, user_id)
        return code

    async def consume_link_code(self, code: str) -> Optional[int]:
        """Возвращает Telegram user_id, если код существует и ещё не просрочен; код удаляется."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                DELETE FROM vk_link_codes WHERE code = $1
                RETURNING user_id, (created_at > NOW() - make_interval(mins => $2::int)) AS fresh
            ''', code, config.LINK_CODE_TTL_MIN)
            if row and row['fresh']:
                return row['user_id']
            return None

    async def link_vk(self, user_id: int, vk_id: int, vk_name: str) -> str:
        """'ok' | 'vk_taken' (этот ВК уже привязан к другому Telegram) | 'user_has_other' (у Telegram уже другой ВК)."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                owner = await conn.fetchval('SELECT user_id FROM vk_links WHERE vk_id = $1', vk_id)
                if owner is not None:
                    return 'ok' if owner == user_id else 'vk_taken'
                current = await conn.fetchval('SELECT vk_id FROM vk_links WHERE user_id = $1', user_id)
                if current is not None:
                    return 'user_has_other'
                await conn.execute(
                    'INSERT INTO vk_links (user_id, vk_id, vk_name) VALUES ($1, $2, $3)', user_id, vk_id, vk_name)
                return 'ok'

    async def get_vk_link(self, user_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM vk_links WHERE user_id = $1', user_id)
            return dict(row) if row else None

    async def get_user_by_vk(self, vk_id: int) -> Optional[int]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT user_id FROM vk_links WHERE vk_id = $1', vk_id)

    async def get_event_by_vk_post(self, owner_id: int, post_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM events WHERE vk_post_owner = $1 AND vk_post_id = $2 ORDER BY id DESC LIMIT 1',
                owner_id, post_id)
            return dict(row) if row else None

    async def save_vk_comment(self, owner_id: int, comment_id: int, post_id: int,
                              vk_id: int, valid: bool, tagged: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO vk_comments (owner_id, comment_id, post_id, vk_id, valid, tagged)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (owner_id, comment_id) DO UPDATE
                SET post_id = EXCLUDED.post_id, vk_id = EXCLUDED.vk_id,
                    valid = EXCLUDED.valid, tagged = EXCLUDED.tagged, updated_at = NOW()
            ''', owner_id, comment_id, post_id, vk_id, valid, tagged)

    async def mark_vk_comment_deleted(self, owner_id: int, comment_id: int) -> Optional[int]:
        """Комментарий удалён: снимает отметку valid. Возвращает vk_id автора, если запись была валидной."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                UPDATE vk_comments SET valid = FALSE, updated_at = NOW()
                WHERE owner_id = $1 AND comment_id = $2 AND valid
                RETURNING vk_id
            ''', owner_id, comment_id)

    async def has_valid_vk_comment(self, vk_id: int, owner_id: int, post_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                SELECT EXISTS(
                    SELECT 1 FROM vk_comments
                    WHERE vk_id = $1 AND owner_id = $2 AND post_id = $3 AND valid
                )
            ''', vk_id, owner_id, post_id)

    async def get_list_access(self, event_id: int, user_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM list_access WHERE event_id = $1 AND user_id = $2', event_id, user_id)
            return dict(row) if row else None

    async def set_list_access(self, event_id: int, user_id: int, status: str, source: str, note: str = None):
        """status: approved | pending | rejected | revoked (путь «сторис»)."""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO list_access (event_id, user_id, status, source, note)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (event_id, user_id) DO UPDATE
                SET status = EXCLUDED.status, source = EXCLUDED.source,
                    note = EXCLUDED.note, updated_at = NOW()
            ''', event_id, user_id, status, source, note)

    async def count_story_attempts(self, event_id: int, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                SELECT COUNT(*) FROM story_submissions
                WHERE event_id = $1 AND user_id = $2
                  AND decision IN ('rejected_ai', 'rejected_admin', 'dup')
            ''', event_id, user_id) or 0

    async def add_story_submission(self, event_id: int, user_id: int, file_id: str, file_unique_id: str,
                                   img_hash: Optional[str], ai_json: Optional[str],
                                   decision: str, note: str = None) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                INSERT INTO story_submissions (event_id, user_id, file_id, file_unique_id, img_hash,
                                               ai_json, decision, note)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
            ''', event_id, user_id, file_id, file_unique_id, img_hash, ai_json, decision, note)

    async def get_story_submission(self, sub_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM story_submissions WHERE id = $1', sub_id)
            return dict(row) if row else None

    async def mark_submission_reviewed(self, sub_id: int, admin_id: int, decision: str) -> bool:
        """True, если именно этот вызов обработал заявку (защита от двойного нажатия двумя админами)."""
        async with self.pool.acquire() as conn:
            updated = await conn.fetchval('''
                UPDATE story_submissions SET reviewed_by = $2, decision = $3
                WHERE id = $1 AND reviewed_by IS NULL
                RETURNING id
            ''', sub_id, admin_id, decision)
            return updated is not None

    async def get_event_image_hashes(self, event_id: int) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT user_id, img_hash, file_unique_id FROM story_submissions
                WHERE event_id = $1 AND decision <> 'dup'
            ''', event_id)
            return [dict(row) for row in rows]

    async def is_list_banned(self, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT EXISTS(SELECT 1 FROM list_bans WHERE user_id = $1)', user_id)

    async def ban_list(self, user_id: int, admin_id: int, reason: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO list_bans (user_id, reason, banned_by) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO NOTHING',
                user_id, reason, admin_id)

    async def count_list_tickets(self, event_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                SELECT COUNT(*) FROM tickets
                WHERE event_id = $1 AND ticket_type = 'purchased' AND ticket_tier = 'list' AND status = 'active'
            ''', event_id) or 0

    async def user_has_list_ticket(self, user_id: int, event_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                SELECT EXISTS(
                    SELECT 1 FROM tickets
                    WHERE event_id = $1 AND user_id = $2 AND ticket_type = 'purchased'
                      AND ticket_tier = 'list' AND status = 'active'
                )
            ''', event_id, user_id)

    async def set_event_vk_post(self, event_id: int, url: Optional[str],
                                owner: Optional[int], post_id: Optional[int]) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                'UPDATE events SET vk_post_url = $2, vk_post_owner = $3, vk_post_id = $4 WHERE id = $1',
                event_id, url, owner, post_id)
            return result.endswith('1')

    async def set_event_list_quota(self, event_id: int, quota: Optional[int]) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute('UPDATE events SET list_quota = $2 WHERE id = $1', event_id, quota)
            return result.endswith('1')

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
