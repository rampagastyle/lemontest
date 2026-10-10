from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import datetime

from database import db
from keyboards import main_menu, admin_menu, events_list_keyboard, event_detail_keyboard
import config

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    is_admin = await db.is_admin(message.from_user.id)

    welcome_text = f"""
🍋 Добро пожаловать в LEMON Tickets!

Здесь вы можете:
• Покупать билеты на мероприятия
• Хранить билеты в удобном формате
• Получать поддержку 24/7

{"🔑 У вас есть права администратора!" if is_admin else ""}
    """

    keyboard = admin_menu() if is_admin else main_menu()
    await message.answer(welcome_text, reply_markup=keyboard)


@router.message(F.text == "🎫 Мероприятия")
async def show_events(message: Message):
    events = await db.get_active_events()

    if not events:
        await message.answer("😔 Пока нет доступных мероприятий. Загляните позже!")
        return

    text = "🎉 Доступные мероприятия:"
    await message.answer(text, reply_markup=events_list_keyboard(events))


@router.callback_query(F.data.startswith("event_"))
async def show_event_detail(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[1])
    event = await db.get_event(event_id)

    if not event:
        await callback.answer("❌ Мероприятие не найдено", show_alert=True)
        return

    date_str = event['date'].strftime("%d.%m.%Y %H:%M")

    text = f"""
🎉 {event['name']}

📝 {event['description']}

📅 Дата: {date_str}
📍 Место: {event['location']}
💰 Цена: {event['price']}₽

🎫 Доступно билетов: {event['available_tickets']} из {event['total_tickets']}
    """

    await callback.message.edit_text(text, reply_markup=event_detail_keyboard(event_id))
    await callback.answer()


@router.callback_query(F.data == "back_to_events")
async def back_to_events(callback: CallbackQuery):
    events = await db.get_active_events()
    text = "🎉 Доступные мероприятия:"
    await callback.message.edit_text(text, reply_markup=events_list_keyboard(events))
    await callback.answer()


@router.message(F.text == "🎟 Мои билеты")
async def show_my_tickets(message: Message):
    tickets = await db.get_user_tickets(message.from_user.id)

    if not tickets:
        await message.answer("У вас пока нет билетов. Купите билет на мероприятие!")
        return

    text = "🎟 Ваши билеты:\n\n"
    for ticket in tickets:
        date_str = ticket['event_date'].strftime("%d.%m.%Y %H:%M")
        status = "✅ Использован" if ticket['used_at'] else "🎫 Активен"
        text += f"🎉 {ticket['event_name']}\n"
        text += f"📅 {date_str}\n"
        text += f"📍 {ticket['location']}\n"
        text += f"Статус: {status}\n"
        text += f"Код: `{ticket['qr_code']}`\n\n"

    await message.answer(text, parse_mode="Markdown")


@router.message(F.text == "ℹ️ О боте")
async def about_bot(message: Message):
    text = """
🍋 LEMON Tickets

Бот для покупки и управления билетами на мероприятия.

Разработано для удобной покупки билетов через Telegram.

📧 Поддержка: нажмите "💬 Поддержка"
    """
    await message.answer(text)


@router.message(F.text == "💬 Поддержка")
async def support_info(message: Message):
    text = """
💬 Техническая поддержка

Напишите ваш вопрос следующим сообщением, и мы свяжемся с вами в ближайшее время.

Или обратитесь напрямую: @your_support_username
    """
    await message.answer(text)
