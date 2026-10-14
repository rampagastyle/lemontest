"""Проверка списков через VK сторис."""
import logging
import html
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
from database import db
from keyboards import main_menu, admin_menu
from utils.image_hash import get_image_hash
from utils.gemini_vision import gemini_analyzer
from utils.vk_api import vk_client

logger = logging.getLogger(__name__)
router = Router()


class ListCheck(StatesGroup):
    waiting_for_event = State()
    waiting_for_vk_username = State()
    waiting_for_screenshot = State()


@router.message(F.text == "📋 Проверить список")
async def start_list_check(message: Message, state: FSMContext):
    """Начинает процесс проверки списка."""
    # Проверяем, привязан ли VK-аккаунт
    vk_username = await db.get_vk_username(message.from_user.id)

    if not vk_username:
        await state.set_state(ListCheck.waiting_for_vk_username)
        await message.answer(
            "📋 Проверка списков\n\n"
            "Сначала укажите ваше имя в VK (как оно отображается в профиле):\n"
            "Это нужно для проверки подлинности сторис."
        )
        return

    events = await db.get_active_events()
    if not events:
        await message.answer("❌ Нет доступных мероприятий")
        return

    await state.update_data(vk_username=vk_username)
    await state.set_state(ListCheck.waiting_for_event)

    text = "📋 Выберите мероприятие для проверки списка:\n\n"
    for event in events:
        vk_post = await db.get_event_vk_post(event['id'])
        if vk_post:  # Показываем только события с VK-постом
            text += f"ID: {event['id']} - {event['name']}\n"

    if "ID:" not in text:
        await message.answer("❌ Нет мероприятий с привязанным VK-постом")
        await state.clear()
        return

    text += "\nОтправьте ID мероприятия:"
    await message.answer(text)


@router.message(ListCheck.waiting_for_vk_username, F.text)
async def process_vk_username(message: Message, state: FSMContext):
    """Сохраняет VK-username и переходит к выбору события."""
    vk_username = message.text.strip()

    if not vk_username or len(vk_username) < 2:
        await message.answer("❌ Введите корректное имя")
        return

    await db.link_vk_account(message.from_user.id, vk_username)
    await state.update_data(vk_username=vk_username)
    await state.set_state(ListCheck.waiting_for_event)

    events = await db.get_active_events()
    if not events:
        await message.answer("❌ Нет доступных мероприятий")
        return

    text = "📋 Выберите мероприятие для проверки списка:\n\n"
    for event in events:
        vk_post = await db.get_event_vk_post(event['id'])
        if vk_post:
            text += f"ID: {event['id']} - {event['name']}\n"

    if "ID:" not in text:
        await message.answer("❌ Нет мероприятий с привязанным VK-постом")
        await state.clear()
        return

    text += "\nОтправьте ID мероприятия:"
    await message.answer(text)


@router.message(ListCheck.waiting_for_event, F.text)
async def process_event_selection(message: Message, state: FSMContext):
    """Выбирает событие и просит скриншот сторис."""
    try:
        event_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите число")
        return

    event = await db.get_event(event_id)
    vk_post = await db.get_event_vk_post(event_id)

    if not event or not vk_post:
        await message.answer("❌ Мероприятие не найдено или без VK-поста")
        return

    await state.update_data(event_id=event_id)
    await state.set_state(ListCheck.waiting_for_screenshot)
    await message.answer(
        f"📋 Мероприятие: {html.escape(event['name'])}\n\n"
        f"📸 Отправьте скриншот сторис VK где:\n"
        f"1. Отмечено ваше имя (@username)\n"
        f"2. Видна отметка сообщества (стикер тусовки)\n"
        f"3. Виден постер или название события\n\n"
        f"Отправьте фотографию или отмените (/cancel)"
    )


