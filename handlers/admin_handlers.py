import html
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile, MessageOriginUser
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import db, SoldOutError
from keyboards import stats_menu_keyboard, manage_events_keyboard, manage_event_actions_keyboard, admin_menu
from utils import generate_unique_ticket_code, make_ticket_qr
import config

logger = logging.getLogger(__name__)
router = Router()


class CreateEvent(StatesGroup):
    name = State()
    date = State()
    post_url = State()
    price_list = State()
    price_nolist = State()
    total_tickets = State()


class AddAdmin(StatesGroup):
    waiting_for_id = State()


class GiftTicket(StatesGroup):
    event_id = State()
    waiting_for_user = State()


class EditEvent(StatesGroup):
    waiting_name = State()
    waiting_date = State()
    waiting_price_list = State()
    waiting_price_nolist = State()
    waiting_add_tickets = State()


# ---------- Проверка прав ----------

async def is_admin_id(user_id: int) -> bool:
    return await db.is_admin(user_id)


async def is_admin_filter(message: Message) -> bool:
    return await is_admin_id(message.from_user.id)


def extract_target_user(message: Message) -> Optional[Tuple[int, Optional[str]]]:
    """Достаёт (user_id, username) из пересланного сообщения или из числового ID в тексте."""
    origin = message.forward_origin
    if isinstance(origin, MessageOriginUser):
        return origin.sender_user.id, origin.sender_user.username
    if message.text and message.text.strip().isdigit():
        return int(message.text.strip()), None
    return None


TARGET_USER_ERROR = (
    "❌ Не удалось определить пользователя.\n"
    "Отправьте числовой ID или перешлите сообщение пользователя "
    "(если у него скрыт профиль, пересылка не сработает — используйте ID)."
)

TG_LINK_RE = re.compile(r"^(?:https?://)?(?:t|telegram)\.me/\S+$", re.IGNORECASE)
TG_HANDLE_RE = re.compile(r"^@(\w{4,})$")


def normalize_tg_link(text: str) -> Optional[str]:
    """Принимает ссылку на пост/канал Telegram или @канал, возвращает https-ссылку (или None)."""
    text = (text or "").strip()
    handle = TG_HANDLE_RE.match(text)
    if handle:
        return f"https://t.me/{handle.group(1)}"
    if not TG_LINK_RE.match(text):
        return None
    if not text.lower().startswith("http"):
        text = "https://" + text
    return text


def parse_price(text: str) -> Optional[int]:
    text = (text or "").strip()
    return int(text) if text.isdigit() else None


# ---------- Создание события (минимум полей) ----------

@router.message(F.text == "➕ Создать событие")
async def start_create_event(message: Message, state: FSMContext):
    if not await is_admin_filter(message):
        await message.answer("❌ У вас нет прав администратора")
        return

    await state.set_state(CreateEvent.name)
    await message.answer("📝 Название мероприятия:")


@router.message(CreateEvent.name, F.text)
async def process_event_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(CreateEvent.date)
    example = (datetime.now() + timedelta(days=7)).strftime("%d.%m.%Y 20:00")
    await message.answer(f"📅 Дата и время: ДД.ММ.ГГГГ ЧЧ:ММ\nНапример: {example}")


@router.message(CreateEvent.date, F.text)
async def process_event_date(message: Message, state: FSMContext):
    try:
        event_date = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("❌ Неверный формат. Нужно: ДД.ММ.ГГГГ ЧЧ:ММ")
        return

    if event_date <= datetime.now():
        await message.answer("❌ Эта дата уже прошла. Введите дату в будущем:")
        return

    await state.update_data(date=event_date)
    await state.set_state(CreateEvent.post_url)
    await message.answer("🔗 Ссылка на пост (или канал) LEMON в Telegram:")


