import html
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import db, SoldOutError, ListQuotaError, ListLimitError
from keyboards import (
    main_menu, admin_menu, events_list_keyboard, event_detail_keyboard,
    confirm_purchase_keyboard, my_tickets_events_keyboard, ticket_keyboard
)
from utils import generate_unique_ticket_code, make_ticket_qr
from utils.formatting import TIER_LABELS, TIER_LIST, event_price, ticket_kind
from listcheck.flow import ensure_list_access
import config

logger = logging.getLogger(__name__)
router = Router()

# Тексты кнопок меню: если пользователь нажал кнопку, пока бот ждёт сообщение в поддержку,
# то ожидание отменяется, а не отправляется в поддержку как «вопрос».
MENU_TEXTS = {
    "🎫 Мероприятия", "🎟 Мои билеты", "💬 Поддержка", "ℹ️ О боте", "📋 Проверить список",
    "➕ Создать событие", "📋 Управление", "🎁 Выдать билет", "📊 Статистика",
    "✅ Проверка билетов", "⏹ Выключить проверку", "👥 Добавить админа",
}


class SupportRequest(StatesGroup):
    waiting_message = State()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
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


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    is_admin = await db.is_admin(message.from_user.id)
    await message.answer("Действие отменено.", reply_markup=admin_menu() if is_admin else main_menu())


@router.message(F.text == "🎫 Мероприятия")
async def show_events(message: Message):
    events = await db.get_active_events()

    if not events:
        await message.answer("😔 Пока нет доступных мероприятий. Загляните позже!")
        return

    text = "🎉 Доступные мероприятия:"
    await message.answer(text, reply_markup=events_list_keyboard(events))


@router.callback_query(F.data.regexp(r"^event_\d+$"))
async def show_event_detail(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[1])
    event = await db.get_event(event_id)

    if not event:
        await callback.answer("❌ Мероприятие не найдено", show_alert=True)
        return

    date_str = event['date'].strftime("%d.%m.%Y %H:%M")
    is_admin = await db.is_admin(callback.from_user.id)

    text = (
        f"🎉 {event['name']}\n\n"
        f"📅 {date_str}\n"
        f"🎫 Доступно билетов: {event['available_tickets']} из {event['total_tickets']}\n\n"
        "Выберите вариант билета:\n"
        "⚠️ Тестовый режим — оплата не требуется"
    )

    await callback.message.edit_text(text, reply_markup=event_detail_keyboard(event, is_admin))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^buy_\d+_(list|nolist)$"))
