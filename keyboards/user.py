from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎫 Мероприятия"), KeyboardButton(text="🎟 Мои билеты")],
            [KeyboardButton(text="💬 Поддержка"), KeyboardButton(text="ℹ️ О боте")]
        ],
        resize_keyboard=True
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎫 Мероприятия"), KeyboardButton(text="🎟 Мои билеты")],
            [KeyboardButton(text="➕ Создать событие"), KeyboardButton(text="🎁 Выдать билет")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="✅ Проверить билет")],
            [KeyboardButton(text="👥 Добавить админа"), KeyboardButton(text="💬 Поддержка")]
        ],
        resize_keyboard=True
    )


def events_list_keyboard(events):
    buttons = []
    for event in events:
        buttons.append([InlineKeyboardButton(
            text=f"{event['name']} - {event['price']}₽",
            callback_data=f"event_{event['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def event_detail_keyboard(event_id, is_admin=False):
    buttons = [[InlineKeyboardButton(text="🎫 Купить билет (ТЕСТ)", callback_data=f"buy_{event_id}")]]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🎁 Подарить билет", callback_data=f"gift_{event_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_events")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_purchase_keyboard(event_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить покупку (ТЕСТ)", callback_data=f"confirm_buy_{event_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_events")]
    ])


def ticket_keyboard(ticket_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К билетам", callback_data="my_tickets")]
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
