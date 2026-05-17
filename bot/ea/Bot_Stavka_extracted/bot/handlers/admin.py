"""
Команды администратора.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import config
from db.models import Match, Subscription, Team, TelegramChannel, TelegramMessage, User

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


@router.message(Command("admin"))
async def cmd_admin(message: Message, db: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа\\.")
        return

    args = (message.text or "").split(maxsplit=2)
    if len(args) < 2:
        await _send_admin_help(message)
        return

    subcommand = args[1].lower()

    if subcommand == "add_channel":
        if len(args) < 3:
            await message.answer("Использование: `/admin add_channel @channel`")
            return
        await _add_channel(message, db, args[2].strip())

    elif subcommand == "remove_channel":
        if len(args) < 3:
            await message.answer("Использование: `/admin remove_channel @channel`")
            return
        await _remove_channel(message, db, args[2].strip())

    elif subcommand == "list_channels":
        await _list_channels(message, db)

    elif subcommand == "status":
        await _status(message, db)

    elif subcommand == "sync":
        target = args[2].strip().lower() if len(args) > 2 else "all"
        await _sync(message, db, target)

    else:
        await _send_admin_help(message)


async def _send_admin_help(message: Message) -> None:
    text = (
        "*Команды администратора:*\n\n"
        "`/admin add_channel @channel` — добавить канал\n"
        "`/admin remove_channel @channel` — убрать канал\n"
        "`/admin list_channels` — список каналов\n"
        "`/admin status` — состояние системы\n"
        "`/admin sync` — запустить все коллекторы сейчас\n"
        "`/admin sync opendota` — только OpenDota\n"
        "`/admin sync hltv` — только HLTV\n"
        "`/admin sync patches` — только патчи\n"
    )
    await message.answer(text)


async def _add_channel(message: Message, db: AsyncSession, username: str) -> None:
    username = username.lstrip("@")
    result = await db.execute(
        select(TelegramChannel).where(TelegramChannel.username == username)
    )
    if result.scalar_one_or_none():
        await message.answer(f"Канал @{username} уже добавлен\\.")
        return

    channel = TelegramChannel(username=username, is_active=True)
    db.add(channel)
    await db.commit()
    await message.answer(f"✅ Канал @{username} добавлен\\.")


async def _remove_channel(message: Message, db: AsyncSession, username: str) -> None:
    username = username.lstrip("@")
    result = await db.execute(
        select(TelegramChannel).where(TelegramChannel.username == username)
    )
    channel = result.scalar_one_or_none()
    if not channel:
        await message.answer(f"Канал @{username} не найден\\.")
        return

    channel.is_active = False
    await db.commit()
    await message.answer(f"✅ Канал @{username} деактивирован\\.")


async def _list_channels(message: Message, db: AsyncSession) -> None:
    result = await db.execute(select(TelegramChannel).order_by(TelegramChannel.added_at))
    channels = result.scalars().all()

    if not channels:
        await message.answer("Каналов нет\\. Добавь через `/admin add_channel @channel`")
        return

    lines = ["*Telegram-каналы:*\n"]
    for ch in channels:
        status = "✅" if ch.is_active else "❌"
        game = f" \\[{ch.game}\\]" if ch.game else ""
        lines.append(f"{status} @{ch.username}{game}")

    await message.answer("\n".join(lines))


async def _status(message: Message, db: AsyncSession) -> None:
    teams_count = (await db.execute(select(func.count(Team.id)))).scalar()
    matches_count = (await db.execute(select(func.count(Match.id)))).scalar()
    upcoming_count = (await db.execute(
        select(func.count(Match.id)).where(Match.status == "upcoming")
    )).scalar()
    users_count = (await db.execute(select(func.count(User.id)))).scalar()
    messages_count = (await db.execute(select(func.count(TelegramMessage.id)))).scalar()
    channels_count = (await db.execute(
        select(func.count(TelegramChannel.id)).where(TelegramChannel.is_active == True)
    )).scalar()
    subs_count = (await db.execute(select(func.count(Subscription.id)))).scalar()

    text = (
        "*Состояние системы:*\n\n"
        f"👥 Пользователей: {users_count}\n"
        f"🔔 Подписок: {subs_count}\n"
        f"🏆 Команд в БД: {teams_count}\n"
        f"📊 Матчей в БД: {matches_count} \\(предстоящих: {upcoming_count}\\)\n"
        f"📢 Telegram\\-каналов: {channels_count}\n"
        f"💬 Сообщений в БД: {messages_count}\n"
    )
    await message.answer(text)


async def _sync(message: Message, db: AsyncSession, target: str) -> None:
    """Ручной запуск коллекторов."""
    await message.answer(f"⏳ Запускаю синхронизацию: *{target}*\\.\\.\\.")

    results = []

    try:
        if target in ("all", "opendota"):
            from collectors.opendota import run_opendota_sync
            await run_opendota_sync(db)
            results.append("✅ OpenDota")
    except Exception as ex:
        results.append(f"❌ OpenDota: {str(ex)[:60]}")

    try:
        if target in ("all", "patches"):
            from collectors.patches import run_patches_sync
            await run_patches_sync(db)
            results.append("✅ Patches")
    except Exception as ex:
        results.append(f"❌ Patches: {str(ex)[:60]}")

    try:
        if target in ("all", "hltv"):
            await message.answer("⏳ HLTV \\(может занять 1\\-2 минуты\\)\\.\\.\\.")
            from collectors.hltv import run_hltv_sync
            await run_hltv_sync(db)
            results.append("✅ HLTV")
    except Exception as ex:
        results.append(f"❌ HLTV: {str(ex)[:60]}")

    try:
        if target in ("all", "liquipedia"):
            from collectors.liquipedia import run_liquipedia_sync
            await run_liquipedia_sync(db)
            results.append("✅ Liquipedia")
    except Exception as ex:
        results.append(f"❌ Liquipedia: {str(ex)[:60]}")

    # Пересчёт рейтингов после синхронизации
    if target == "all":
        try:
            from collectors.rating import recalculate_ratings
            await recalculate_ratings(db, "cs2")
            await recalculate_ratings(db, "dota2")
            results.append("✅ Ratings recalculated")
        except Exception as ex:
            results.append(f"❌ Ratings: {str(ex)[:60]}")

    from bot.formatters.telegram_format import escape_md as e
    lines = ["*Результат синхронизации:*\n"]
    for r in results:
        lines.append(e(r))

    await message.answer("\n".join(lines))
