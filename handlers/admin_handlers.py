from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime

from database import db
from keyboards import stats_menu_keyboard
from utils import generate_unique_ticket_code, generate_qr_code
import config

router = Router()


class CreateEvent(StatesGroup):
    name = State()
    description = State()
    date = State()
    location = State()
    price = State()
    total_tickets = State()


class AddAdmin(StatesGroup):
    waiting_for_id = State()


class GiftTicket(StatesGroup):
    event_id = State()
    waiting_for_user = State()


class CheckTicket(StatesGroup):
    waiting_for_code = State()


async def is_admin_filter(message: Message) -> bool:
    return await db.is_admin(message.from_user.id) or message.from_user.id in config.ADMIN_IDS


@router.message(F.text == "➕ Создать событие")
async def start_create_event(message: Message, state: FSMContext):
    if not await is_admin_filter(message):
        await message.answer("❌ У вас нет прав администратора")
        return

    await state.set_state(CreateEvent.name)
    await message.answer("📝 Введите название мероприятия:")


@router.message(CreateEvent.name)
async def process_event_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(CreateEvent.description)
    await message.answer("📄 Введите описание мероприятия:")


@router.message(CreateEvent.description)
async def process_event_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(CreateEvent.date)
    await message.answer("📅 Введите дату и время в формате: ДД.ММ.ГГГГ ЧЧ:ММ\nНапример: 25.12.2024 19:00")


@router.message(CreateEvent.date)
async def process_event_date(message: Message, state: FSMContext):
    try:
        event_date = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        await state.update_data(date=event_date)
        await state.set_state(CreateEvent.location)
        await message.answer("📍 Введите место проведения:")
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте: ДД.ММ.ГГГГ ЧЧ:ММ")


@router.message(CreateEvent.location)
async def process_event_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text)
    await state.set_state(CreateEvent.price)
    await message.answer("💰 Введите цену билета (только число):")


@router.message(CreateEvent.price)
async def process_event_price(message: Message, state: FSMContext):
    try:
        price = int(message.text)
        await state.update_data(price=price)
        await state.set_state(CreateEvent.total_tickets)
        await message.answer("🎫 Введите общее количество билетов:")
    except ValueError:
        await message.answer("❌ Введите число")


@router.message(CreateEvent.total_tickets)
async def process_event_tickets(message: Message, state: FSMContext):
    try:
        total_tickets = int(message.text)
        data = await state.get_data()

        event_id = await db.create_event(
            name=data['name'],
            description=data['description'],
            date=data['date'],
            location=data['location'],
            price=data['price'],
            total_tickets=total_tickets,
            created_by=message.from_user.id
        )

        await state.clear()
        await message.answer(f"✅ Мероприятие создано! ID: {event_id}")
    except ValueError:
        await message.answer("❌ Введите число")


@router.message(F.text == "🎁 Выдать билет")
async def start_gift_ticket(message: Message, state: FSMContext):
    if not await is_admin_filter(message):
        await message.answer("❌ У вас нет прав администратора")
        return

    events = await db.get_active_events()
    if not events:
        await message.answer("❌ Нет доступных мероприятий")
        return

    text = "🎁 Выдача подарочного билета\n\nВыберите мероприятие (отправьте ID):\n\n"
    for event in events:
        text += f"ID: {event['id']} - {event['name']}\n"

    await state.set_state(GiftTicket.event_id)
    await message.answer(text)


@router.message(GiftTicket.event_id)
async def process_gift_event_id(message: Message, state: FSMContext):
    try:
        event_id = int(message.text)
        event = await db.get_event(event_id)

        if not event:
            await message.answer("❌ Мероприятие не найдено")
            return

        if event['available_tickets'] <= 0:
            await message.answer("❌ Билеты закончились")
            return

        await state.update_data(event_id=event_id)
        await state.set_state(GiftTicket.waiting_for_user)
        await message.answer("👤 Отправьте ID пользователя или перешлите его сообщение:")
    except ValueError:
        await message.answer("❌ Введите число")


