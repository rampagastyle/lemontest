"""Минимальный клиент API ВКонтакте на aiohttp (токен сообщества)."""
import logging
import random
from typing import List, Optional

import aiohttp

import config

logger = logging.getLogger(__name__)


class VkError(Exception):
    def __init__(self, code, message):
        super().__init__(f"VK error {code}: {message}")
        self.code = code
        self.message = message


class VkClient:
    def __init__(self, token: str, group_id: int, version: str):
        self.token = token
        self.group_id = group_id
        self.version = version
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40))
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def call(self, method: str, **params):
        params["access_token"] = self.token
        params["v"] = self.version
        async with self._get_session().post(f"https://api.vk.com/method/{method}", data=params) as response:
            data = await response.json(content_type=None)
        if "error" in data:
            error = data["error"]
            raise VkError(error.get("error_code"), error.get("error_msg"))
        return data["response"]

    async def is_member(self, user_id: int) -> bool:
        result = await self.call("groups.isMember", group_id=self.group_id, user_id=user_id)
        if isinstance(result, dict):          # на случай extended-ответа
            return bool(result.get("member"))
        return bool(int(result))

    async def get_users(self, ids: List[int]) -> List[dict]:
        if not ids:
            return []
        return await self.call("users.get", user_ids=",".join(str(i) for i in ids))

    async def resolve_screen_name(self, name: str) -> Optional[dict]:
        """Короткое имя ([durov|..]) -> пользователь; None, если это не пользователь."""
        try:
            users = await self.call("users.get", user_ids=name)
        except VkError:
            return None
        return users[0] if users else None

    async def send_message(self, user_id: int, text: str):
        await self.call("messages.send", peer_id=user_id, random_id=random.randint(1, 2 ** 31 - 1), message=text)

    async def get_long_poll_server(self) -> dict:
        return await self.call("groups.getLongPollServer", group_id=self.group_id)

    async def poll(self, server: str, key: str, ts: str, wait: int = 25) -> dict:
        params = {"act": "a_check", "key": key, "ts": ts, "wait": wait}
        timeout = aiohttp.ClientTimeout(total=wait + 15)
        async with self._get_session().get(server, params=params, timeout=timeout) as response:
            return await response.json(content_type=None)


_client: Optional[VkClient] = None


def get_vk_client() -> Optional[VkClient]:
    global _client
    if _client is None and config.VK_TOKEN and config.VK_GROUP_ID:
        _client = VkClient(config.VK_TOKEN, config.VK_GROUP_ID, config.VK_API_VERSION)
    return _client
