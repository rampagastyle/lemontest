import os
import re
from typing import List
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [int(id_.strip()) for id_ in os.getenv("ADMIN_IDS", "").split(",") if id_.strip()]

# ---------- Проверка списков (подписки, друзья в ВК, сторис) ----------
# Выключено по умолчанию: пока флаг не включён, бот работает как раньше.
LIST_VERIFICATION = _bool("LIST_VERIFICATION", False)
# 1 — нужны ОБА условия: 3 друга в ВК И сторис (по умолчанию). 0 — достаточно одного из двух.
LIST_REQUIRE_BOTH = _bool("LIST_REQUIRE_BOTH", True)

# Канал LEMON в Telegram: @name или числовой id (-100...). Бот должен быть админом канала.
_channel = (os.getenv("LEMON_TG_CHANNEL") or "").strip()
LEMON_TG_CHANNEL = int(_channel) if re.fullmatch(r"-?\d+", _channel) else (_channel or None)
LEMON_TG_LINK = (os.getenv("LEMON_TG_LINK") or "").strip() or None   # ссылка для кнопки «Подписаться»

# Сообщество LEMON во ВКонтакте: токен сообщества и числовой id (без минуса)
VK_TOKEN = (os.getenv("VK_TOKEN") or "").strip() or None
VK_GROUP_ID = int(os.getenv("VK_GROUP_ID", "0") or 0)
VK_API_VERSION = os.getenv("VK_API_VERSION", "5.199")
LINK_CODE_TTL_MIN = 15          # сколько минут живёт код привязки ВК

# ИИ для проверки скриншотов сторис: gemini | anthropic
AI_PROVIDER = (os.getenv("AI_PROVIDER") or "gemini").strip().lower()
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip() or None
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")

STORY_MAX_ATTEMPTS = int(os.getenv("STORY_MAX_ATTEMPTS", "3"))      # попыток отправить скриншот на событие
STORY_AUDIT_PERCENT = int(os.getenv("STORY_AUDIT_PERCENT", "15"))   # % авто-одобренных, которые уходят админу на аудит


def list_config_problems() -> List[str]:
    """Какие настройки нужны для проверки списков, но не заданы."""
    problems = []
    if not LEMON_TG_CHANNEL:
        problems.append("LEMON_TG_CHANNEL")
    if not VK_TOKEN:
        problems.append("VK_TOKEN")
    if not VK_GROUP_ID:
        problems.append("VK_GROUP_ID")
    if AI_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            problems.append("GEMINI_API_KEY")
    elif AI_PROVIDER == "anthropic":
        if not ANTHROPIC_API_KEY:
            problems.append("ANTHROPIC_API_KEY")
    else:
        problems.append("AI_PROVIDER (gemini или anthropic)")
    return problems