@router.message(GiftTicket.waiting_for_user)
async def process_gift_user(message: Message, state: FSMContext):
    try:
        if message.forward_from:
            user_id = message.forward_from.id
            username = message.forward_from.username or "Unknown"
        else:
            user_id = int(message.text)
            username = "Unknown"

        data = await state.get_data()
        event_id = data['event_id']
        event = await db.get_event(event_id)

        qr_code = generate_unique_ticket_code()

        ticket_id = await db.create_ticket(
            event_id=event_id,
            user_id=user_id,
            username=username,
            qr_code=qr_code,
            ticket_type='gifted',
            gifted_by=message.from_user.id
        )

        qr_image = generate_qr_code(qr_code)
        date_str = event['date'].strftime("%d.%m.%Y %H:%M")

        text = f"""
✅ Подарочный билет выдан!

🎉 {event['name']}
📅 {date_str}
📍 {event['location']}

👤 Получатель: {user_id}
🎫 Код: `{qr_code}`
        """

        photo = BufferedInputFile(qr_image.read(), filename="ticket_qr.png")
        await message.answer_photo(photo=photo, caption=text, parse_mode="Markdown")

        try:
            await message.bot.send_photo(
                chat_id=user_id,
                photo=BufferedInputFile(generate_qr_code(qr_code).read(), filename="ticket_qr.png"),
                caption=f"🎁 Вам подарили билет!\n\n{text}"
            )
        except:
            await message.answer("⚠️ Не удалось отправить билет пользователю напрямую")

        await state.clear()

    except ValueError:
        await message.answer("❌ Неверный формат ID")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()


@router.callback_query(F.data.startswith("gift_"))
async def gift_from_event(callback: CallbackQuery, state: FSMContext):
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав администратора", show_alert=True)
        return

    event_id = int(callback.data.split("_")[1])
    event = await db.get_event(event_id)

    if not event or event['available_tickets'] <= 0:
        await callback.answer("❌ Билеты закончились", show_alert=True)
        return

    await state.update_data(event_id=event_id)
    await state.set_state(GiftTicket.waiting_for_user)
    await callback.message.answer("👤 Отправьте ID пользователя или перешлите его сообщение:")
    await callback.answer()


@router.message(F.text == "✅ Проверить билет")
async def start_check_ticket(message: Message, state: FSMContext):
    if not await is_admin_filter(message):
        await message.answer("❌ У вас нет прав администратора")
        return

    await state.set_state(CheckTicket.waiting_for_code)
    await message.answer("📷 Отправьте код билета:")


@router.message(CheckTicket.waiting_for_code)
async def process_check_ticket(message: Message, state: FSMContext):
    qr_code = message.text.strip()

    ticket = await db.validate_and_use_ticket(qr_code, message.from_user.id)

    if not ticket:
        await message.answer("❌ Билет не найден")
        await state.clear()
        return

    date_str = ticket['event_date'].strftime("%d.%m.%Y %H:%M")
    ticket_type = "🎁 Подарочный" if ticket['ticket_type'] == 'gifted' else "💳 Куплен"

    if ticket['just_used']:
        text = f"""
✅ БИЛЕТ АКТИВИРОВАН!

🎉 {ticket['event_name']}
📅 {date_str}
👤 Владелец: @{ticket['username'] or 'Unknown'}
🎫 Тип: {ticket_type}

Пользователь может пройти!
        """
    else:
        if ticket['used_at']:
            used_str = ticket['used_at'].strftime("%d.%m.%Y %H:%M")
            text = f"""
❌ БИЛЕТ УЖЕ ИСПОЛЬЗОВАН!

🎉 {ticket['event_name']}
📅 {date_str}
👤 Владелец: @{ticket['username'] or 'Unknown'}
🎫 Тип: {ticket_type}

⚠️ Использован: {used_str}
            """
        else:
            text = f"""
⚠️ БИЛЕТ НЕ АКТИВЕН

🎉 {ticket['event_name']}
📅 {date_str}
👤 Владелец: @{ticket['username'] or 'Unknown'}
🎫 Тип: {ticket_type}

Статус: {ticket['status']}
            """

    await message.answer(text)
    await state.clear()


