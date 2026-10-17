"""Слушатель событий сообщества ВК (Bots Long Poll API): привязка аккаунта по коду и комментарии с отметками."""
import asyncio
import logging
from typing import Optional

from database import db
from listcheck.rules import extract_mentions, find_link_code
from listcheck.vk_api import VkClient, get_vk_client

logger = logging.getLogger(__name__)

# Для /listcheck: что сейчас делает слушатель
listener_state = {"running": False, "last_event_at": None, "last_error": None, "events_total": 0}


async def _notify_tg(bot, tg_user_id: Optional[int], text: str):
    if not tg_user_id:
        return
    try:
        await bot.send_message(tg_user_id, text)
    except Exception as e:
        logger.warning("Не удалось написать в Telegram %s: %s", tg_user_id, e)


async def _vk_reply(vk: VkClient, vk_id: int, text: str):
    try:
        await vk.send_message(vk_id, text)
    except Exception as e:
        logger.warning("Не удалось ответить во ВК %s: %s", vk_id, e)


async def handle_message_new(bot, vk: VkClient, obj: dict):
    message = obj.get("message", obj)
    from_id = message.get("from_id")
    code = find_link_code(message.get("text", ""))
    if not code or not from_id or from_id < 0:
        return          # обычные сообщения людей в сообщество не трогаем

    tg_user = await db.consume_link_code(code)
    if tg_user is None:
        await _vk_reply(vk, from_id, "Код не найден или устарел. Получите новый код в Telegram-боте и отправьте его снова.")
        return

    name = ""
    try:
        users = await vk.get_users([from_id])
        if users:
            name = f"{users[0].get('first_name', '')} {users[0].get('last_name', '')}".strip()
    except Exception as e:
        logger.warning("users.get для %s не удался: %s", from_id, e)

    result = await db.link_vk(tg_user, from_id, name)
    if result == "ok":
        await _vk_reply(vk, from_id, "✅ Готово! Аккаунт привязан. Возвращайтесь в Telegram-бот и нажмите «Проверить».")
        await _notify_tg(bot, tg_user, f"✅ ВК привязан: {name or from_id}. Нажмите «🔄 Проверить» в условиях списка.")
    elif result == "vk_taken":
        await _vk_reply(vk, from_id, "Этот профиль ВК уже привязан к другому аккаунту Telegram.")
        await _notify_tg(bot, tg_user, "❌ Этот профиль ВК уже привязан к другому аккаунту Telegram. "
                                       "Если это ошибка, напишите в поддержку.")
    else:
        await _vk_reply(vk, from_id, "К этому Telegram-аккаунту уже привязан другой профиль ВК.")
        await _notify_tg(bot, tg_user, "❌ К вашему Telegram уже привязан другой профиль ВК. "
                                       "Чтобы сменить его, напишите в поддержку.")


async def process_comment(bot, vk: VkClient, obj: dict, edited: bool = False):
    """Новый или отредактированный комментарий: считаем живые отметки и запоминаем, засчитан ли он."""
    author = obj.get("from_id")
    if not author or author < 0:
        return
    owner = obj.get("post_owner_id") or obj.get("owner_id")
    post_id = obj.get("post_id")
    comment_id = obj.get("id")
    if owner is None or post_id is None or comment_id is None:
        return

    event = await db.get_event_by_vk_post(owner, post_id)
    if not event:
        return          # комментарий не под постом мероприятия

    ids, names = extract_mentions(obj.get("text", ""))
    for name in list(names)[:6]:
        user = await vk.resolve_screen_name(name)
        if user:
            ids.add(user["id"])
    ids.discard(author)
    reply_to = obj.get("reply_to_user")      # при ответе ВК сам подставляет отметку адресата
    if reply_to:
        ids.discard(reply_to)

    valid_ids = set()
    if ids:
        for user in await vk.get_users(sorted(ids)):
            if not user.get("deactivated"):   # удалённые и заблокированные страницы не считаем
                valid_ids.add(user["id"])

    valid = len(valid_ids) >= 3
    await db.save_vk_comment(owner, comment_id, post_id, author, valid, len(valid_ids))

    tg_user = await db.get_user_by_vk(author)
    if valid:
        await _notify_tg(bot, tg_user, f"✅ Комментарий с 3 отметками засчитан («{event['name']}»). "
                                       "Нажмите «🔄 Проверить» в условиях списка.")
    elif edited:
        await _notify_tg(bot, tg_user, f"⚠️ После редактирования в комментарии меньше 3 отметок — "
                                       f"условие для «{event['name']}» не засчитано.")


async def handle_comment_deleted(bot, obj: dict):
    owner, comment_id = obj.get("owner_id"), obj.get("id")
    if owner is None or comment_id is None:
        return
    vk_id = await db.mark_vk_comment_deleted(owner, comment_id)
    if vk_id:
        tg_user = await db.get_user_by_vk(vk_id)
        await _notify_tg(bot, tg_user, "⚠️ Вы удалили комментарий с отметками друзей — условие списка больше не выполнено.")


async def handle_update(bot, vk: VkClient, update: dict):
    kind = update.get("type")
    obj = update.get("object", {})
    if kind == "message_new":
        await handle_message_new(bot, vk, obj)
    elif kind == "wall_reply_new":
        await process_comment(bot, vk, obj)
    elif kind == "wall_reply_edit":
        await process_comment(bot, vk, obj, edited=True)
    elif kind == "wall_reply_delete":
        await handle_comment_deleted(bot, obj)


async def run_vk_listener(bot):
    """Бесконечный цикл Long Poll. Запускается фоновой задачей рядом с Telegram-ботом."""
    vk = get_vk_client()
    delay = 1
    listener_state["running"] = True
    try:
        while True:
            try:
                server = await vk.get_long_poll_server()
                ts = server["ts"]
                logger.info("VK Long Poll подключён")
                listener_state["last_error"] = None
                while True:
                    data = await vk.poll(server["server"], server["key"], ts)
                    if "failed" in data:
                        if data["failed"] == 1:        # история событий устарела, берём новый ts
                            ts = data["ts"]
                            continue
                        break                           # ключ истёк или данные потеряны: заново получить сервер
                    ts = data["ts"]
                    delay = 1
                    for update in data.get("updates", []):
                        listener_state["events_total"] += 1
                        try:
                            await handle_update(bot, vk, update)
                        except Exception:
                            logger.exception("Ошибка обработки события ВК: %s", str(update)[:300])
            except asyncio.CancelledError:
                raise
            except Exception as e:
                listener_state["last_error"] = str(e)[:200]
                logger.exception("VK Long Poll: ошибка, переподключаюсь через %s с", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
    finally:
        listener_state["running"] = False
