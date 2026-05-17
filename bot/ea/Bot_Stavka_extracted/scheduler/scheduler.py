"""
Планировщик задач на APScheduler.
Запускает коллекторы по расписанию.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import config
from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Бот передаётся при создании планировщика для рассылки уведомлений
_bot = None


def set_bot(bot) -> None:
    global _bot
    _bot = bot


async def _job_opendota() -> None:
    logger.info("[Scheduler] OpenDota sync started")
    from collectors.opendota import run_opendota_sync
    async with AsyncSessionLocal() as db:
        await run_opendota_sync(db)


async def _job_hltv() -> None:
    logger.info("[Scheduler] HLTV sync started")
    from collectors.hltv import run_hltv_sync
    async with AsyncSessionLocal() as db:
        await run_hltv_sync(db)


async def _job_liquipedia() -> None:
    logger.info("[Scheduler] Liquipedia sync started")
    from collectors.liquipedia import run_liquipedia_sync
    async with AsyncSessionLocal() as db:
        await run_liquipedia_sync(db)


async def _job_patches() -> None:
    logger.info("[Scheduler] Patches sync started")
    from collectors.patches import run_patches_sync
    async with AsyncSessionLocal() as db:
        await run_patches_sync(db)


async def _job_telegram() -> None:
    logger.info("[Scheduler] Telegram sync started")
    from collectors.telegram_collector import run_telegram_sync
    async with AsyncSessionLocal() as db:
        await run_telegram_sync(db)


async def _job_ratings() -> None:
    logger.info("[Scheduler] Rating recalculation started")
    from collectors.rating import recalculate_ratings
    async with AsyncSessionLocal() as db:
        await recalculate_ratings(db, "cs2")
        await recalculate_ratings(db, "dota2")


async def _job_faceit() -> None:
    logger.info("[Scheduler] FACEIT sync started")
    from config import config
    if not config.FACEIT_API_KEY:
        logger.debug("FACEIT_API_KEY not set, skipping")
        return
    # FACEIT обогащает игроков которые уже есть в БД
    import aiohttp
    from collectors.faceit import FaceitCollector
    from db.models import Player
    from sqlalchemy import select, and_
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Player).where(
                and_(Player.game == "cs2", Player.source != "faceit")
            ).limit(50)
        )
        players = result.scalars().all()
        if not players:
            return
        async with aiohttp.ClientSession() as http:
            collector = FaceitCollector(http)
            for player in players:
                await collector.enrich_player(db, player.nickname)


async def _job_notifications() -> None:
    """Рассылка уведомлений о матчах через ~60 минут."""
    if _bot is None:
        return
    from bot.notifications import send_match_notifications
    async with AsyncSessionLocal() as db:
        count = await send_match_notifications(db, _bot)
        if count:
            logger.info("[Scheduler] Notifications sent: %d", count)


def create_scheduler(bot=None) -> AsyncIOScheduler:
    if bot is not None:
        set_bot(bot)

    scheduler = AsyncIOScheduler(timezone="UTC")

    # Каждые 2 часа — предстоящие матчи (OpenDota + HLTV)
    scheduler.add_job(
        _job_opendota,
        trigger=IntervalTrigger(hours=config.SCHEDULE_MATCHES_INTERVAL_HOURS),
        id="opendota_sync",
        name="OpenDota sync",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        _job_hltv,
        trigger=IntervalTrigger(hours=config.SCHEDULE_MATCHES_INTERVAL_HOURS),
        id="hltv_sync",
        name="HLTV sync",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Каждые 6 часов — статистика команд
    scheduler.add_job(
        _job_liquipedia,
        trigger=IntervalTrigger(hours=config.SCHEDULE_STATS_INTERVAL_HOURS),
        id="liquipedia_sync",
        name="Liquipedia sync",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Каждые 24 часа — патчи (ночью в 03:00 UTC)
    scheduler.add_job(
        _job_patches,
        trigger=CronTrigger(hour=3, minute=0),
        id="patches_sync",
        name="Patches sync",
        replace_existing=True,
    )

    # Каждые 60 секунд — Telegram-каналы
    scheduler.add_job(
        _job_telegram,
        trigger=IntervalTrigger(seconds=config.SCHEDULE_TG_INTERVAL_SECONDS),
        id="telegram_sync",
        name="Telegram sync",
        replace_existing=True,
        misfire_grace_time=30,
    )

    # Каждые 12 часов — пересчёт ELO-рейтингов по матчам из БД
    scheduler.add_job(
        _job_ratings,
        trigger=IntervalTrigger(hours=12),
        id="ratings_recalc",
        name="Ratings recalculation",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Каждые 6 часов — обогащение игроков CS2 через FACEIT
    scheduler.add_job(
        _job_faceit,
        trigger=IntervalTrigger(hours=6),
        id="faceit_sync",
        name="FACEIT sync",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Каждые 15 минут — проверка и рассылка уведомлений о матчах
    scheduler.add_job(
        _job_notifications,
        trigger=IntervalTrigger(minutes=15),
        id="match_notifications",
        name="Match notifications",
        replace_existing=True,
        misfire_grace_time=60,
    )

    return scheduler
