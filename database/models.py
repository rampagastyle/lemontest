import asyncpg
from datetime import datetime
from typing import Optional, List
import config


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
                    price INTEGER NOT NULL,
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
                    payment_id TEXT UNIQUE,
                    status TEXT DEFAULT 'pending',
                    purchased_at TIMESTAMP DEFAULT NOW(),
                    used_at TIMESTAMP
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

    async def add_admin(self, user_id: int, username: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO admins (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING',
                user_id, username
            )

    async def is_admin(self, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.fetchval('SELECT EXISTS(SELECT 1 FROM admins WHERE user_id = $1)', user_id)
            return result

    async def create_event(self, name: str, description: str, date: datetime, location: str,
                          price: int, total_tickets: int, created_by: int, image_url: str = None) -> int:
        async with self.pool.acquire() as conn:
            event_id = await conn.fetchval('''
                INSERT INTO events (name, description, date, location, price, total_tickets,
                                   available_tickets, created_by, image_url)
                VALUES ($1, $2, $3, $4, $5, $6, $6, $7, $8)
                RETURNING id
            ''', name, description, date, location, price, total_tickets, created_by, image_url)
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

    async def create_ticket(self, event_id: int, user_id: int, username: str,
                           qr_code: str, payment_id: str) -> int:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                ticket_id = await conn.fetchval('''
                    INSERT INTO tickets (event_id, user_id, username, qr_code, payment_id, status)
                    VALUES ($1, $2, $3, $4, $5, 'paid')
                    RETURNING id
                ''', event_id, user_id, username, qr_code, payment_id)

                await conn.execute('''
                    UPDATE events
                    SET available_tickets = available_tickets - 1
                    WHERE id = $1
                ''', event_id)

                return ticket_id

    async def get_user_tickets(self, user_id: int) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT t.*, e.name as event_name, e.date as event_date, e.location
                FROM tickets t
                JOIN events e ON t.event_id = e.id
                WHERE t.user_id = $1 AND t.status = 'paid'
                ORDER BY e.date DESC
            ''')
            return [dict(row) for row in rows]

    async def validate_ticket(self, qr_code: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                ticket = await conn.fetchrow('''
                    SELECT t.*, e.name as event_name, e.date as event_date
                    FROM tickets t
                    JOIN events e ON t.event_id = e.id
                    WHERE t.qr_code = $1
                ''', qr_code)

                if ticket and ticket['status'] == 'paid' and not ticket['used_at']:
                    await conn.execute('''
                        UPDATE tickets
                        SET used_at = NOW()
                        WHERE qr_code = $1
                    ''', qr_code)
                    return dict(ticket)

                return dict(ticket) if ticket else None

    async def create_support_request(self, user_id: int, username: str, message: str) -> int:
        async with self.pool.acquire() as conn:
            request_id = await conn.fetchval('''
                INSERT INTO support_requests (user_id, username, message)
                VALUES ($1, $2, $3)
                RETURNING id
            ''', user_id, username, message)
            return request_id


db = Database()
