import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database import db
from handlers import scan_handlers, user_handlers, list_handlers, admin_handlers, fallback
from listcheck.vk_api import get_vk_client
from listcheck.vk_listener import run_vk_listener

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

    # scan_handlers первым: /start t_<код> должен обрабатываться раньше обычного /start.
    # list_handlers до user_handlers: состояния диалога списков перехватывают кнопки меню.
    # fallback последним: логирует необработанные апдейты.
    dp.include_router(scan_handlers.router)
    dp.include_router(list_handlers.router)
    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(fallback.router)

    await db.connect()

    for admin_id in config.ADMIN_IDS:
        await db.add_admin(admin_id)

    listener_task = None
    if config.LIST_VERIFICATION:
        problems = config.list_config_problems()
        if problems:
            logger.warning("Проверка списков включена, но не заданы: %s. Кнопка «По списку» будет недоступна.",
                           ", ".join(problems))
        else:
            listener_task = asyncio.create_task(run_vk_listener(bot))
            logger.info("Слушатель событий ВК запущен")

    logger.info("🍋 LEMON Tickets TEST bot started!")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if listener_task:
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
        vk = get_vk_client()
        if vk:
            await vk.close()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
