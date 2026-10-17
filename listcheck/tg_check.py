import config


async def is_tg_subscribed(bot, user_id: int) -> bool:
    """Подписан ли пользователь на канал LEMON. Бот должен быть админом канала, иначе Telegram вернёт ошибку."""
    member = await bot.get_chat_member(chat_id=config.LEMON_TG_CHANNEL, user_id=user_id)
    if member.status in ("member", "administrator", "creator"):
        return True
    if member.status == "restricted":
        return bool(getattr(member, "is_member", False))
    return False
