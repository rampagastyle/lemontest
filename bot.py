import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database import db
from handlers import scan_handlers, user_handlers, admin_handlers, list_check_handlers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан. Укажите его в .env или в переменных окружения.")
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан. Укажите его в .env или в переменных окружения.")

    bot = Bot(token=config.BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # scan_handlers первым: /start t_<код> должен обрабатываться раньше обычного /start
    dp.include_router(scan_handlers.router)
    dp.include_router(list_check_handlers.router)
    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)

    await db.connect()

    for admin_id in config.ADMIN_IDS:
        await db.add_admin(admin_id)

    logger.info("🍋 LEMON Tickets TEST bot started!")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