@router.message(ListCheck.waiting_for_screenshot)
async def process_screenshot(message: Message, state: FSMContext):
    """Обрабатывает скриншот сторис через Gemini."""
    if not message.photo:
        await message.answer("❌ Отправьте изображение")
        return

    try:
        # Скачиваем изображение
        file_info = await message.bot.get_file(message.photo[-1].file_id)
        image_bytes = await message.bot.download_file(file_info.file_path)

        # Считаем хеш для дедупликации
        screenshot_hash = get_image_hash(image_bytes)

        data = await state.get_data()
        event_id = data['event_id']
        user_id = message.from_user.id
        vk_username = data['vk_username']

        # Проверяем дедупликацию
        is_duplicate = await db.check_screenshot_duplicate(event_id, user_id, screenshot_hash)
        if is_duplicate:
            await message.answer(
                "⚠️ Вы уже отправляли этот скриншот для этого события.\n"
                "Отправьте новый скриншот или /cancel"
            )
            return

        await message.answer("🔍 Анализирую скриншот... Подождите...")

        # Анализируем через Gemini
        analysis = await gemini_analyzer.analyze_screenshot(image_bytes)

        if not analysis:
            await message.answer(
                "❌ Не удалось проанализировать скриншот. Попробуйте ещё раз."
            )
            return

        has_community_tag = analysis.get('has_community_tag', False)
        has_event_poster = analysis.get('has_event_poster', False)
        author_name = analysis.get('author_name')
        confidence = analysis.get('confidence', 0)

        # Сравниваем имя автора с VK-username
        author_match = gemini_analyzer.validate_author_match(author_name, vk_username)

        # Сохраняем проверку
        check_id = await db.create_list_check(
            event_id=event_id,
            user_id=user_id,
            vk_username=vk_username,
            screenshot_hash=screenshot_hash,
            gemini_analysis=analysis,
            author_match=author_match,
            has_community_tag=has_community_tag,
            has_event_poster=has_event_poster
        )

        # Добавляем хеш в дедупликацию
        await db.add_screenshot_hash(event_id, user_id, screenshot_hash)

        # Формируем результат
        result_text = f"📊 Результаты анализа (ID проверки: {check_id})\n\n"
        result_text += f"🎯 Отметка сообщества: {'✅ Да' if has_community_tag else '❌ Нет'}\n"
        result_text += f"📰 Постер события: {'✅ Да' if has_event_poster else '❌ Нет'}\n"
        result_text += f"👤 Имя автора: {author_name or '?'}\n"
        result_text += f"✓ Ваше имя совпадает: {'✅ Да' if author_match else '❌ Нет'}\n"
        result_text += f"🔍 Уверенность анализа: {int(confidence * 100)}%\n\n"

        if has_community_tag and has_event_poster and author_match:
            result_text += "✅ Проверка успешна! Информация отправлена администраторам на подтверждение."
        else:
            issues = []
            if not has_community_tag:
                issues.append("отсутствует отметка сообщества")
            if not has_event_poster:
                issues.append("не виден постер события")
            if not author_match:
                issues.append("имя не совпадает")
            result_text += f"⚠️ Проблемы: {', '.join(issues)}\n"
            result_text += "Попробуйте отправить другой скриншот."

        result_text += "\n\nОтправить ещё один скриншот или /cancel"

        await message.answer(result_text)
        await state.set_state(ListCheck.waiting_for_screenshot)

        # Уведомляем админов
        admin_text = (
            f"📋 Новая проверка списка (ID: {check_id})\n\n"
            f"Пользователь: {message.from_user.full_name} (@{message.from_user.username or 'unknown'})\n"
            f"VK-имя: {vk_username}\n"
            f"Статус: {'✅ ОК' if (has_community_tag and has_event_poster and author_match) else '⚠️ Требует внимания'}\n"
            f"Отметка: {'✅' if has_community_tag else '❌'} "
            f"Постер: {'✅' if has_event_poster else '❌'} "
            f"Имя: {'✅' if author_match else '❌'}"
        )

        admin_ids = set(config.ADMIN_IDS) | set(await db.get_admin_ids())
        for admin_id in admin_ids:
            try:
                await message.bot.send_message(admin_id, admin_text)
            except Exception as e:
                logger.warning(f"Не удалось отправить админу {admin_id}: {e}")

    except Exception as e:
        logger.exception(f"Screenshot processing error: {e}")
        await message.answer(f"❌ Ошибка при обработке: {e}")
        await state.clear()


@router.message(F.state.in_([ListCheck.waiting_for_screenshot]))
async def screenshot_non_photo(message: Message):
    """Обработка не-фотографий при ожидании скриншота."""
    if message.text == "/cancel":
        await message.reply("❌ Проверка отменена")
    else:
        await message.answer("❌ Отправьте изображение или /cancel")
