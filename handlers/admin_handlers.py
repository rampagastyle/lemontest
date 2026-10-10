from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime

from database import db
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


@router.message(F.text == "✅ Проверить билет")
async def check_ticket_start(message: Message):
    if not await is_admin_filter(message):
        await message.answer("❌ У вас нет прав администратора")
        return

    await message.answer("📷 Отправьте QR-код билета или введите код вручную:")


@router.message(F.text == "📊 Статистика")
async def show_statistics(message: Message):
    if not await is_admin_filter(message):
        await message.answer("❌ У вас нет прав администратора")
        return

    events = await db.get_active_events()

    if not events:
        await message.answer("📊 Нет активных мероприятий")
        return

    text = "📊 Статистика по мероприятиям:\n\n"
    for event in events:
        sold = event['total_tickets'] - event['available_tickets']
        text += f"🎉 {event['name']}\n"
        text += f"Продано: {sold}/{event['total_tickets']}\n"
        text += f"Выручка: {sold * event['price']}₽\n\n"

    await message.answer(text)
