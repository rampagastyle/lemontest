"""Подключается последним: фиксирует в логах необработанные апдейты и не оставляет кнопки «вечно грузиться»."""
import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

logger = logging.getLogger(__name__)
router = Router()


@router.message()
async def unhandled_message(message: Message, state: FSMContext):
    logger.info("Необработанное сообщение от %s: text=%r content_type=%s state=%s",
                message.from_user.id if message.from_user else None, message.text,
                message.content_type, await state.get_state())


@router.callback_query()
async def unhandled_callback(callback: CallbackQuery):
    logger.info("Необработанный callback от %s: %r", callback.from_user.id, callback.data)
    await callback.answer("Эта кнопка устарела. Откройте меню заново: /start", show_alert=True)
