"""Проверка списков: привязка ВК, скриншот сторис, разбор админом, настройки события, диагностика."""
import html
import json
import logging
import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import config
from database import db
from handlers.user_handlers import MENU_TEXTS
from listcheck import flow, service
from listcheck.ai_story import analyze_story
from listcheck.rules import average_hash, hamming, names_match, decide_story, parse_vk_post_url
from listcheck.vk_api import get_vk_client
from listcheck.vk_listener import listener_state

logger = logging.getLogger(__name__)
router = Router()

DUP_DISTANCE = 4        # максимум различающихся бит хеша, при котором скриншоты считаются одинаковыми


class ListStory(StatesGroup):
    waiting_photo = State()


class ListEventEdit(StatesGroup):
    vk_post = State()
    quota = State()


def _check_button(event_id: int, text: str = "🔄 К условиям списка") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=f"lst_{event_id}_check")]])


async def _admin_ids():
    return set(config.ADMIN_IDS) | set(await db.get_admin_ids())


async def _safe_send(bot, chat_id: int, text: str, **kwargs):
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.warning("Не удалось написать %s: %s", chat_id, e)


# ---------- Вход из меню ----------

@router.message(F.text == "📋 Проверить список")
async def list_menu_entry(message: Message, state: FSMContext):
    await state.clear()
    if not config.LIST_VERIFICATION:
        await message.answer("📋 Проверка списков пока не включена. "
                             "Билет «По списку» можно выбрать в карточке мероприятия.")
        return
    events = await db.get_active_events()
    if not events:
        await message.answer("😔 Пока нет доступных мероприятий.")
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=event["name"], callback_data=f"lst_{event['id']}_check")]
        for event in events
    ])
    await message.answer("📋 Проверка списка\n\nВыберите мероприятие:", reply_markup=markup)


# ---------- Действия пользователя на экране условий ----------

@router.callback_query(F.data.regexp(r"^lst_\d+_(check|link|story)$"))
async def list_action(callback: CallbackQuery, state: FSMContext):
    _, event_id, action = callback.data.split("_")
    event = await db.get_event(int(event_id))
    if not event:
        await callback.answer("❌ Мероприятие не найдено", show_alert=True)
        return
    if not config.LIST_VERIFICATION:
        await callback.answer("Проверка списков отключена", show_alert=True)
        return

    if action == "check":
        await flow.show_conditions(callback, event)
    elif action == "link":
        await _start_link(callback, event)
    else:
        await _start_story(callback, event, state)


async def _start_link(callback: CallbackQuery, event: dict):
    if config.list_config_problems():
        await callback.answer("Проверка списков пока не настроена", show_alert=True)
        return
    link = await db.get_vk_link(callback.from_user.id)
    if link:
        await callback.answer(f"ВК уже привязан: {link.get('vk_name') or link['vk_id']}", show_alert=True)
        return

    code = await db.create_link_code(callback.from_user.id)
    text = (
        "🔗 Привязка ВКонтакте\n\n"
        "1. Откройте личные сообщения сообщества LEMON (кнопка ниже)\n"
        f"2. Отправьте туда этот код: <code>{code}</code>\n"
        "3. Вернитесь сюда и нажмите «Проверить»\n\n"
        f"Код действует {config.LINK_CODE_TTL_MIN} минут. Писать нужно с того профиля ВК, "
        "на который вы подписаны (с него же вы будете отмечать друзей)."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать сообществу ВК", url=flow.vk_write_url())],
        [InlineKeyboardButton(text="🔄 Проверить", callback_data=f"lst_{event['id']}_check")],
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)
    await callback.answer()


