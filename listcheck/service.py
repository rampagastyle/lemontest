"""Оценка условий списка для человека и проверка на входе."""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import config
from database import db
from listcheck.tg_check import is_tg_subscribed
from listcheck.vk_api import get_vk_client

logger = logging.getLogger(__name__)


@dataclass
class ListState:
    config_problems: List[str] = field(default_factory=list)
    banned: bool = False
    quota: Optional[int] = None
    quota_left: Optional[int] = None
    has_list_ticket: bool = False
    tg_ok: Optional[bool] = None            # None — не удалось проверить (ошибка API)
    vk_linked: bool = False
    vk_id: Optional[int] = None
    vk_name: Optional[str] = None
    vk_ok: Optional[bool] = None            # None — не удалось проверить
    friends_ok: bool = False
    story_status: Optional[str] = None      # None | pending | approved | rejected | revoked
    story_attempts: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def path_ok(self) -> bool:
        return self.friends_ok or self.story_status == "approved"

    @property
    def quota_ok(self) -> bool:
        return self.quota_left is None or self.quota_left > 0

    @property
    def eligible(self) -> bool:
        """Можно ли прямо сейчас купить билет «По списку»."""
        return (
            not self.config_problems and not self.banned
            and self.tg_ok is True and self.vk_linked and self.vk_ok is True
            and self.path_ok and self.quota_ok and not self.has_list_ticket
        )

    def door_problems(self) -> List[str]:
        """Что не так с условиями (для проверки на входе: квота и «уже есть билет» не важны)."""
        problems = []
        if self.banned:
            problems.append("снят со списков")
        if self.tg_ok is False:
            problems.append("не подписан на Telegram LEMON")
        if not self.vk_linked:
            problems.append("ВК не привязан")
        elif self.vk_ok is False:
            problems.append("не подписан на ВК LEMON")
        if not self.path_ok:
            problems.append("не подтверждено условие (3 друга в ВК / сторис)")
        return problems

    def unknown(self) -> bool:
        return self.tg_ok is None or (self.vk_linked and self.vk_ok is None)


async def evaluate(bot, user_id: int, event: dict) -> ListState:
    state = ListState()
    state.config_problems = config.list_config_problems()
    if state.config_problems:
        return state

    event_id = event["id"]
    state.banned = await db.is_list_banned(user_id)
    state.quota = event.get("list_quota")
    if state.quota is not None:
        used = await db.count_list_tickets(event_id)
        state.quota_left = max(0, state.quota - used)
    state.has_list_ticket = await db.user_has_list_ticket(user_id, event_id)

    try:
        state.tg_ok = await is_tg_subscribed(bot, user_id)
    except Exception as e:
        logger.warning("Не удалось проверить подписку на ТГ для %s: %s", user_id, e)
        state.errors.append("tg")

    vk = get_vk_client()
    link = await db.get_vk_link(user_id)
    if link:
        state.vk_linked = True
        state.vk_id = link["vk_id"]
        state.vk_name = link.get("vk_name")
        try:
            state.vk_ok = await vk.is_member(link["vk_id"])
        except Exception as e:
            logger.warning("Не удалось проверить подписку на ВК для %s: %s", user_id, e)
            state.errors.append("vk")
        owner, post_id = event.get("vk_post_owner"), event.get("vk_post_id")
        if owner and post_id:
            state.friends_ok = await db.has_valid_vk_comment(link["vk_id"], owner, post_id)

    access = await db.get_list_access(event_id, user_id)
    state.story_status = access["status"] if access else None
    state.story_attempts = await db.count_story_attempts(event_id, user_id)
    return state


async def door_list_check(bot, ticket: dict) -> Optional[dict]:
    """Перепроверка на входе. None — проверять не нужно (не списочный билет или он выдан до включения проверки).

    При сбое сервисов не блокируем вход: возвращаем error/unknown, админ сверит вручную.
    """
    if not config.LIST_VERIFICATION:
        return None
    if ticket.get("ticket_type") != "purchased" or ticket.get("ticket_tier") != "list":
        return None
    if not ticket.get("list_verified"):
        return None

    try:
        event = await db.get_event(ticket["event_id"])
        state = await asyncio.wait_for(evaluate(bot, ticket["user_id"], event), timeout=8)
    except Exception:
        logger.exception("Door list check failed")
        return {"problems": [], "surcharge": 0, "unknown": False, "error": True}

    problems = state.door_problems()
    paid = ticket.get("price")
    if paid is None:
        paid = ticket.get("event_price_list") or 0
    surcharge = max(0, (ticket.get("event_price_nolist") or 0) - paid)
    return {
        "problems": problems,
        "surcharge": surcharge,
        "unknown": state.unknown() and not problems,
        "error": False,
    }
