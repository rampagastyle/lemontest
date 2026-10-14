"""VK API интеграция для получения информации о постах."""
import aiohttp
import logging
from typing import Optional, Dict, Tuple
import config

logger = logging.getLogger(__name__)


class VKAPIClient:
    def __init__(self):
        self.base_url = "https://api.vk.com/method"
        self.token = config.VK_API_TOKEN
        self.version = config.VK_API_VERSION

    async def get_post_info(self, post_url: str) -> Optional[Dict]:
        """Получает информацию о посте по ссылке VK.

        Ожидает ссылку типа: https://vk.com/wall-123456_789 или https://vk.com/club123
        Возвращает: {owner_id, post_id, text, created_at} или None
        """
        owner_id, post_id = self._parse_post_url(post_url)
        if not owner_id or not post_id:
            logger.warning(f"Не удалось распарсить URL: {post_url}")
            return None

        if not self.token:
            logger.error("VK_API_TOKEN не установлен")
            return None

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    'owner_id': owner_id,
                    'posts': f"{owner_id}_{post_id}",
                    'access_token': self.token,
                    'v': self.version,
                }
                async with session.get(
                    f"{self.base_url}/wall.getById",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"VK API returned {resp.status}")
                        return None
                    data = await resp.json()

                    # Проверяем ошибку API
                    if 'error' in data:
                        logger.error(f"VK API error: {data['error']}")
                        return None

                    if 'response' in data and data['response']:
                        post = data['response'][0]
                        return {
                            'owner_id': post.get('owner_id'),
                            'post_id': post.get('id'),
                            'text': post.get('text', ''),
                            'created_at': post.get('date'),
                            'from_id': post.get('from_id')
                        }

                    logger.warning(f"VK API no posts found: {data}")
                    return None
        except Exception as e:
            logger.error(f"VK API error: {e}")
            return None

    async def validate_post_url(self, post_url: str) -> bool:
        """Проверяет, что ссылка валидна и пост существует."""
        if not self.token:
            logger.error("VK_API_TOKEN не установлен")
            return False
        info = await self.get_post_info(post_url)
        return info is not None

    @staticmethod
    def _parse_post_url(url: str) -> Tuple[Optional[int], Optional[int]]:
        """Парсит ссылку VK и возвращает (owner_id, post_id).

        Примеры:
        - https://vk.com/wall-123456_789 → (-123456, 789)
        - https://vk.com/club123/posts/789 → (-123, 789)
        - vk.com/wall-123456_789 → (-123456, 789)
        """
        url = url.strip()
        if not url.startswith('http'):
            url = f"https://{url}"

        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            path = parsed.path.strip('/')

            # Формат: wall-123456_789
            if 'wall-' in path:
                parts = path.split('wall-')[1].split('_')
                if len(parts) == 2:
                    try:
                        owner_id = -int(parts[0])  # owner_id обычно отрицательный
                        post_id = int(parts[1])
                        return owner_id, post_id
                    except ValueError:
                        pass

            # Формат: club123/posts/789 или club123/?w=wall-123_789
            if 'club' in path or 'public' in path:
                club_part = path.split('/')[0]
                club_id = int(''.join(filter(str.isdigit, club_part)))

                if 'w=' in parsed.query:
                    w_param = parse_qs(parsed.query)['w'][0]
                    if 'wall' in w_param:
                        parts = w_param.split('wall')[1].strip('-_').split('_')
                        if len(parts) == 2:
                            post_id = int(parts[1])
                            return -club_id, post_id

        except Exception as e:
            logger.error(f"URL parse error: {e}")

        return None, None


vk_client = VKAPIClient()
