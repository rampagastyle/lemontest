from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

from utils.formatting import price_range, event_price, TIER_LIST, TIER_NOLIST


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎫 Мероприятия"), KeyboardButton(text="🎟 Мои билеты")],
            [KeyboardButton(text="📋 Проверить список"), KeyboardButton(text="💬 Поддержка")],
            [KeyboardButton(text="ℹ️ О боте")]
        ],
        resize_keyboard=True
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎫 Мероприятия"), KeyboardButton(text="🎟 Мои билеты")],
            [KeyboardButton(text="➕ Создать событие"), KeyboardButton(text="📋 Управление")],
            [KeyboardButton(text="🎁 Выдать билет"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="✅ Проверка билетов"), KeyboardButton(text="👥 Добавить админа")],
            [KeyboardButton(text="💬 Поддержка")]
        ],
        resize_keyboard=True
    )


def scan_menu():
    """Клавиатура, пока включён режим проверки билетов."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⏹ Выключить проверку")]],
        resize_keyboard=True
    )


def events_list_keyboard(events):
    buttons = []
    for event in events:
        buttons.append([InlineKeyboardButton(
            text=f"{event['name']} — {price_range(event)}",
            callback_data=f"event_{event['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def event_detail_keyboard(event, is_admin=False):
    event_id = event['id']
    buttons = []
    if event.get('post_url'):
        buttons.append([InlineKeyboardButton(text="🔗 Пост о мероприятии", url=event['post_url'])])
    buttons.append([InlineKeyboardButton(
        text=f"📋 По списку — {event_price(event, TIER_LIST)}₽",
        callback_data=f"buy_{event_id}_{TIER_LIST}"
    )])
    buttons.append([InlineKeyboardButton(
        text=f"🚪 Без списка — {event_price(event, TIER_NOLIST)}₽",
        callback_data=f"buy_{event_id}_{TIER_NOLIST}"
    )])
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🎁 Подарить билет", callback_data=f"gift_{event_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_events")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_purchase_keyboard(event_id, tier, already_has: int = 0):
    """Клавиатура подтверждения. already_has — сколько билетов уже есть (для предупреждения)."""
    buttons = [
        [InlineKeyboardButton(text="✅ Подтвердить (ТЕСТ)", callback_data=f"confirm_buy_{event_id}_{tier}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"event_{event_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def my_tickets_events_keyboard(events):
    """Список мероприятий, на которые у пользователя есть билеты."""
    buttons = []
    for event in events:
        count = event.get('tickets_count', 0)
        label = f"{event['name']} ({count})"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"my_tickets_event_{event['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def ticket_keyboard(ticket_id=None):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К билетам", callback_data="my_tickets")]
    ])


def manage_events_keyboard(events):
    """Список всех мероприятий для управления."""
    buttons = []
    for event in events:
        status = "✅" if event.get('is_active') else "⏸"
        date_str = event['date'].strftime("%d.%m") if event.get('date') else ""
        buttons.append([InlineKeyboardButton(
            text=f"{status} {event['name']} ({date_str})",
            callback_data=f"manage_event_{event['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Закрыть", callback_data="close_manage")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def manage_event_actions_keyboard(event):
    """Действия над одним мероприятием."""
    event_id = event['id']
    active = event.get('is_active', True)
    toggle_text = "⏸ Деактивировать" if active else "✅ Активировать"
    toggle_data = f"toggle_event_{event_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_data)],
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"edit_name_{event_id}")],
        [InlineKeyboardButton(text="📅 Изменить дату", callback_data=f"edit_date_{event_id}")],
        [InlineKeyboardButton(text="💰 Изменить цены", callback_data=f"edit_prices_{event_id}")],
        [InlineKeyboardButton(text="🎫 Добавить билеты", callback_data=f"add_tickets_{event_id}")],
        [InlineKeyboardButton(text="◀️ К списку", callback_data="manage_events_list")],
    ])


def stats_menu_keyboard(events):
    buttons = [[InlineKeyboardButton(text="📊 Общая статистика", callback_data="stats_all")]]
    for event in events:
        buttons.append([InlineKeyboardButton(
            text=f"📈 {event['name']}",
            callback_data=f"stats_{event['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="close_stats")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
