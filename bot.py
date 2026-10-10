import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database import db
from handlers import user_handlers, admin_handlers, payment_handlers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    bot = Bot(token=config.BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(payment_handlers.router)

    await db.connect()

    for admin_id in config.ADMIN_IDS:
        await db.add_admin(admin_id)

    logger.info("🍋 LEMON Tickets bot started!")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
