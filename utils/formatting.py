from typing import Optional

TIER_LIST = "list"
TIER_NOLIST = "nolist"

TIER_LABELS = {
    TIER_LIST: "📋 По списку",
    TIER_NOLIST: "🚪 Без списка",
}


def event_price(event: dict, tier: str) -> int:
    """Цена события для выбранного варианта (по списку / без списка)."""
    value = event.get('price_list') if tier == TIER_LIST else event.get('price_nolist')
    if value is None:
        value = event.get('price') or 0
    return value


def price_range(event: dict) -> str:
    a = event_price(event, TIER_LIST)
    b = event_price(event, TIER_NOLIST)
    if a == b:
        return f"{a}₽"
    return f"{min(a, b)}–{max(a, b)}₽"


def ticket_kind(ticket: dict) -> str:
    """Подпись типа билета: подарочный / по списку / без списка / куплен (старые билеты)."""
    if ticket.get('ticket_type') == 'gifted':
        return "🎁 Подарочный"
    tier: Optional[str] = ticket.get('ticket_tier')
    return TIER_LABELS.get(tier, "💳 Куплен")