async def process_buy_ticket(callback: CallbackQuery):
    _, event_id, tier = callback.data.split("_")
    event_id = int(event_id)
    event = await db.get_event(event_id)

    if not event:
        await callback.answer("❌ Мероприятие не найдено", show_alert=True)
        return

    if event['available_tickets'] <= 0:
        await callback.answer("❌ Билеты закончились", show_alert=True)
        return

    # «По списку» доступен только после проверки условий (подписки, друзья в ВК или сторис)
    if tier == TIER_LIST and config.LIST_VERIFICATION:
        if not await ensure_list_access(callback, event):
            return

    already = await db.count_user_tickets_for_event(callback.from_user.id, event_id)

    warn = ""
    if already > 0:
        warn = (
            f"\n⚠️ У вас уже есть {already} билет(а/ов) на это мероприятие.\n"
            "Вы можете купить ещё один.\n"
        )

    text = (
        "🎫 Покупка билета (ТЕСТОВЫЙ РЕЖИМ)\n\n"
        f"Мероприятие: {event['name']}\n"
        f"Вариант: {TIER_LABELS[tier]}\n"
        f"Цена: {event_price(event, tier)}₽\n"
        f"{warn}\n"
        "⚠️ Это тестовая покупка — оплата не требуется!\n"
        "Просто подтвердите получение билета."
    )

    await callback.message.edit_text(
        text, reply_markup=confirm_purchase_keyboard(event_id, tier, already_has=already)
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^confirm_buy_\d+_(list|nolist)$"))
async def confirm_purchase(callback: CallbackQuery):
    _, _, event_id, tier = callback.data.split("_")
    event_id = int(event_id)
    event = await db.get_event(event_id)

    if not event:
        await callback.answer("❌ Мероприятие не найдено", show_alert=True)
        return

    # Повторная проверка на сервере: кнопку подтверждения нельзя использовать в обход условий
    list_checked = tier == TIER_LIST and config.LIST_VERIFICATION
    if list_checked:
        if not await ensure_list_access(callback, event):
            return

    qr_code = generate_unique_ticket_code()

    try:
        await db.create_ticket(
            event_id=event_id,
            user_id=callback.from_user.id,
            username=callback.from_user.username or "Unknown",
            qr_code=qr_code,
            ticket_type='purchased',
            ticket_tier=tier,
            price=event_price(event, tier),
            list_verified=list_checked
        )
    except SoldOutError:
        await callback.answer("❌ Билеты закончились", show_alert=True)
        return
    except ListQuotaError:
        await callback.answer("😔 Места «По списку» закончились. Билет «Без списка» ещё можно купить.",
                              show_alert=True)
        return
    except ListLimitError:
        await callback.answer("ℹ️ У вас уже есть билет «По списку» на это мероприятие (один на человека).",
                              show_alert=True)
        return
    except Exception:
        logger.exception("Ticket creation error")
        await callback.answer("❌ Ошибка при выдаче билета", show_alert=True)
        return

    qr_image = await make_ticket_qr(callback.bot, qr_code)
    date_str = event['date'].strftime("%d.%m.%Y %H:%M")

    text = (
        "✅ Билет успешно получен!\n\n"
        f"🎉 {html.escape(event['name'])}\n"
        f"📅 {date_str}\n"
        f"🏷 {TIER_LABELS[tier]}\n\n"
        f"Код: <code>{qr_code}</code>\n\n"
        "Покажите этот QR-код на входе."
    )

    photo = BufferedInputFile(qr_image.read(), filename="ticket_qr.png")
    await callback.message.answer_photo(photo=photo, caption=text, parse_mode="HTML")
    await callback.message.delete()
    await callback.answer("✅ Билет получен!")


@router.callback_query(F.data == "back_to_events")
async def back_to_events(callback: CallbackQuery):
    events = await db.get_active_events()
    if not events:
        await callback.message.edit_text("😔 Пока нет доступных мероприятий. Загляните позже!")
        await callback.answer()
        return
    text = "🎉 Доступные мероприятия:"
    await callback.message.edit_text(text, reply_markup=events_list_keyboard(events))
    await callback.answer()


@router.message(F.text == "🎟 Мои билеты")
@router.callback_query(F.data == "my_tickets")
async def show_my_tickets(event):
    """Показывает список мероприятий, на которые есть билеты."""
    user_id = event.from_user.id

    if isinstance(event, CallbackQuery):
        message = event.message
        is_callback = True
    else:
        message = event
        is_callback = False

    events = await db.get_user_events_with_tickets(user_id)

    if not events:
        text = "У вас пока нет билетов. Купите билет на мероприятие!"
        if is_callback:
            await message.edit_text(text)
            await event.answer()
        else:
            await message.answer(text)
        return

    text = "🎟 Ваши билеты\n\nВыберите мероприятие:"
    kb = my_tickets_events_keyboard(events)

    if is_callback:
        await message.edit_text(text, reply_markup=kb)
        await event.answer()
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.regexp(r"^my_tickets_event_\d+$"))
async def show_tickets_for_event(callback: CallbackQuery):
    """Показывает все билеты пользователя на выбранное мероприятие."""
    event_id = int(callback.data.rsplit("_", 1)[1])
    user_id = callback.from_user.id

    tickets = await db.get_user_tickets_for_event(user_id, event_id)
    if not tickets:
        await callback.answer("Билетов не найдено", show_alert=True)
        return

    event_name = tickets[0]['event_name']
    date_str = tickets[0]['event_date'].strftime("%d.%m.%Y %H:%M")

    await callback.message.edit_text(
        f"🎟 Билеты на «{html.escape(event_name)}»\n📅 {date_str}\n\n"
        f"Всего: {len(tickets)}. Отправляю QR-коды…"
    )
    await callback.answer()

    for i, ticket in enumerate(tickets, 1):
        status = "✅ Использован" if ticket['used_at'] else "🎫 Активен"
        text = (
            f"🎉 {html.escape(ticket['event_name'])}\n"
            f"📅 {date_str}\n\n"
            f"Билет {i}/{len(tickets)}\n"
            f"Статус: {status}\n"
            f"Тип: {ticket_kind(ticket)}\n"
            f"Код: <code>{ticket['qr_code']}</code>"
        )
        qr_image = await make_ticket_qr(callback.bot, ticket['qr_code'])
        photo = BufferedInputFile(qr_image.read(), filename="ticket_qr.png")
        await callback.message.answer_photo(
            photo=photo, caption=text, parse_mode="HTML",
            reply_markup=ticket_keyboard() if i == len(tickets) else None
        )


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


# ---------- Поддержка ----------

@router.message(F.text == "💬 Поддержка")
async def support_info(message: Message, state: FSMContext):
    await state.set_state(SupportRequest.waiting_message)
    await message.answer(
        "💬 Техническая поддержка\n\n"
        "Напишите ваш вопрос следующим сообщением, и мы свяжемся с вами в ближайшее время.\n\n"
        "Для отмены отправьте /cancel"
    )


@router.message(SupportRequest.waiting_message, F.text)
async def receive_support_message(message: Message, state: FSMContext):
    if message.text in MENU_TEXTS:
        await state.clear()
        await message.answer("Обращение отменено. Нажмите нужную кнопку ещё раз.")
        return

    username = message.from_user.username
    request_id = await db.create_support_request(
        user_id=message.from_user.id,
        username=username or "Unknown",
        message=message.text
    )
    await state.clear()
    await message.answer(f"✅ Спасибо! Обращение №{request_id} принято. Мы скоро свяжемся с вами.")

    admin_text = (
        f"💬 Новое обращение в поддержку №{request_id}\n\n"
        f"От: {message.from_user.full_name} "
        f"({'@' + username if username else 'без username'}), ID: <code>{message.from_user.id}</code>\n\n"
        f"{html.escape(message.text)}"
    )
    admin_ids = set(config.ADMIN_IDS) | set(await db.get_admin_ids())
    for admin_id in admin_ids:
        try:
            await message.bot.send_message(admin_id, admin_text, parse_mode="HTML")
        except Exception as e:
            logger.warning("Не удалось уведомить админа %s: %s", admin_id, e)


@router.message(SupportRequest.waiting_message)
async def support_non_text(message: Message):
    await message.answer("Пожалуйста, опишите вопрос текстом или отправьте /cancel для отмены.")
