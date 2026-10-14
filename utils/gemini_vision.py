"""Gemini Vision API для анализа скриншотов сторис."""
import google.generativeai as genai
import logging
from typing import Optional, Dict
import base64
from io import BytesIO
import config

logger = logging.getLogger(__name__)


class GeminiVisionAnalyzer:
    def __init__(self):
        if config.GEMINI_API_KEY:
            genai.configure(api_key=config.GEMINI_API_KEY)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    async def analyze_screenshot(self, image_bytes: bytes) -> Optional[Dict]:
        """Анализирует скриншот сторис через Gemini Vision.

        Возвращает: {
            'has_community_tag': bool,      # есть ли отметка сообщества
            'has_event_poster': bool,       # есть ли постер события
            'author_name': str or None,     # имя автора сторис
            'confidence': float,            # уверенность анализа
            'details': str                  # описание найденного
        }
        """
        if not config.GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY не установлен")
            return None

        try:
            # Кодируем изображение в base64
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')

            prompt = """Проанализируй этот скриншот VK сторис и ответь на вопросы:

1. Есть ли на скриншоте отметка сообщества VK (обычно выглядит как наклейка с названием сообщества)?
2. Есть ли постер события/мероприятия (изображение, текст события)?
3. Какое имя автора видно на сторис (если видно)?

Ответь в формате JSON:
{
  "has_community_tag": true/false,
  "has_event_poster": true/false,
  "author_name": "имя или null",
  "confidence": 0.0-1.0,
  "details": "краткое описание"
}

Будь точен — это используется для проверки подлинности."""

            response = self.model.generate_content(
                [
                    prompt,
                    {
                        'mime_type': 'image/jpeg',
                        'data': image_b64
                    }
                ]
            )

            import json
            try:
                result = json.loads(response.text)
                return result
            except json.JSONDecodeError:
                # Попробуем извлечь JSON из ответа
                import re
                json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    return result
                logger.warning(f"Не удалось парсить Gemini ответ: {response.text}")
                return None

        except Exception as e:
            logger.error(f"Gemini Vision error: {e}")
            return None

    def validate_author_match(self, author_name: str, vk_username: str) -> bool:
        """Сравнивает имя автора со VK-аккаунтом.

        Проверяет различные варианты совпадения.
        """
        if not author_name or not vk_username:
            return False

        author_lower = author_name.lower().strip()
        vk_lower = vk_username.lower().strip()

        # Точное совпадение
        if author_lower == vk_lower:
            return True

        # Совпадение без пробелов
        author_nospace = author_lower.replace(' ', '')
        vk_nospace = vk_lower.replace(' ', '')
        if author_nospace == vk_nospace:
            return True

        # Совпадение первого имени или части ника
        author_parts = author_lower.split()
        vk_parts = vk_lower.split()

        for ap in author_parts:
            for vp in vk_parts:
                if len(ap) > 2 and len(vp) > 2 and ap in vp or vp in ap:
                    return True

        return False


gemini_analyzer = GeminiVisionAnalyzer()
