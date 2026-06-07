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


async def _job_opendota_live() -> None:
    from collectors.opendota import run_opendota_live_sync
    async with AsyncSessionLocal() as db:
        await run_opendota_live_sync(db)


async def _job_opendota_history() -> None:
    logger.info("[Scheduler] OpenDota history sync started")
    from collectors.opendota import run_opendota_history_sync
    async with AsyncSessionLocal() as db:
        await run_opendota_history_sync(db)


async def _job_opendota_detail_stats() -> None:
    logger.info("[Scheduler] OpenDota detail stats sync started")
    from collectors.opendota import run_opendota_detail_stats_sync
    async with AsyncSessionLocal() as db:
        await run_opendota_detail_stats_sync(db)


async def _job_hltv() -> None:
    logger.info("[Scheduler] HLTV sync started")
    from collectors.hltv import collect_cs2_data
    from aggregator.stats_saver import save_cs2_team_ratings, save_cs2_player_ratings
    async with AsyncSessionLocal() as db:
        data = await collect_cs2_data(db)
        hltv_rankings = data.get("team_rankings", [])
        player_ratings = data.get("player_ratings", [])

        # Сохраняем рейтинги команд и игроков
        t_updated = await save_cs2_team_ratings(db, hltv_rankings)
        p_updated = await save_cs2_player_ratings(db, player_ratings)
        logger.info("[Scheduler] HLTV: saved %d teams, %d players", t_updated, p_updated)


async def _job_hltv_history() -> None:
    logger.info("[Scheduler] HLTV history sync started")
    from collectors.hltv import run_hltv_history_sync
    async with AsyncSessionLocal() as db:
        await run_hltv_history_sync(db, pages=10)


async def _job_cybersport() -> None:
    logger.info("[Scheduler] Cybersport CS2 rankings sync started")
    from collectors.cybersport import collect_cs2_stats
    from aggregator.stats_saver import save_cs2_team_ratings
    async with AsyncSessionLocal() as db:
        data = await collect_cs2_stats(db)
        hltv_rankings = data.get("hltv_rankings", [])
        valve_rankings = data.get("valve_rankings", [])
        updated = await save_cs2_team_ratings(db, hltv_rankings, valve_rankings)
        logger.info("[Scheduler] Cybersport: saved %d team ratings", updated)


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


async def _job_process_news() -> None:
    """Обработка новых сообщений из TG-каналов через Gemini Flash / keywords."""
    logger.info("[Scheduler] News processing started")
    from analyzer.news_processor import process_unprocessed_messages
    from config import config
    async with AsyncSessionLocal() as db:
        created = await process_unprocessed_messages(
            db,
            gemini_key=config.GEMINI_API_KEY,
            gemini_model=config.GEMINI_MODEL,
            batch_size=40,
        )
        if created:
            logger.info("[Scheduler] News processing done: %d new events", created)


async def _job_daily_analysis() -> None:
    """Ежедневный анализ всех матчей и расстановка виртуальных ставок."""
    logger.info("[Scheduler] Daily analysis started")
    from analyzer.daily_analysis import analyze_all_today
    async with AsyncSessionLocal() as db:
        results = await analyze_all_today(db)
        new_bets = sum(1 for r in results if r.get("bet_placed"))
        logger.info("[Scheduler] Daily analysis done: %d matches, %d new bets", len(results), new_bets)


async def _job_news_digest(bot: Bot) -> None:
    """Ежедневный дайджест новостей — рассылаем админу (или в канал)."""
    logger.info("[Scheduler] News digest started")
    from analyzer.news_analyzer import get_recent_messages, build_digest
    from config import config
    async with AsyncSessionLocal() as db:
        messages = await get_recent_messages(db, hours=24, limit=300)
        parts = build_digest(messages, hours=24)
        if not parts or "_Нет_" in parts[0]:
            return
        try:
            for part in parts:
                await bot.send_message(config.ADMIN_ID, part)
            logger.info("[Scheduler] News digest sent: %d parts", len(parts))
        except Exception as e:
            logger.warning("[Scheduler] News digest send failed: %s", e)


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

    # Каждые 90 секунд — live-матчи Dota2 (лёгкий запрос, кэш лиг)
    scheduler.add_job(
        _job_opendota_live,
        trigger=IntervalTrigger(seconds=90),
        id="opendota_live",
        name="OpenDota live sync",
        replace_existing=True,
        misfire_grace_time=60,
    )

    scheduler.add_job(
        _job_hltv,
        trigger=IntervalTrigger(hours=config.SCHEDULE_MATCHES_INTERVAL_HOURS),
        id="hltv_sync",
        name="HLTV sync",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Каждые 5 минут — рейтинги CS2 команд (HLTV + Valve) для live обновлений
    scheduler.add_job(
        _job_cybersport,
        trigger=IntervalTrigger(minutes=5),
        id="cybersport_rankings",
        name="Cybersport CS2 rankings",
        replace_existing=True,
        misfire_grace_time=120,
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

    # Каждые 24 часа — детальная статистика (kills/towers/roshans) в 04:30 UTC
    scheduler.add_job(
        _job_opendota_detail_stats,
        trigger=CronTrigger(hour=4, minute=30),
        id="opendota_detail_stats",
        name="OpenDota detail stats",
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

    # Каждые 15 минут — обработка новостей (Gemini Flash / keywords)
    scheduler.add_job(
        _job_process_news,
        trigger=IntervalTrigger(minutes=15),
        id="process_news",
        name="News processing (Gemini)",
        replace_existing=True,
        misfire_grace_time=120,
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

    # Каждый день в 07:00 UTC (12:00 ЕКБ) — дайджест новостей за сутки
    scheduler.add_job(
        _job_news_digest,
        args=[bot],
        trigger=CronTrigger(hour=7, minute=0),
        id="news_digest",
        name="Daily news digest",
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
