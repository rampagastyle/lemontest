"""Проверка билетов на входе.

Как это работает:
1. Админ нажимает «✅ Проверка билетов» — включается режим проверки.
2. Админ сканирует QR камерой телефона. QR — это ссылка t.me/<бот>?start=t_<код>,
   Telegram открывает бота и отправляет ему код (или остаётся нажать «Start»/«Отправить»).
3. Бот сразу проверяет и активирует билет. Так можно проверять билеты подряд, без доп. кнопок.
4. «⏹ Выключить проверку» возвращает обычное меню.

Роутер подключается ПЕРВЫМ, чтобы /start t_... не перехватывался обычным /start.
"""
import logging
import re

from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from database import db
from keyboards import admin_menu, scan_menu
from utils import TICKET_PREFIX
from utils.formatting import ticket_kind, TIER_LIST

logger = logging.getLogger(__name__)
router = Router()

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class CheckTicket(StatesGroup):
    scanning = State()


def format_scan_result(ticket: dict) -> str:
    date_str = ticket['event_date'].strftime("%d.%m.%Y %H:%M")
    username = ticket.get('username')
    owner = f"@{username}" if username and username != "Unknown" else f"ID {ticket['user_id']}"

    body = (
        f"\n\n🎉 {ticket['event_name']}"
        f"\n📅 {date_str}"
        f"\n👤 {owner}"
        f"\n🏷 {ticket_kind(ticket)}"
    )

    if ticket['just_used']:
        head = "✅ ПРОХОД РАЗРЕШЁН"
        extra = ""
        if ticket.get('ticket_tier') == TIER_LIST:
            extra += "\n\n📋 Сверьте гостя со списком"
        if not ticket['event_is_active']:
            extra += "\n\n⚠️ Мероприятие помечено как неактивное"
    elif ticket['used_at']:
        used_str = ticket['used_at'].strftime("%d.%m.%Y %H:%M")
        head = "❌ БИЛЕТ УЖЕ ИСПОЛЬЗОВАН"
        extra = f"\n\n⚠️ Использован: {used_str}"
    else:
        head = "⚠️ БИЛЕТ НЕ АКТИВЕН"
        extra = f"\n\nСтатус: {ticket['status']}"

    return head + body + extra


async def check_code_and_reply(message: Message, code: str):
    if not UUID_RE.fullmatch(code):
        await message.answer("❌ Билет не найден")
        return

    ticket = await db.validate_and_use_ticket(code, message.from_user.id)
    if not ticket:
        await message.answer("❌ Билет не найден")
        return

    await message.answer(format_scan_result(ticket))


@router.message(F.text == "✅ Проверка билетов")
async def enable_scan_mode(message: Message, state: FSMContext):
    if not await db.is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав администратора")
        return

    await state.set_state(CheckTicket.scanning)
    await message.answer(
        "✅ Режим проверки включён\n\n"
        "Сканируйте QR-коды билетов камерой телефона — откроется бот, "
        "билет проверится сам (если Telegram просит, нажмите «Start»/«Отправить»).\n"
        "Код билета можно и просто вставить сообщением.",
        reply_markup=scan_menu()
    )


@router.message(F.text == "⏹ Выключить проверку")
async def disable_scan_mode(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⏹ Режим проверки выключен", reply_markup=admin_menu())


@router.message(CommandStart(deep_link=True, magic=F.args.startswith(TICKET_PREFIX)))
async def ticket_deep_link(message: Message, command: CommandObject, state: FSMContext):
    code = command.args[len(TICKET_PREFIX):]

    if not await db.is_admin(message.from_user.id):
        await message.answer(
            "🎫 Это QR-код билета.\n"
            "Покажите его на входе — проверять билеты могут только организаторы."
        )
        return

    if await state.get_state() != CheckTicket.scanning.state:
        await message.answer(
            "ℹ️ Режим проверки выключен.\n"
            "Нажмите «✅ Проверка билетов» и отсканируйте билет ещё раз."
        )
        return

    await check_code_and_reply(message, code)


@router.message(CheckTicket.scanning, F.text, ~F.text.startswith("/"))
async def scan_manual_input(message: Message):
    """Запасной вариант: админ вставил код билета (или всю ссылку из QR) текстом."""
    match = UUID_RE.search(message.text)
    if not match:
        await message.answer("🤔 Это не похоже на код билета. Отсканируйте QR или вставьте код.")
        return

    await check_code_and_reply(message, match.group(0))