async def _start_story(callback: CallbackQuery, event: dict, state: FSMContext):
    st = await service.evaluate(callback.bot, callback.from_user.id, event)
    if st.config_problems:
        await callback.answer("Проверка списков пока не настроена", show_alert=True)
        return
    if st.banned:
        await callback.answer("Список для вас недоступен", show_alert=True)
        return
    if not st.vk_linked:
        await callback.answer("Сначала привяжите ВК", show_alert=True)
        await flow.show_conditions(callback, event, st)
        return
    if st.story_status == "approved":
        await callback.answer("Сторис уже подтверждена", show_alert=True)
        return
    if st.story_status == "pending":
        await callback.answer("Сторис уже на проверке у администратора", show_alert=True)
        return
    if st.story_attempts >= config.STORY_MAX_ATTEMPTS:
        await callback.answer("Лимит попыток исчерпан. Напишите в поддержку или возьмите билет «Без списка».",
                              show_alert=True)
        return

    await state.set_state(ListStory.waiting_photo)
    await state.update_data(event_id=event["id"])
    await callback.message.answer(
        "📸 Пришлите скриншот сторис\n\n"
        "На нём должны быть видны:\n"
        "• отметка LEMON\n"
        f"• публикация о «{event['name']}»\n"
        f"• ваше имя вверху сторис ({st.vk_name or 'как в профиле ВК'})\n\n"
        "Отправьте именно фото (не файлом). Отмена: /cancel"
    )
    await callback.answer()


# ---------- Скриншот сторис ----------

@router.message(ListStory.waiting_photo, F.photo)
async def story_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    event_id = data.get("event_id")
    uid = message.from_user.id

    event = await db.get_event(event_id) if event_id else None
    link = await db.get_vk_link(uid)
    if not event or not link:
        await message.answer("Что-то пошло не так. Откройте условия списка заново.")
        return
    if await db.is_list_banned(uid):
        await message.answer("🚫 Список для вас недоступен.")
        return
    attempts = await db.count_story_attempts(event_id, uid)
    if attempts >= config.STORY_MAX_ATTEMPTS:
        await message.answer("Лимит попыток исчерпан.", reply_markup=_check_button(event_id))
        return
    access = await db.get_list_access(event_id, uid)
    if access and access["status"] in ("approved", "pending"):
        await message.answer("Ваша сторис уже принята или на проверке.", reply_markup=_check_button(event_id))
        return

    photo = message.photo[-1]
    wait = await message.answer("🔎 Проверяю скриншот…")

    try:
        buffer = await message.bot.download(photo)
        buffer.seek(0)
        image = buffer.read()
    except Exception:
        logger.exception("Не удалось скачать скриншот")
        await wait.edit_text("Не удалось скачать файл. Попробуйте отправить скриншот ещё раз.")
        return

    img_hash = None
    try:
        img_hash = average_hash(image)
    except Exception:
        logger.warning("Не удалось посчитать хеш скриншота", exc_info=True)

    # дубли: тот же файл или почти та же картинка от другого человека
    for row in await db.get_event_image_hashes(event_id):
        if row["user_id"] == uid:
            continue
        same_file = row["file_unique_id"] and row["file_unique_id"] == photo.file_unique_id
        same_image = img_hash and row["img_hash"] and hamming(img_hash, row["img_hash"]) <= DUP_DISTANCE
        if same_file or same_image:
            await db.add_story_submission(event_id, uid, photo.file_id, photo.file_unique_id, img_hash,
                                          None, "dup", "дубль скриншота")
            left = max(0, config.STORY_MAX_ATTEMPTS - attempts - 1)
            await wait.edit_text(
                f"❌ Этот скриншот уже использовал другой участник. Нужна ваша собственная сторис.\n"
                f"Осталось попыток: {left}", reply_markup=_check_button(event_id))
            return

    ai, ai_error = None, None
    try:
        ai = await analyze_story(image, event["name"])
    except Exception as e:
        ai_error = str(e)[:200]
        logger.warning("ИИ не смог разобрать скриншот: %s", ai_error)

    if ai is None:
        verdict, reason = "review", f"ИИ недоступен: {ai_error}"
    else:
        shown = ai.get("author_name") or ""
        name_ok = names_match(link.get("vk_name") or "", shown) if shown else False
        verdict, reason = decide_story(ai, name_ok)
    ai_json = json.dumps(ai, ensure_ascii=False) if ai else None

    if verdict == "approve":
        sub_id = await db.add_story_submission(event_id, uid, photo.file_id, photo.file_unique_id,
                                               img_hash, ai_json, "approved_ai", reason)
        await db.set_list_access(event_id, uid, "approved", "ai", reason)
        await wait.edit_text("✅ Сторис принята!", reply_markup=_check_button(event_id))
        if random.random() < config.STORY_AUDIT_PERCENT / 100:
            await _notify_admins(message.bot, sub_id, event, message.from_user, link, photo.file_id, ai, reason, audit=True)

    elif verdict == "reject":
        await db.add_story_submission(event_id, uid, photo.file_id, photo.file_unique_id,
                                      img_hash, ai_json, "rejected_ai", reason)
        await db.set_list_access(event_id, uid, "rejected", "ai", reason)
        left = max(0, config.STORY_MAX_ATTEMPTS - attempts - 1)
        await wait.edit_text(f"❌ {reason}\n\nОсталось попыток: {left}", reply_markup=_check_button(event_id))

    else:
        sub_id = await db.add_story_submission(event_id, uid, photo.file_id, photo.file_unique_id,
                                               img_hash, ai_json, "pending", reason)
        await db.set_list_access(event_id, uid, "pending", "ai", reason)
        await wait.edit_text("⏳ Скриншот отправлен администратору на проверку. Напишем, как только он ответит.",
                             reply_markup=_check_button(event_id))
        await _notify_admins(message.bot, sub_id, event, message.from_user, link, photo.file_id, ai, reason, audit=False)


