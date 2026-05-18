#!/usr/bin/env python3
"""
Простой скрипт для ручного запуска сборщиков данных.
Запуск: python run_collectors.py
"""
import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    from db.database import init_db, AsyncSessionLocal
    from collectors.hltv import run_hltv_sync
    from collectors.cybersport import sync_cs2_rankings

    logger.info("=" * 80)
    logger.info("ИНИЦИАЛИЗАЦИЯ БД")
    logger.info("=" * 80)
    await init_db()

    async with AsyncSessionLocal() as db:
        logger.info("")
        logger.info("=" * 80)
        logger.info("ЗАПУСК HLTV SYNC (собираем рейтинги команд и игроков)")
        logger.info("=" * 80)
        try:
            await run_hltv_sync(db)
        except Exception as e:
            logger.error(f"HLTV Sync ошибка: {e}", exc_info=True)

        logger.info("")
        logger.info("=" * 80)
        logger.info("ЗАПУСК CYBERSPORT SYNC (собираем HLTV и Valve рейтинги)")
        logger.info("=" * 80)
        try:
            await sync_cs2_rankings(db)
        except Exception as e:
            logger.error(f"Cybersport Sync ошибка: {e}", exc_info=True)

    logger.info("")
    logger.info("=" * 80)
    logger.info("ПРОВЕРЯЕМ ЧТО ПОПАЛО В БД")
    logger.info("=" * 80)

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        from db.models import Team, Player

        # Смотрим команды
        teams = (await db.execute(
            select(Team).where(Team.game == "cs2").order_by(Team.hltv_rating.desc())
        )).scalars().all()

        logger.info(f"\nКоманды CS2 в БД: {len(teams)} шт")
        if teams:
            for i, t in enumerate(teams[:5], 1):
                logger.info(
                    f"  {i}. {t.name:30s} | HLTV={str(t.hltv_rating or 'N/A'):>6s} | "
                    f"Valve={str(t.valve_rating or 'N/A'):>6s} | avg={str(round(t.rating, 2) if t.rating else 'N/A'):>6s}"
                )

        # Смотрим игроков
        players = (await db.execute(
            select(Player).where(Player.game == "cs2").order_by(Player.rating.desc())
        )).scalars().all()

        logger.info(f"\nИгроки CS2 в БД: {len(players)} шт")
        if players:
            for i, p in enumerate(players[:5], 1):
                logger.info(f"  {i}. {p.nickname:25s} | rating={p.rating or 'N/A'}")

    logger.info("")
    logger.info("=" * 80)
    logger.info("ГОТОВО")
    logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
