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
            [KeyboardButton(text="➕ Создать событие"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="✅ Проверить билет"), KeyboardButton(text="👥 Добавить админа")],
            [KeyboardButton(text="💬 Поддержка"), KeyboardButton(text="ℹ️ О боте")]
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


def event_detail_keyboard(event_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎫 Купить билет", callback_data=f"buy_{event_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_events")]
    ])


def payment_keyboard(payment_url):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_payment")]
    ])


def ticket_keyboard(ticket_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать QR-код", callback_data=f"download_qr_{ticket_id}")],
        [InlineKeyboardButton(text="◀️ К билетам", callback_data="my_tickets")]
    ])
