#!/usr/bin/env python3
"""
Тест: инициализируем свежую БД и заполняем её реальными данными.
"""
import asyncio
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

# Временно меняем DATABASE_URL чтобы использовать другой файл
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_bot.db"


async def main():
    from db.database import init_db, AsyncSessionLocal
    from collectors.hltv import run_hltv_sync
    from collectors.cybersport import sync_cs2_rankings

    logger.info("=" * 80)
    logger.info("ИНИЦИАЛИЗАЦИЯ СВЕЖЕЙ БД (test_bot.db)")
    logger.info("=" * 80)
    await init_db()

    async with AsyncSessionLocal() as db:
        logger.info("")
        logger.info("=" * 80)
        logger.info("ЗАПУСК HLTV SYNC")
        logger.info("=" * 80)
        try:
            await run_hltv_sync(db)
            logger.info("✓ HLTV Sync успешен")
        except Exception as e:
            logger.error(f"✗ HLTV Sync ошибка: {e}")

        logger.info("")
        logger.info("=" * 80)
        logger.info("ЗАПУСК CYBERSPORT SYNC")
        logger.info("=" * 80)
        try:
            await sync_cs2_rankings(db)
            logger.info("✓ Cybersport Sync успешен")
        except Exception as e:
            logger.error(f"✗ Cybersport Sync ошибка: {e}")

    logger.info("")
    logger.info("=" * 80)
    logger.info("РЕЗУЛЬТАТЫ В БД")
    logger.info("=" * 80)

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select, func
        from db.models import Team, Player

        # Команды
        teams_count = (await db.execute(
            select(func.count(Team.id)).where(Team.game == "cs2")
        )).scalar()

        # Игроки
        players_count = (await db.execute(
            select(func.count(Player.id)).where(Player.game == "cs2")
        )).scalar()

        logger.info(f"\n✓ Команд CS2 в БД: {teams_count}")
        logger.info(f"✓ Игроков CS2 в БД: {players_count}")

        # Топ команды
        if teams_count > 0:
            teams = (await db.execute(
                select(Team).where(Team.game == "cs2").order_by(Team.hltv_rating.desc()).limit(5)
            )).scalars().all()

            logger.info("\nТоп-5 команд:")
            for i, t in enumerate(teams, 1):
                logger.info(
                    f"  {i}. {t.name:25s} | HLTV={str(t.hltv_rating or '-'):>6s} | "
                    f"Valve={str(t.valve_rating or '-'):>6s} | "
                    f"avg={str(round(t.rating, 2) if t.rating else '-'):>6s}"
                )

        # Топ игроки
        if players_count > 0:
            players = (await db.execute(
                select(Player).where(Player.game == "cs2").order_by(Player.rating.desc()).limit(5)
            )).scalars().all()

            logger.info("\nТоп-5 игроков:")
            for i, p in enumerate(players, 1):
                logger.info(f"  {i}. {p.nickname:25s} | rating={p.rating or '-'}")

    logger.info("\n✓ ГОТОВО! БД заполнена реальными данными в test_bot.db")
    logger.info("\nДля использования в боте:")
    logger.info("  rm bot.db.bak bot.db")
    logger.info("  cp test_bot.db bot.db")


if __name__ == "__main__":
    asyncio.run(main())