@router.message(CreateEvent.post_url, F.text)
async def process_event_post_url(message: Message, state: FSMContext):
    url = normalize_tg_link(message.text)
    if not url:
        await message.answer("❌ Нужна ссылка на Telegram (например, https://t.me/lemon/123) или @канал")
        return

    await state.update_data(post_url=url)
    await state.set_state(CreateEvent.price_list)
    await message.answer("📋 Цена «По списку» (₽, 0 — бесплатно):")


@router.message(CreateEvent.price_list, F.text)
async def process_event_price_list(message: Message, state: FSMContext):
    price = parse_price(message.text)
    if price is None:
        await message.answer("❌ Введите целое число (0 или больше)")
        return

    await state.update_data(price_list=price)
    await state.set_state(CreateEvent.price_nolist)
    await message.answer("🚪 Цена «Без списка» (₽):")


@router.message(CreateEvent.price_nolist, F.text)
async def process_event_price_nolist(message: Message, state: FSMContext):
    price = parse_price(message.text)
    if price is None:
        await message.answer("❌ Введите целое число (0 или больше)")
        return

    await state.update_data(price_nolist=price)
    await state.set_state(CreateEvent.total_tickets)
    await message.answer("🎫 Сколько всего билетов?")


@router.message(CreateEvent.total_tickets, F.text)
async def process_event_tickets(message: Message, state: FSMContext):
    total_tickets = parse_price(message.text)
    if not total_tickets:
        await message.answer("❌ Введите целое число больше 0")
        return

    data = await state.get_data()

    event_id = await db.create_event(
        name=data['name'],
        date=data['date'],
        post_url=data['post_url'],
        price_list=data['price_list'],
        price_nolist=data['price_nolist'],
        total_tickets=total_tickets,
        created_by=message.from_user.id
    )

    await state.clear()
    await message.answer(
        f"✅ Мероприятие создано! ID: {event_id}\n\n"
        f"🎉 {data['name']}\n"
        f"📅 {data['date'].strftime('%d.%m.%Y %H:%M')}\n"
        f"📋 По списку — {data['price_list']}₽\n"
        f"🚪 Без списка — {data['price_nolist']}₽\n"
        f"🎫 Билетов: {total_tickets}"
    )


# ---------- Подарочные билеты ----------

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


@router.message(GiftTicket.event_id, F.text)
async def process_gift_event_id(message: Message, state: FSMContext):
    try:
        event_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите число")
        return

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


