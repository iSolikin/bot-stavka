"""
Планировщик задач на APScheduler.
Запускает коллекторы по расписанию и рассылает уведомления о матчах.
"""
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from config import config
from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def _job_opendota() -> None:
    logger.info("[Scheduler] OpenDota sync started")
    from collectors.opendota import run_opendota_sync
    async with AsyncSessionLocal() as db:
        await run_opendota_sync(db)


async def _job_opendota_history() -> None:
    logger.info("[Scheduler] OpenDota history sync started")
    from collectors.opendota import run_opendota_history_sync
    async with AsyncSessionLocal() as db:
        await run_opendota_history_sync(db)


async def _job_hltv() -> None:
    logger.info("[Scheduler] HLTV sync started")
    from collectors.hltv import run_hltv_sync
    async with AsyncSessionLocal() as db:
        await run_hltv_sync(db)


async def _job_hltv_history() -> None:
    logger.info("[Scheduler] HLTV history sync started")
    from collectors.hltv import run_hltv_history_sync
    async with AsyncSessionLocal() as db:
        await run_hltv_history_sync(db, pages=10)


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


async def _job_daily_analysis() -> None:
    """Ежедневный анализ всех матчей и расстановка виртуальных ставок."""
    logger.info("[Scheduler] Daily analysis started")
    from analyzer.daily_analysis import analyze_all_today
    async with AsyncSessionLocal() as db:
        results = await analyze_all_today(db)
        new_bets = sum(1 for r in results if r.get("bet_placed"))
        logger.info("[Scheduler] Daily analysis done: %d matches, %d new bets", len(results), new_bets)


async def _job_settle_bets() -> None:
    """Автоматически сводим виртуальные ставки."""
    from bets.virtual_bets import settle_pending_bets
    async with AsyncSessionLocal() as db:
        settled = await settle_pending_bets(db)
        if settled:
            logger.info("[Scheduler] Virtual bets settled: %d", settled)


async def _job_notify(bot: Bot) -> None:
    """Рассылка уведомлений о матчах которые начнутся в течение часа."""
    from bot.notifications import send_match_notifications
    async with AsyncSessionLocal() as db:
        sent = await send_match_notifications(db, bot)
        if sent:
            logger.info("[Scheduler] Notifications sent: %d", sent)


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
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

    # Каждые 24 часа — история матчей по командам (в 04:00 UTC)
    scheduler.add_job(
        _job_opendota_history,
        trigger=CronTrigger(hour=4, minute=0),
        id="opendota_history_sync",
        name="OpenDota history sync",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Каждые 24 часа — исторические результаты CS2 с HLTV (в 05:00 UTC)
    scheduler.add_job(
        _job_hltv_history,
        trigger=CronTrigger(hour=5, minute=0),
        id="hltv_history_sync",
        name="HLTV history sync",
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

    # Каждый день в 06:00 UTC (11:00 ЕКБ) — анализ всех матчей дня
    scheduler.add_job(
        _job_daily_analysis,
        trigger=CronTrigger(hour=6, minute=0),
        id="daily_analysis",
        name="Daily match analysis",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Каждые 30 минут — сведение виртуальных ставок
    scheduler.add_job(
        _job_settle_bets,
        trigger=IntervalTrigger(minutes=30),
        id="settle_bets",
        name="Settle virtual bets",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # Каждые 5 минут — уведомления о предстоящих матчах
    scheduler.add_job(
        _job_notify,
        args=[bot],
        trigger=IntervalTrigger(minutes=5),
        id="notify_matches",
        name="Match notifications",
        replace_existing=True,
        misfire_grace_time=60,
    )

    return scheduler