@router.message(ListStory.waiting_photo, F.document)
async def story_document(message: Message):
    await message.answer("Пришлите скриншот именно как фото (не файлом). Отмена: /cancel")


@router.message(ListStory.waiting_photo, F.text, ~F.text.startswith("/"))
async def story_wrong_input(message: Message, state: FSMContext):
    if message.text in MENU_TEXTS:
        await state.clear()
        await message.answer("Отправка скриншота отменена. Нажмите нужную кнопку ещё раз.")
        return
    await message.answer("Жду скриншот сторис фотографией. Отмена: /cancel")


async def _notify_admins(bot, sub_id, event, tg_user, link, file_id, ai, reason, audit: bool):
    username = f"@{tg_user.username}" if tg_user.username else "без username"
    lines = [
        "🔍 АУДИТ (одобрено автоматически)" if audit else "📸 Сторис на проверку",
        "",
        f"🎉 {event['name']}",
        f"👤 {tg_user.full_name} ({username}), ID {tg_user.id}",
        f"🔗 ВК: {link.get('vk_name') or '—'} (vk.com/id{link['vk_id']})",
        f"🤖 {reason}",
    ]
    if ai:
        lines.append(f"Имя на скриншоте: {ai.get('author_name') or '—'} · уверенность {ai.get('confidence'):.2f}")
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"lsr_{sub_id}_ok"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"lsr_{sub_id}_no")],
        [InlineKeyboardButton(text="🚫 Отклонить и снять со списков", callback_data=f"lsr_{sub_id}_ban")],
    ])
    caption = "\n".join(lines)

    # Если задан отдельный чат/форум — отправляем туда, чтобы не засорять личные чаты админов.
    review_chat = getattr(config, "ADMIN_REVIEW_CHAT_ID", None)
    if review_chat:
        try:
            await bot.send_photo(review_chat, photo=file_id, caption=caption, reply_markup=markup)
            return
        except Exception as e:
            logger.warning("Не удалось отправить заявку в чат проверки %s: %s — fallback в лички", review_chat, e)

    delivered = 0
    for admin_id in await _admin_ids():
        try:
            await bot.send_photo(admin_id, photo=file_id, caption=caption, reply_markup=markup)
            delivered += 1
        except Exception as e:
            logger.warning("Не удалось отправить заявку админу %s: %s", admin_id, e)
    if not delivered:
        logger.error("Заявка на проверку сторис %s не дошла ни до одного админа", sub_id)