@router.message(F.text == "📊 Статистика")
async def show_statistics_menu(message: Message):
    if not await is_admin_filter(message):
        await message.answer("❌ У вас нет прав администратора")
        return

    events = await db.get_active_events()

    if not events:
        await message.answer("📊 Нет активных мероприятий")
        return

    await message.answer("📊 Выберите мероприятие:", reply_markup=stats_menu_keyboard(events))


@router.callback_query(F.data == "stats_all")
async def show_all_statistics(callback: CallbackQuery):
    stats = await db.get_all_statistics()

    if not stats:
        await callback.answer("📊 Нет данных", show_alert=True)
        return

    text = "📊 ОБЩАЯ СТАТИСТИКА\n\n"

    total_revenue = 0
    total_purchased = 0
    total_gifted = 0
    total_used = 0

    for stat in stats:
        text += f"🎉 {stat['name']}\n"
        text += f"💳 Куплено: {stat['purchased_count']}\n"
        text += f"🎁 Подарено: {stat['gifted_count']}\n"
        text += f"✅ Использовано: {stat['used_count']}/{stat['total_sold']}\n"
        text += f"💰 Выручка: {stat['revenue'] or 0}₽\n"
        text += f"🎫 Осталось: {stat['available_tickets']}/{stat['total_tickets']}\n\n"

        total_revenue += stat['revenue'] or 0
        total_purchased += stat['purchased_count']
        total_gifted += stat['gifted_count']
        total_used += stat['used_count']

    text += f"━━━━━━━━━━━━━━━━\n"
    text += f"ИТОГО:\n"
    text += f"💳 Куплено билетов: {total_purchased}\n"
    text += f"🎁 Подарено билетов: {total_gifted}\n"
    text += f"✅ Использовано: {total_used}\n"
    text += f"💰 Общая выручка: {total_revenue}₽"

    await callback.message.edit_text(text, reply_markup=stats_menu_keyboard(stats))
    await callback.answer()


@router.callback_query(F.data.startswith("stats_"))
async def show_event_statistics(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[1])
    event = await db.get_event(event_id)
    stats = await db.get_event_statistics(event_id)

    if not event or not stats:
        await callback.answer("❌ Данные не найдены", show_alert=True)
        return

    date_str = event['date'].strftime("%d.%m.%Y %H:%M")

    text = f"""
📊 СТАТИСТИКА МЕРОПРИЯТИЯ

🎉 {event['name']}
📅 {date_str}
📍 {event['location']}
💰 Цена: {event['price']}₽

━━━━━━━━━━━━━━━━
💳 Куплено билетов: {stats['purchased_count']}
🎁 Подарено билетов: {stats['gifted_count']}
📦 Всего продано: {stats['total_sold']}
✅ Использовано: {stats['used_count']}
🎫 Осталось: {event['available_tickets']}/{event['total_tickets']}

━━━━━━━━━━━━━━━━
💰 Выручка: {stats['revenue'] or 0}₽
    """

    events = await db.get_active_events()
    await callback.message.edit_text(text, reply_markup=stats_menu_keyboard(events))
    await callback.answer()


@router.callback_query(F.data == "close_stats")
async def close_statistics(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@router.message(F.text == "👥 Добавить админа")
async def start_add_admin(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Только главный админ может добавлять других админов")
        return

    await state.set_state(AddAdmin.waiting_for_id)
    await message.answer("👤 Отправьте ID пользователя или перешлите его сообщение:")


@router.message(AddAdmin.waiting_for_id)
async def process_add_admin(message: Message, state: FSMContext):
    try:
        if message.forward_from:
            user_id = message.forward_from.id
            username = message.forward_from.username
        else:
            user_id = int(message.text)
            username = None

        await db.add_admin(user_id, username)
        await state.clear()
        await message.answer(f"✅ Пользователь {user_id} добавлен в список администраторов")
    except ValueError:
        await message.answer("❌ Неверный формат ID")
