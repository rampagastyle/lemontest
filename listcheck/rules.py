"""Чистая логика без сети и БД: разбор отметок, ссылок, имён, решения по сторис, хеш картинки."""
import difflib
import json
import re
from io import BytesIO
from typing import Optional, Set, Tuple

MENTION_RE = re.compile(r"\[([A-Za-z0-9_.]+)\|[^\]]*\]")
COMMUNITY_RE = re.compile(r"(club|public|event)\d+")
VK_POST_RE = re.compile(r"wall(-?\d+)_(\d+)")
LINK_CODE_RE = re.compile(r"LEMON-[A-Z0-9]{6}", re.IGNORECASE)


def extract_mentions(text: str) -> Tuple[Set[int], Set[str]]:
    """Отметки вида [id123|Имя] -> id; [durov|Имя] -> короткое имя (его надо превратить в id через API).

    Отметки сообществ ([club1|..], [public1|..]) игнорируются.
    """
    ids: Set[int] = set()
    names: Set[str] = set()
    for match in MENTION_RE.finditer(text or ""):
        token = match.group(1)
        if re.fullmatch(r"id\d+", token):
            ids.add(int(token[2:]))
        elif COMMUNITY_RE.fullmatch(token):
            continue
        else:
            names.add(token.lower())
    return ids, names


def parse_vk_post_url(url: str) -> Optional[Tuple[int, int, str]]:
    """Ссылка на пост ВК -> (owner_id, post_id, нормализованная ссылка) или None."""
    url = (url or "").strip()
    if not re.search(r"(?:vk\.com|vk\.ru)/", url):
        return None
    match = VK_POST_RE.search(url)
    if not match:
        return None
    owner, post = int(match.group(1)), int(match.group(2))
    return owner, post, f"https://vk.com/wall{owner}_{post}"


def find_link_code(text: str) -> Optional[str]:
    match = LINK_CODE_RE.search(text or "")
    return match.group(0).upper() if match else None


def _tokens(value: str):
    return re.findall(r"[a-zа-я0-9]+", (value or "").lower().replace("ё", "е"))


def names_match(vk_name: str, shown_name: str) -> bool:
    """Имя в профиле ВК совпадает с именем автора на скриншоте (порядок слов не важен, опечатки терпим)."""
    a, b = _tokens(vk_name), _tokens(shown_name)
    if not a or not b:
        return False
    need = min(2, len(a))
    hits = sum(
        1 for token_a in a
        if any(difflib.SequenceMatcher(None, token_a, token_b).ratio() >= 0.8 for token_b in b)
    )
    return hits >= need


def parse_ai_json(text: str) -> Optional[dict]:
    """Достаёт JSON-объект из ответа модели (с ограждением ``` или текстом вокруг)."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    candidates = [cleaned]
    braces = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if braces:
        candidates.append(braces.group(0))
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def normalize_ai(data: dict) -> dict:
    def as_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "да")
        return None if value is None else bool(value)

    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "is_story": as_bool(data.get("is_story")),
        "lemon_mention": as_bool(data.get("lemon_mention")),
        "event_content_visible": as_bool(data.get("event_content_visible")),
        "author_name": (data.get("author_name") or "").strip() if isinstance(data.get("author_name"), str) else "",
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": str(data.get("reason") or "")[:300],
    }


def decide_story(ai: dict, name_ok: Optional[bool], min_confidence: float = 0.7) -> Tuple[str, str]:
    """Решение по скриншоту сторис: ('approve'|'reject'|'review', причина)."""
    confidence = ai.get("confidence") or 0.0

    if confidence >= 0.6:
        if ai.get("is_story") is False:
            return "reject", "Это не похоже на скриншот сторис."
        if ai.get("lemon_mention") is False:
            return "reject", "В сторис не видно отметку LEMON."

    if ai.get("is_story") is not True or ai.get("lemon_mention") is not True:
        return "review", "ИИ не уверен, что это сторис с отметкой LEMON"
    if confidence < min_confidence:
        return "review", f"низкая уверенность ИИ ({confidence:.2f})"
    if ai.get("event_content_visible") is False:
        return "review", "не видна публикация о мероприятии"
    if not ai.get("author_name"):
        return "review", "не виден автор сторис"
    if not name_ok:
        return "review", f"имя автора на скриншоте («{ai.get('author_name')}») не совпало с профилем ВК"
    return "approve", "все проверки пройдены"


def average_hash(data: bytes) -> str:
    """Перцептивный хеш 8x8 (16 hex-символов): одинаковые и слегка пережатые картинки дают близкие значения."""
    from PIL import Image
    image = Image.open(BytesIO(data)).convert("L").resize((8, 8))
    pixels = list(image.tobytes())
    average = sum(pixels) / len(pixels)
    bits = 0
    for pixel in pixels:
        bits = (bits << 1) | (1 if pixel >= average else 0)
    return f"{bits:016x}"


def hamming(hash_a: str, hash_b: str) -> int:
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")