# ---------- Решение админа ----------

@router.callback_query(F.data.regexp(r"^lsr_\d+_(ok|no|ban)$"))
async def review_story(callback: CallbackQuery):
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    _, sub_id, action = callback.data.split("_")
    sub = await db.get_story_submission(int(sub_id))
    if not sub:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    was_audit = sub["decision"] == "approved_ai"      # аудит: пользователю уже сказали «принято»
    new_decision = "approved_admin" if action == "ok" else "rejected_admin"
    if not await db.mark_submission_reviewed(sub["id"], callback.from_user.id, new_decision):
        await callback.answer("Уже обработано другим админом", show_alert=True)
        return

    event_id, uid = sub["event_id"], sub["user_id"]
    left = max(0, config.STORY_MAX_ATTEMPTS - await db.count_story_attempts(event_id, uid))

    if action == "ok":
        await db.set_list_access(event_id, uid, "approved", "admin")
        if not was_audit:
            await _safe_send(callback.bot, uid, "✅ Администратор подтвердил вашу сторис!",
                             reply_markup=_check_button(event_id))
        verdict = "✅ Подтверждено"
    elif action == "no":
        await db.set_list_access(event_id, uid, "rejected", "admin")
        text = ("❌ Сторис не подтверждена, условие снято." if was_audit else "❌ Администратор не подтвердил сторис.")
        await _safe_send(callback.bot, uid, f"{text}\nОсталось попыток: {left}. "
                                            "Можно отправить другой скриншот или взять билет «Без списка».",
                         reply_markup=_check_button(event_id))
        verdict = "❌ Отклонено"
    else:
        await db.ban_list(uid, callback.from_user.id, "обман при проверке списка")
        await db.set_list_access(event_id, uid, "revoked", "admin")
        await _safe_send(callback.bot, uid, "🚫 К сожалению, список для вас недоступен. "
                                            "Билет «Без списка» купить можно.")
        verdict = "🚫 Отклонено, снят со списков"

    try:
        await callback.message.edit_caption(
            caption=f"{callback.message.caption or ''}\n\n{verdict} — {callback.from_user.full_name}")
    except Exception:
        pass
    await callback.answer("Готово")


# ---------- Настройки события: пост ВК и квота (из карточки «Управление») ----------

async def _require_admin(callback: CallbackQuery) -> bool:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return False
    return True


