"""Экран условий списка и проверка допуска перед покупкой билета «По списку»."""
import logging
from typing import Tuple

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
from listcheck.service import ListState, evaluate
from utils.formatting import event_price, TIER_LIST, TIER_NOLIST

logger = logging.getLogger(__name__)


def tg_channel_url():
    if config.LEMON_TG_LINK:
        return config.LEMON_TG_LINK
    channel = config.LEMON_TG_CHANNEL
    if isinstance(channel, str) and channel.startswith("@"):
        return f"https://t.me/{channel[1:]}"
    return None


def vk_group_url() -> str:
    return f"https://vk.com/club{config.VK_GROUP_ID}"


def vk_write_url() -> str:
    return f"https://vk.me/club{config.VK_GROUP_ID}"


def _mark(value) -> str:
    return "✅" if value is True else ("❔" if value is None else "❌")


def build_conditions(event: dict, st: ListState) -> Tuple[str, InlineKeyboardMarkup]:
    event_id = event["id"]
    price_list = event_price(event, TIER_LIST)
    price_nolist = event_price(event, TIER_NOLIST)

    lines = [
        "📋 Билет «По списку»",
        f"🎉 {event['name']}",
        f"💰 {price_list}₽ (без списка — {price_nolist}₽)",
        "",
    ]
    back = [InlineKeyboardButton(text="◀️ К мероприятию", callback_data=f"event_{event_id}")]

    if st.config_problems:
        lines.append("⚠️ Проверка списков пока не настроена. Вы можете взять билет «Без списка» "
                     "или написать в поддержку.")
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[back])

    if st.banned:
        lines.append("🚫 Список для вас недоступен. Билет «Без списка» купить можно.")
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[back])

    if st.has_list_ticket:
        lines.append("ℹ️ У вас уже есть билет «По списку» на это мероприятие (один на человека).")
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[back])

    if st.quota is not None:
        if st.quota_left == 0:
            lines.append("😔 Места «По списку» закончились. Билет «Без списка» ещё можно купить.")
            return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[back])
        lines.append(f"🎟 Мест по списку осталось: {st.quota_left} из {st.quota}")
        lines.append("")

    lines.append("Условия:")
    lines.append(f"{_mark(st.tg_ok)} Подписка на LEMON в Telegram")
    if not st.vk_linked:
        lines.append("❌ ВК не привязан (нужен для проверки подписки)")
    else:
        lines.append(f"{_mark(st.vk_ok)} Подписка на LEMON во ВКонтакте ({st.vk_name or 'профиль привязан'})")
    lines.append("")
    if config.LIST_REQUIRE_BOTH:
        lines.append("Плюс оба условия:" if st.friends_available else "Плюс условие:")
    else:
        lines.append("Плюс одно из двух:")
    if st.friends_available or not config.LIST_REQUIRE_BOTH:
        friends_line = f"{_mark(st.friends_ok)} 👥 Отметить 3 друзей в комментарии под постом в ВК"
        if not st.friends_available:
            friends_line += " (для этого мероприятия недоступно)"
        lines.append(friends_line)
    story_marks = {"approved": "✅", "pending": "⏳"}
    story_line = f"{story_marks.get(st.story_status, '❌')} 📸 Сторис с отметкой LEMON (скриншот)"
    if st.story_status == "pending":
        story_line += " — на проверке у администратора"
    lines.append(story_line)
    story_blocked = st.story_status not in ("approved", "pending") and st.story_attempts >= config.STORY_MAX_ATTEMPTS
    if story_blocked and (config.LIST_REQUIRE_BOTH or not st.friends_ok):
        lines.append("⚠️ Попытки отправки сторис закончились. Напишите в поддержку или возьмите билет «Без списка».")

    if st.errors:
        lines.append("")
        lines.append("⚠️ Часть проверок не удалась (сбой сервиса). Попробуйте «Проверить» ещё раз чуть позже.")

    rows = []
    if st.eligible:
        lines.append("")
        lines.append("✅ Все условия выполнены!")
        rows.append([InlineKeyboardButton(text=f"🎟 Купить по списку — {price_list}₽",
                                          callback_data=f"buy_{event_id}_{TIER_LIST}")])
    else:
        tg_url = tg_channel_url()
        if st.tg_ok is not True and tg_url:
            rows.append([InlineKeyboardButton(text="📣 Подписаться в Telegram", url=tg_url)])
        if not st.vk_linked:
            rows.append([InlineKeyboardButton(text="🔗 Привязать ВК", callback_data=f"lst_{event_id}_link")])
        else:
            if st.vk_ok is False:
                rows.append([InlineKeyboardButton(text="📣 Подписаться во ВК", url=vk_group_url())])
            if not st.path_ok:
                if event.get("vk_post_url") and not st.friends_ok:
                    rows.append([InlineKeyboardButton(text="👥 Пост в ВК (отметить 3 друзей)",
                                                      url=event["vk_post_url"])])
                if st.story_status not in ("approved", "pending") and st.story_attempts < config.STORY_MAX_ATTEMPTS:
                    rows.append([InlineKeyboardButton(text="📸 Отправить скриншот сторис",
                                                      callback_data=f"lst_{event_id}_story")])
        rows.append([InlineKeyboardButton(text="🔄 Проверить", callback_data=f"lst_{event_id}_check")])
    rows.append(back)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def show_conditions(callback, event: dict, st: ListState = None):
    """Показывает экран условий, заменяя текущее сообщение."""
    if st is None:
        st = await evaluate(callback.bot, callback.from_user.id, event)
    text, markup = build_conditions(event, st)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception as e:
        if "not modified" not in str(e).lower():
            await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


async def ensure_list_access(callback, event: dict) -> bool:
    """True — можно продолжать покупку «По списку». Иначе показан экран условий."""
    if not config.LIST_VERIFICATION:
        return True
    st = await evaluate(callback.bot, callback.from_user.id, event)
    if st.eligible:
        return True
    await show_conditions(callback, event, st)
    return False
