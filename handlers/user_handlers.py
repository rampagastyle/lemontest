from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext

from database import db
from keyboards import main_menu, admin_menu, events_list_keyboard, event_detail_keyboard, confirm_purchase_keyboard
from utils import generate_unique_ticket_code, generate_qr_code
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

⚠️ Режим тестирования - оплата не требуется!
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
    is_admin = await db.is_admin(callback.from_user.id)

    text = f"""
🎉 {event['name']}

📝 {event['description']}

📅 Дата: {date_str}
📍 Место: {event['location']}
💰 Цена: {event['price']}₽

🎫 Доступно билетов: {event['available_tickets']} из {event['total_tickets']}

⚠️ Тестовый режим - оплата не требуется
    """

    await callback.message.edit_text(text, reply_markup=event_detail_keyboard(event_id, is_admin))
    await callback.answer()


@router.callback_query(F.data.startswith("buy_"))
async def process_buy_ticket(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[1])
    event = await db.get_event(event_id)

    if not event:
        await callback.answer("❌ Мероприятие не найдено", show_alert=True)
        return

    if event['available_tickets'] <= 0:
        await callback.answer("❌ Билеты закончились", show_alert=True)
        return

    text = f"""
🎫 Покупка билета (ТЕСТОВЫЙ РЕЖИМ)

Мероприятие: {event['name']}
Цена: {event['price']}₽

⚠️ Это тестовая покупка - оплата не требуется!
Просто подтвердите получение билета.
    """

    await callback.message.edit_text(text, reply_markup=confirm_purchase_keyboard(event_id))
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_buy_"))
async def confirm_purchase(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    event = await db.get_event(event_id)

    if not event or event['available_tickets'] <= 0:
        await callback.answer("❌ Билеты закончились", show_alert=True)
        return

    qr_code = generate_unique_ticket_code()

    try:
        ticket_id = await db.create_ticket(
            event_id=event_id,
            user_id=callback.from_user.id,
            username=callback.from_user.username or "Unknown",
            qr_code=qr_code,
            ticket_type='purchased'
        )

        qr_image = generate_qr_code(qr_code)
        date_str = event['date'].strftime("%d.%m.%Y %H:%M")

        text = f"""
✅ Билет успешно получен!

🎉 {event['name']}
📅 {date_str}
📍 {event['location']}

🎫 Ваш билет:
Код: `{qr_code}`

Покажите этот QR-код на входе.
        """

        photo = BufferedInputFile(qr_image.read(), filename="ticket_qr.png")
        await callback.message.answer_photo(photo=photo, caption=text, parse_mode="Markdown")
        await callback.message.delete()
        await callback.answer("✅ Билет получен!")

    except Exception as e:
        await callback.answer("❌ Ошибка при выдаче билета", show_alert=True)
        print(f"Ticket creation error: {e}")


@router.callback_query(F.data == "back_to_events")
async def back_to_events(callback: CallbackQuery):
    events = await db.get_active_events()
    text = "🎉 Доступные мероприятия:"
    await callback.message.edit_text(text, reply_markup=events_list_keyboard(events))
    await callback.answer()


@router.message(F.text == "🎟 Мои билеты")
@router.callback_query(F.data == "my_tickets")
async def show_my_tickets(event):
    user_id = event.from_user.id

    if isinstance(event, CallbackQuery):
        message = event.message
        is_callback = True
    else:
        message = event
        is_callback = False

    tickets = await db.get_user_tickets(user_id)

    if not tickets:
        text = "У вас пока нет билетов. Купите билет на мероприятие!"
        if is_callback:
            await message.edit_text(text)
            await event.answer()
        else:
            await message.answer(text)
        return

    for ticket in tickets:
        date_str = ticket['event_date'].strftime("%d.%m.%Y %H:%M")
        status = "✅ Использован" if ticket['used_at'] else "🎫 Активен"
        ticket_type = "🎁 Подарочный" if ticket['ticket_type'] == 'gifted' else "💳 Куплен"

        text = f"""
🎉 {ticket['event_name']}
📅 {date_str}
📍 {ticket['location']}

Статус: {status}
Тип: {ticket_type}
Код: `{ticket['qr_code']}`
        """

        qr_image = generate_qr_code(ticket['qr_code'])
        photo = BufferedInputFile(qr_image.read(), filename="ticket_qr.png")
        await message.answer_photo(photo=photo, caption=text, parse_mode="Markdown")

    if is_callback:
        await message.delete()
        await event.answer()


@router.message(F.text == "ℹ️ О боте")
async def about_bot(message: Message):
    text = """
🍋 LEMON Tickets (ТЕСТ-ВЕРСИЯ)

Бот для покупки и управления билетами на мероприятия.

⚠️ Это тестовая версия:
• Оплата не требуется
• Билеты выдаются бесплатно
• Для демонстрации функционала

📧 Поддержка: нажмите "💬 Поддержка"
    """
    await message.answer(text)


@router.message(F.text == "💬 Поддержка")
async def support_info(message: Message):
    text = """
💬 Техническая поддержка

Напишите ваш вопрос следующим сообщением, и мы свяжемся с вами в ближайшее время.

Или обратитесь напрямую к администратору.
    """
    await message.answer(text)