@router.callback_query(F.data.regexp(r"^edit_vkpost_\d+$"))
async def edit_vkpost_start(callback: CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    event_id = int(callback.data.rsplit("_", 1)[1])
    await state.update_data(list_event_id=event_id)
    await state.set_state(ListEventEdit.vk_post)
    await callback.message.answer("🔗 Ссылка на пост мероприятия в сообществе LEMON ВК "
                                  "(например, https://vk.com/wall-123_456) или «-», чтобы убрать:")
    await callback.answer()


@router.message(ListEventEdit.vk_post, F.text, ~F.text.startswith("/"))
async def edit_vkpost_save(message: Message, state: FSMContext):
    if message.text in MENU_TEXTS:
        await state.clear()
        await message.answer("Изменение отменено. Нажмите нужную кнопку ещё раз.")
        return
    if not await db.is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    event_id = data["list_event_id"]
    text = message.text.strip()
    if text in ("-", "—", "нет"):
        await db.set_event_vk_post(event_id, None, None, None)
    else:
        parsed = parse_vk_post_url(text)
        if not parsed:
            await message.answer("❌ Нужна ссылка вида https://vk.com/wall-123_456 или «-»")
            return
        owner, post_id, url = parsed
        if config.VK_GROUP_ID and owner != -config.VK_GROUP_ID:
            await message.answer(f"❌ Пост должен быть на стене сообщества LEMON (id -{config.VK_GROUP_ID}), "
                                 "иначе бот не увидит комментарии.")
            return
        await db.set_event_vk_post(event_id, url, owner, post_id)

    await state.clear()
    await message.answer("✅ Сохранено", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ К карточке", callback_data=f"manage_event_{event_id}")]]))


@router.callback_query(F.data.regexp(r"^edit_quota_\d+$"))
async def edit_quota_start(callback: CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    event_id = int(callback.data.rsplit("_", 1)[1])
    await state.update_data(list_event_id=event_id)
    await state.set_state(ListEventEdit.quota)
    await callback.message.answer("📋 Сколько всего билетов можно продать «По списку»? (0 — без лимита)")
    await callback.answer()


@router.message(ListEventEdit.quota, F.text, ~F.text.startswith("/"))
async def edit_quota_save(message: Message, state: FSMContext):
    if message.text in MENU_TEXTS:
        await state.clear()
        await message.answer("Изменение отменено. Нажмите нужную кнопку ещё раз.")
        return
    if not await db.is_admin(message.from_user.id):
        await state.clear()
        return

    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Введите целое число (0 — без лимита)")
        return
    quota = int(text)
    data = await state.get_data()
    event_id = data["list_event_id"]
    event = await db.get_event(event_id)
    if event and quota > event["total_tickets"]:
        await message.answer(f"❌ Квота не может быть больше общего числа билетов ({event['total_tickets']})")
        return

    await db.set_event_list_quota(event_id, quota or None)
    await state.clear()
    await message.answer("✅ Сохранено", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ К карточке", callback_data=f"manage_event_{event_id}")]]))


# ---------- Диагностика ----------

@router.message(Command("listcheck"))
async def list_diagnostics(message: Message):
    if not await db.is_admin(message.from_user.id):
        return

    lines = [f"LIST_VERIFICATION: {'включена ✅' if config.LIST_VERIFICATION else 'выключена'}"]
    problems = config.list_config_problems()
    lines.append("❌ Не заданы: " + ", ".join(problems) if problems else "✅ Все переменные заданы")

    if config.LEMON_TG_CHANNEL:
        try:
            chat = await message.bot.get_chat(config.LEMON_TG_CHANNEL)
            me = await message.bot.me()
            member = await message.bot.get_chat_member(chat.id, me.id)
            if member.status in ("administrator", "creator"):
                lines.append(f"✅ Telegram: канал «{chat.title}», бот — админ")
            else:
                lines.append(f"❌ Telegram: бот в канале «{chat.title}» не админ (статус {member.status}) — "
                             "проверка подписок работать не будет")
        except Exception as e:
            lines.append(f"❌ Telegram: {str(e)[:150]}")

    vk = get_vk_client()
    if vk:
        try:
            info = await vk.call("groups.getById", group_ids=config.VK_GROUP_ID)
            group = info["groups"][0] if isinstance(info, dict) else info[0]
            lines.append(f"✅ ВК: сообщество «{group.get('name')}», токен работает")
        except Exception as e:
            lines.append(f"❌ ВК (groups.getById): {str(e)[:150]}")
        try:
            await vk.is_member(1)
            lines.append("✅ ВК: проверка подписки (groups.isMember) работает")
        except Exception as e:
            lines.append(f"❌ ВК (groups.isMember): {str(e)[:150]}")
        try:
            await vk.get_long_poll_server()
            lines.append("✅ ВК: Long Poll включён")
        except Exception as e:
            lines.append(f"❌ ВК Long Poll: {str(e)[:150]} — включите в настройках сообщества")

    lines.append("✅ Слушатель ВК запущен" if listener_state["running"] else "❌ Слушатель ВК не запущен")
    lines.append(f"   событий получено: {listener_state['events_total']}")
    if listener_state["last_error"]:
        lines.append(f"   последняя ошибка: {listener_state['last_error']}")

    model = config.GEMINI_MODEL if config.AI_PROVIDER == "gemini" else config.ANTHROPIC_MODEL
    lines.append(f"🤖 ИИ: {config.AI_PROVIDER} / {model}")
    await message.answer("\n".join(lines))