@router.message(GiftTicket.waiting_for_user)
async def process_gift_user(message: Message, state: FSMContext):
    target = extract_target_user(message)
    if target is None:
        await message.answer(TARGET_USER_ERROR)
        return

    user_id, username = target
    username = username or "Unknown"

    data = await state.get_data()
    event_id = data['event_id']
    event = await db.get_event(event_id)

    if not event:
        await message.answer("❌ Мероприятие не найдено")
        await state.clear()
        return

    qr_code = generate_unique_ticket_code()

    try:
        await db.create_ticket(
            event_id=event_id,
            user_id=user_id,
            username=username,
            qr_code=qr_code,
            ticket_type='gifted',
            gifted_by=message.from_user.id
        )
    except SoldOutError:
        await message.answer("❌ Билеты закончились")
        await state.clear()
        return
    except Exception:
        logger.exception("Gift ticket error")
        await message.answer("❌ Не удалось выдать билет. Подробности в логах.")
        await state.clear()
        return

    date_str = event['date'].strftime("%d.%m.%Y %H:%M")

    text = (
        "✅ Подарочный билет выдан!\n\n"
        f"🎉 {html.escape(event['name'])}\n"
        f"📅 {date_str}\n\n"
        f"👤 Получатель: {user_id}\n"
        f"🎫 Код: <code>{qr_code}</code>"
    )

    qr_bytes = (await make_ticket_qr(message.bot, qr_code)).read()
    await message.answer_photo(
        photo=BufferedInputFile(qr_bytes, filename="ticket_qr.png"),
        caption=text, parse_mode="HTML"
    )

    try:
        await message.bot.send_photo(
            chat_id=user_id,
            photo=BufferedInputFile(qr_bytes, filename="ticket_qr.png"),
            caption=f"🎁 Вам подарили билет!\n\n{text}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning("Не удалось отправить подарочный билет пользователю %s: %s", user_id, e)
        await message.answer(
            "⚠️ Не удалось отправить билет пользователю напрямую "
            "(возможно, он ещё не запускал бота). Билет есть в его разделе «Мои билеты»."
        )

    await state.clear()


@router.callback_query(F.data.regexp(r"^gift_\d+$"))
async def gift_from_event(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_id(callback.from_user.id):
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


# ---------- Статистика ----------

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
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ У вас нет прав администратора", show_alert=True)
        return

    stats = await db.get_all_statistics()

    if not stats:
        await callback.answer("📊 Нет данных", show_alert=True)
        return

    text = "📊 ОБЩАЯ СТАТИСТИКА\n\n"

    totals = dict(revenue=0, purchased=0, list=0, nolist=0, gifted=0, used=0)

    for stat in stats:
        text += f"🎉 {stat['name']}\n"
        text += f"📋 По списку: {stat['list_count']} · 🚪 Без списка: {stat['nolist_count']}\n"
        text += f"🎁 Подарено: {stat['gifted_count']}\n"
        text += f"✅ Использовано: {stat['used_count']}/{stat['total_sold']}\n"
        text += f"💰 Выручка: {stat['revenue']}₽\n"
        text += f"🎫 Осталось: {stat['available_tickets']}/{stat['total_tickets']}\n\n"

        totals['revenue'] += stat['revenue']
        totals['purchased'] += stat['purchased_count']
        totals['list'] += stat['list_count']
        totals['nolist'] += stat['nolist_count']
        totals['gifted'] += stat['gifted_count']
        totals['used'] += stat['used_count']

    text += "━━━━━━━━━━━━━━━━\n"
    text += "ИТОГО:\n"
    text += f"💳 Куплено билетов: {totals['purchased']} (📋 {totals['list']} · 🚪 {totals['nolist']})\n"
    text += f"🎁 Подарено билетов: {totals['gifted']}\n"
    text += f"✅ Использовано: {totals['used']}\n"
    text += f"💰 Общая выручка: {totals['revenue']}₽"

    await callback.message.edit_text(text, reply_markup=stats_menu_keyboard(stats))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^stats_\d+$"))
async def show_event_statistics(callback: CallbackQuery):
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ У вас нет прав администратора", show_alert=True)
        return

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

━━━━━━━━━━━━━━━━
📋 По списку: {stats['list_count']}
🚪 Без списка: {stats['nolist_count']}
🎁 Подарено: {stats['gifted_count']}
📦 Всего выдано: {stats['total_sold']}
✅ Использовано: {stats['used_count']}
🎫 Осталось: {event['available_tickets']}/{event['total_tickets']}

━━━━━━━━━━━━━━━━
💰 Выручка: {stats['revenue']}₽
    """

    events = await db.get_active_events()
    await callback.message.edit_text(text, reply_markup=stats_menu_keyboard(events))
    await callback.answer()


@router.callback_query(F.data == "close_stats")
async def close_statistics(callback: CallbackQuery):
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ У вас нет прав администратора", show_alert=True)
        return

    await callback.message.delete()
    await callback.answer()


# ---------- Добавление админов ----------

@router.message(F.text == "👥 Добавить админа")
async def start_add_admin(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Только главный админ может добавлять других админов")
        return

    await state.set_state(AddAdmin.waiting_for_id)
    await message.answer("👤 Отправьте ID пользователя или перешлите его сообщение:")


@router.message(AddAdmin.waiting_for_id)
async def process_add_admin(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return

    target = extract_target_user(message)
    if target is None:
        await message.answer(TARGET_USER_ERROR)
        return

    user_id, username = target
    await db.add_admin(user_id, username)
    await state.clear()
    await message.answer(f"✅ Пользователь {user_id} добавлен в список администраторов")


# ---------- Управление мероприятиями ----------

@router.message(F.text == "📋 Управление")
async def manage_events_menu(message: Message):
    if not await is_admin_filter(message):
        await message.answer("❌ У вас нет прав администратора")
        return

    events = await db.get_all_events()
    if not events:
        await message.answer("📋 Нет мероприятий. Создайте первое через «➕ Создать событие».")
        return

    await message.answer(
        "📋 Управление мероприятиями\n\nВыберите событие:",
        reply_markup=manage_events_keyboard(events)
    )


@router.callback_query(F.data == "manage_events_list")
async def manage_events_list_cb(callback: CallbackQuery):
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    events = await db.get_all_events()
    if not events:
        await callback.message.edit_text("📋 Нет мероприятий.")
        await callback.answer()
        return

    await callback.message.edit_text(
        "📋 Управление мероприятиями\n\nВыберите событие:",
        reply_markup=manage_events_keyboard(events)
    )
    await callback.answer()


@router.callback_query(F.data == "close_manage")
async def close_manage(callback: CallbackQuery):
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data.regexp(r"^manage_event_\d+$"))
async def manage_event_detail(callback: CallbackQuery):
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    event_id = int(callback.data.rsplit("_", 1)[1])
    event = await db.get_event(event_id)
    if not event:
        await callback.answer("❌ Не найдено", show_alert=True)
        return

    date_str = event['date'].strftime("%d.%m.%Y %H:%M")
    status = "активно ✅" if event.get('is_active') else "неактивно ⏸"
    text = (
        f"📋 {event['name']}\n\n"
        f"📅 {date_str}\n"
        f"Статус: {status}\n"
        f"📋 По списку: {event.get('price_list') or '—'}₽\n"
        f"🚪 Без списка: {event.get('price_nolist') or '—'}₽\n"
        f"🎫 Осталось: {event['available_tickets']} / {event['total_tickets']}\n"
    )
    if event.get('post_url'):
        text += f"🔗 {event['post_url']}\n"

    await callback.message.edit_text(text, reply_markup=manage_event_actions_keyboard(event))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^toggle_event_\d+$"))
async def toggle_event_active(callback: CallbackQuery):
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    event_id = int(callback.data.rsplit("_", 1)[1])
    event = await db.get_event(event_id)
    if not event:
        await callback.answer("❌ Не найдено", show_alert=True)
        return

    new_active = not event.get('is_active', True)
    await db.set_event_active(event_id, new_active)
    event = await db.get_event(event_id)

    status_word = "активировано" if new_active else "деактивировано"
    await callback.answer(f"✅ Мероприятие {status_word}")

    date_str = event['date'].strftime("%d.%m.%Y %H:%M")
    status = "активно ✅" if event.get('is_active') else "неактивно ⏸"
    text = (
        f"📋 {event['name']}\n\n"
        f"📅 {date_str}\n"
        f"Статус: {status}\n"
        f"📋 По списку: {event.get('price_list') or '—'}₽\n"
        f"🚪 Без списка: {event.get('price_nolist') or '—'}₽\n"
        f"🎫 Осталось: {event['available_tickets']} / {event['total_tickets']}\n"
    )
    if event.get('post_url'):
        text += f"🔗 {event['post_url']}\n"

    await callback.message.edit_text(text, reply_markup=manage_event_actions_keyboard(event))


@router.callback_query(F.data.regexp(r"^edit_name_\d+$"))
async def start_edit_name(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    event_id = int(callback.data.rsplit("_", 1)[1])
    await state.update_data(edit_event_id=event_id)
    await state.set_state(EditEvent.waiting_name)
    await callback.message.answer("✏️ Введите новое название мероприятия:")
    await callback.answer()


@router.message(EditEvent.waiting_name, F.text)
async def process_edit_name(message: Message, state: FSMContext):
    if not await is_admin_filter(message):
        await state.clear()
        return
    data = await state.get_data()
    event_id = data.get('edit_event_id')
    name = message.text.strip()
    if not name or len(name) > 200:
        await message.answer("❌ Название должно быть от 1 до 200 символов")
        return
    await db.update_event(event_id, name=name)
    await state.clear()
    await message.answer(f"✅ Название обновлено: {name}", reply_markup=admin_menu())


@router.callback_query(F.data.regexp(r"^edit_date_\d+$"))
async def start_edit_date(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    event_id = int(callback.data.rsplit("_", 1)[1])
    await state.update_data(edit_event_id=event_id)
    await state.set_state(EditEvent.waiting_date)
    await callback.message.answer(
        "📅 Введите новую дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "Например: 15.11.2026 20:00"
    )
    await callback.answer()


@router.message(EditEvent.waiting_date, F.text)
async def process_edit_date(message: Message, state: FSMContext):
    if not await is_admin_filter(message):
        await state.clear()
        return
    data = await state.get_data()
    event_id = data.get('edit_event_id')
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("❌ Неверный формат. Пример: 15.11.2026 20:00")
        return
    await db.update_event(event_id, date=dt)
    await state.clear()
    await message.answer(
        f"✅ Дата обновлена: {dt.strftime('%d.%m.%Y %H:%M')}",
        reply_markup=admin_menu()
    )


@router.callback_query(F.data.regexp(r"^edit_prices_\d+$"))
async def start_edit_prices(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    event_id = int(callback.data.rsplit("_", 1)[1])
    await state.update_data(edit_event_id=event_id)
    await state.set_state(EditEvent.waiting_price_list)
    await callback.message.answer("💰 Введите цену «По списку» (число в рублях):")
    await callback.answer()


@router.message(EditEvent.waiting_price_list, F.text)
async def process_edit_price_list(message: Message, state: FSMContext):
    if not await is_admin_filter(message):
        await state.clear()
        return
    price = parse_price(message.text)
    if price is None:
        await message.answer("❌ Введите целое число")
        return
    await state.update_data(price_list=price)
    await state.set_state(EditEvent.waiting_price_nolist)
    await message.answer("💰 Введите цену «Без списка» (число в рублях):")


@router.message(EditEvent.waiting_price_nolist, F.text)
async def process_edit_price_nolist(message: Message, state: FSMContext):
    if not await is_admin_filter(message):
        await state.clear()
        return
    price = parse_price(message.text)
    if price is None:
        await message.answer("❌ Введите целое число")
        return
    data = await state.get_data()
    event_id = data.get('edit_event_id')
    await db.update_event(event_id, price_list=data['price_list'], price_nolist=price)
    await state.clear()
    await message.answer(
        f"✅ Цены обновлены:\n📋 По списку — {data['price_list']}₽\n🚪 Без списка — {price}₽",
        reply_markup=admin_menu()
    )


@router.callback_query(F.data.regexp(r"^add_tickets_\d+$"))
async def start_add_tickets(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_id(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    event_id = int(callback.data.rsplit("_", 1)[1])
    await state.update_data(edit_event_id=event_id)
    await state.set_state(EditEvent.waiting_add_tickets)
    await callback.message.answer("🎫 Сколько билетов добавить? (целое число)")
    await callback.answer()


@router.message(EditEvent.waiting_add_tickets, F.text)
async def process_add_tickets(message: Message, state: FSMContext):
    if not await is_admin_filter(message):
        await state.clear()
        return
    count = parse_price(message.text)
    if not count or count <= 0:
        await message.answer("❌ Введите целое число больше 0")
        return
    data = await state.get_data()
    event_id = data.get('edit_event_id')
    ok = await db.add_tickets_to_event(event_id, count)
    await state.clear()
    if ok:
        event = await db.get_event(event_id)
        await message.answer(
            f"✅ Добавлено {count} билетов.\n"
            f"Теперь: {event['available_tickets']} / {event['total_tickets']}",
            reply_markup=admin_menu()
        )
    else:
        await message.answer("❌ Не удалось обновить", reply_markup=admin_menu())
