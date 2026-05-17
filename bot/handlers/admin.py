"""
Команды администратора.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import config
from db.models import Match, Team, TelegramChannel, TelegramMessage, User, VirtualBet
from bot.formatters.telegram_format import escape_md as e

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


@router.message(Command("admin"))
async def cmd_admin(message: Message, db: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа\\.")
        return

    args = (message.text or "").split(maxsplit=3)
    if len(args) < 2:
        await _send_admin_help(message)
        return

    subcommand = args[1].lower()

    if subcommand == "add_channel":
        if len(args) < 3:
            await message.answer("Использование: `/admin add_channel @channel [cs2|dota2]`")
            return
        game = args[3].lower() if len(args) > 3 else None
        if game and game not in ("cs2", "dota2"):
            game = None
        await _add_channel(message, db, args[2].strip(), game)

    elif subcommand == "remove_channel":
        if len(args) < 3:
            await message.answer("Использование: `/admin remove_channel @channel`")
            return
        await _remove_channel(message, db, args[2].strip())

    elif subcommand == "list_channels":
        await _list_channels(message, db)

    elif subcommand == "seed_channels":
        await _seed_channels(message, db)

    elif subcommand == "sync":
        src = args[2].lower() if len(args) > 2 else ""
        await _trigger_sync(message, db, src)

    elif subcommand == "status":
        await _status(message, db)

    elif subcommand == "bets":
        await _bets_status(message, db)

    else:
        await _send_admin_help(message)


async def _send_admin_help(message: Message) -> None:
    text = (
        "*🔧 Команды администратора:*\n\n"
        "`/admin status` — состояние системы\n"
        "`/admin bets` — статистика виртуальных ставок\n\n"
        "*Каналы:*\n"
        "`/admin add_channel @ch [cs2|dota2]` — добавить канал\n"
        "`/admin remove_channel @ch` — убрать канал\n"
        "`/admin list_channels` — список каналов\n"
        "`/admin seed_channels` — загрузить стандартный набор каналов\n\n"
        "*Синхронизация:*\n"
        "`/admin sync opendota` — синхронизировать OpenDota прямо сейчас\n"
        "`/admin sync hltv` — синхронизировать HLTV прямо сейчас\n"
        "`/admin sync telegram` — синхронизировать Telegram-каналы\n"
        "`/admin sync history` — загрузить историю матчей \\(долго\\)\n"
    )
    await message.answer(text)


async def _add_channel(message: Message, db: AsyncSession, username: str, game: str | None = None) -> None:
    username = username.lstrip("@").lower()
    result = await db.execute(
        select(TelegramChannel).where(TelegramChannel.username == username)
    )
    existing = result.scalar_one_or_none()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            await db.commit()
            await message.answer(f"✅ Канал @{e(username)} реактивирован\\.")
        else:
            await message.answer(f"Канал @{e(username)} уже добавлен\\.")
        return

    channel = TelegramChannel(username=username, game=game, is_active=True)
    db.add(channel)
    await db.commit()
    game_label = f" \\[{e(game)}\\]" if game else ""
    await message.answer(f"✅ Канал @{e(username)}{game_label} добавлен\\.")


async def _remove_channel(message: Message, db: AsyncSession, username: str) -> None:
    username = username.lstrip("@").lower()
    result = await db.execute(
        select(TelegramChannel).where(TelegramChannel.username == username)
    )
    channel = result.scalar_one_or_none()
    if not channel:
        await message.answer(f"Канал @{e(username)} не найден\\.")
        return

    channel.is_active = False
    await db.commit()
    await message.answer(f"✅ Канал @{e(username)} деактивирован\\.")


async def _list_channels(message: Message, db: AsyncSession) -> None:
    result = await db.execute(select(TelegramChannel).order_by(TelegramChannel.is_active.desc(), TelegramChannel.added_at))
    channels = result.scalars().all()

    if not channels:
        await message.answer("Каналов нет\\. Используй `/admin seed_channels` для загрузки базового набора\\.")
        return

    active = [ch for ch in channels if ch.is_active]
    inactive = [ch for ch in channels if not ch.is_active]

    lines = [f"*📢 Каналы* \\(активных: {len(active)}, отключённых: {len(inactive)}\\)\n"]

    if active:
        lines.append("*Активные:*")
        for ch in active[:30]:
            game = f" \\[{e(ch.game)}\\]" if ch.game else ""
            lines.append(f"  ✅ @{e(ch.username)}{game}")

    if inactive:
        lines.append("\n*Отключённые:*")
        for ch in inactive[:10]:
            lines.append(f"  ❌ @{e(ch.username)}")

    await message.answer("\n".join(lines))


async def _seed_channels(message: Message, db: AsyncSession) -> None:
    """Загрузить стандартный набор каналов."""
    await message.answer("⏳ Загружаю стандартный набор каналов\\.\\.\\.")

    # Новостные медиа — проверенные каналы
    NEWS = [
        ("cybersport_ru",       None,     "Киберспорт.ру"),
        ("esforce",             None,     "ESforce media"),
        ("gg_esports",          None,     "GG.ru esports"),
        ("ruhub",               None,     "RuHub стримы"),
        ("dota2_ru",            "dota2",  "Dota2 RU"),
        ("cs2_ru",              "cs2",    "CS2 RU"),
        ("natusvincere",        None,     "NaVi official"),
        ("virtuspro",           None,     "Virtus.pro official"),
        ("teamspirit_gg",       None,     "Team Spirit"),
        ("navi_dota",           "dota2",  "NaVi Dota2"),
        ("pgl_esports",         None,     "PGL турниры"),
        ("wesg_esports",        None,     "WESG"),
    ]

    # Аналитика / разборы матчей
    ANALYTICS = [
        ("cs2_analytics",       "cs2",    "CS2 аналитика"),
        ("csgo_prognoz",        "cs2",    "CS2 прогнозы"),
        ("dota2_prognozy",      "dota2",  "Dota2 прогнозы"),
        ("dota2_analytics",     "dota2",  "Dota2 аналитика"),
        ("esports_analysis",    None,     "Esports аналитика"),
    ]

    all_ch = [(u, g, n) for u, g, n in NEWS + ANALYTICS]

    added = 0
    skipped = 0
    for username, game, note in all_ch:
        username = username.lower()
        existing = await db.execute(
            select(TelegramChannel).where(TelegramChannel.username == username)
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue
        db.add(TelegramChannel(username=username, game=game, is_active=True))
        added += 1

    await db.commit()
    await message.answer(
        f"✅ Каналы загружены\\: *{e(str(added))}* добавлено, *{e(str(skipped))}* уже были\\.\n\n"
        f"_Проверь список через_ `/admin list_channels`"
    )


async def _trigger_sync(message: Message, db: AsyncSession, source: str) -> None:
    """Запустить синхронизацию вручную в фоне."""
    import asyncio

    if source == "opendota":
        await message.answer("⏳ Запускаю OpenDota sync в фоне\\.\\.\\.")
        async def _run():
            from collectors.opendota import run_opendota_sync
            from db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as s:
                await run_opendota_sync(s)
        asyncio.create_task(_run())
        await message.answer("✅ OpenDota sync запущен\\.")

    elif source == "hltv":
        await message.answer("⏳ Запускаю HLTV sync в фоне \\(может занять 2\\-3 мин\\)\\.\\.\\.")
        async def _run():
            from collectors.hltv import run_hltv_sync
            from db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as s:
                await run_hltv_sync(s)
        asyncio.create_task(_run())
        await message.answer("✅ HLTV sync запущен\\.")

    elif source == "telegram":
        await message.answer("⏳ Запускаю Telegram sync\\.\\.\\.")
        async def _run():
            from collectors.telegram_collector import run_telegram_sync
            from db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as s:
                await run_telegram_sync(s)
        asyncio.create_task(_run())
        await message.answer("✅ Telegram sync запущен\\.")

    elif source == "history":
        await message.answer(
            "⏳ Запускаю загрузку истории матчей в фоне\\.\n"
            "_Это займёт 5\\-15 минут \\(OpenDota 60 команд \\+ HLTV 10 страниц\\)_"
        )
        async def _run():
            from collectors.opendota import run_opendota_history_sync
            from collectors.hltv import run_hltv_history_sync
            from db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as s:
                await run_opendota_history_sync(s)
            async with AsyncSessionLocal() as s:
                await run_hltv_history_sync(s, pages=10)
        asyncio.create_task(_run())
        await message.answer("✅ History sync запущен\\.")

    else:
        await message.answer(
            "Источники: `opendota`, `hltv`, `telegram`, `history`\n"
            "Пример: `/admin sync opendota`"
        )


async def _status(message: Message, db: AsyncSession) -> None:
    teams_count = (await db.execute(select(func.count(Team.id)))).scalar()
    matches_total = (await db.execute(select(func.count(Match.id)))).scalar()
    matches_finished = (await db.execute(
        select(func.count(Match.id)).where(Match.status == "finished")
    )).scalar()
    matches_upcoming = (await db.execute(
        select(func.count(Match.id)).where(Match.status.in_(["upcoming", "live"]))
    )).scalar()
    users_count = (await db.execute(select(func.count(User.id)))).scalar()
    messages_count = (await db.execute(select(func.count(TelegramMessage.id)))).scalar()
    channels_count = (await db.execute(
        select(func.count(TelegramChannel.id)).where(TelegramChannel.is_active == True)
    )).scalar()
    bets_count = (await db.execute(select(func.count(VirtualBet.id)))).scalar()
    bets_pending = (await db.execute(
        select(func.count(VirtualBet.id)).where(VirtualBet.status == "pending")
    )).scalar()

    # Матчей по источникам
    hltv_fin = (await db.execute(
        select(func.count(Match.id)).where(Match.source == "hltv", Match.status == "finished")
    )).scalar()
    opendota_fin = (await db.execute(
        select(func.count(Match.id)).where(Match.source == "opendota", Match.status == "finished")
    )).scalar()

    text = (
        "*⚙️ Состояние системы:*\n\n"
        f"👥 Пользователей: *{e(str(users_count))}*\n"
        f"🏆 Команд в БД: *{e(str(teams_count))}*\n\n"
        f"📊 *Матчи:*\n"
        f"  Всего: *{e(str(matches_total))}*\n"
        f"  Завершённых: *{e(str(matches_finished))}* \\(HLTV: {e(str(hltv_fin))}, OD: {e(str(opendota_fin))}\\)\n"
        f"  Предстоящих/live: *{e(str(matches_upcoming))}*\n\n"
        f"📢 Telegram\\-каналов: *{e(str(channels_count))}*\n"
        f"💬 Сообщений в БД: *{e(str(messages_count))}*\n\n"
        f"💰 Демо\\-ставок: *{e(str(bets_count))}* \\(pending: {e(str(bets_pending))}\\)\n"
    )
    await message.answer(text)


async def _bets_status(message: Message, db: AsyncSession) -> None:
    from bets.virtual_bets import get_bet_stats, settle_pending_bets
    await settle_pending_bets(db)
    stats = await get_bet_stats(db)

    if stats.get("total", 0) == 0:
        await message.answer("💰 Виртуальных ставок пока нет\\.")
        return

    profit = stats["total_profit"]
    sign = "\\+" if profit >= 0 else ""
    text = (
        f"💰 *Виртуальные ставки*\n\n"
        f"Всего: *{e(str(stats['total']))}*\n"
        f"Выиграно: *{e(str(stats['won']))}* / Проиграно: *{e(str(stats['lost']))}* / Pending: *{e(str(stats['pending']))}*\n"
        f"Винрейт: *{e(str(stats['winrate']))}%*\n"
        f"P&L: *{e(sign + str(int(profit)))} ед\\.*\n"
        f"ROI: *{e(str(stats['roi']))}%*\n"
    )
    await message.answer(text)
