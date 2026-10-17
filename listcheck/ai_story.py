"""Проверка скриншота сторис через ИИ с поддержкой изображений (Gemini или Claude)."""
import base64
import logging

import aiohttp

import config
from listcheck.rules import parse_ai_json, normalize_ai

logger = logging.getLogger(__name__)


class AiError(Exception):
    pass


PROMPT = """Ты проверяешь скриншот истории (сторис) из ВКонтакте или Telegram.
Нужно определить, выложил ли человек сторис с отметкой сообщества/канала LEMON (упоминание @lemon, club..., \
название LEMON в отметке или подписи) и публикацией о мероприятии «{event}».

Ответь ТОЛЬКО JSON-объектом без пояснений, с полями:
- "is_story": true, если это скриншот именно сторис (вертикальная история с интерфейсом ВК/Telegram), иначе false
- "lemon_mention": true, если в сторис видна отметка/упоминание LEMON, иначе false
- "event_content_visible": true, если видна публикация/постер этого мероприятия, false если явно другое, null если непонятно
- "author_name": имя автора сторис, как оно написано вверху истории, или "" если не видно
- "confidence": число от 0 до 1 — насколько ты уверен в ответе
- "reason": короткое объяснение на русском (до 150 символов)

Не выдумывай: если не видно — ставь false или пустую строку, а confidence понижай."""


async def _gemini(image: bytes, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image).decode()}},
        ]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post(url, json=body, headers={"x-goog-api-key": config.GEMINI_API_KEY}) as response:
            data = await response.json(content_type=None)
            if response.status != 200:
                raise AiError(f"Gemini HTTP {response.status}: {str(data)[:200]}")
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise AiError(f"Неожиданный ответ Gemini: {str(data)[:200]}")


async def _anthropic(image: bytes, prompt: str) -> str:
    body = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": 400,
        "temperature": 0,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(image).decode()}},
            {"type": "text", "text": prompt},
        ]}],
    }
    headers = {"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post("https://api.anthropic.com/v1/messages", json=body, headers=headers) as response:
            data = await response.json(content_type=None)
            if response.status != 200:
                raise AiError(f"Anthropic HTTP {response.status}: {str(data)[:200]}")
    try:
        return "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
    except (KeyError, TypeError):
        raise AiError(f"Неожиданный ответ Anthropic: {str(data)[:200]}")


async def analyze_story(image: bytes, event_name: str) -> dict:
    """Возвращает нормализованный разбор скриншота. Бросает AiError, если ИИ недоступен или ответил мусором."""
    prompt = PROMPT.format(event=event_name)
    if config.AI_PROVIDER == "anthropic":
        text = await _anthropic(image, prompt)
    else:
        text = await _gemini(image, prompt)
    data = parse_ai_json(text)
    if data is None:
        raise AiError(f"Не удалось разобрать ответ ИИ: {text[:200]}")
    return normalize_ai(data)
