"""
Сборщик CS2 данных.

Источники:
- Liquipedia — предстоящие матчи (реальный парсинг HTML)
- Cybersport.ru — рейтинги команд (HLTV + Valve)

HLTV не предоставляет публичного API и блокирует прямой скрапинг.
"""
import asyncio
import logging
import ssl
from datetime import datetime
from typing import Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from db.models import Match, Team
from aggregator.aggregator import normalize_team_name

logger = logging.getLogger(__name__)


def _make_ssl_connector() -> aiohttp.TCPConnector:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return aiohttp.TCPConnector(ssl=ctx)


async def collect_cs2_data(db: AsyncSession):
    """Главная функция сбора CS2 данных (вызывается из scheduler)."""
    from collectors.liquipedia import run_liquipedia_sync
    logger.info("[CS2] Starting data collection via Liquipedia + Cybersport")
    try:
        await run_liquipedia_sync(db)
        logger.info("[CS2] Liquipedia sync complete")
    except Exception as e:
        logger.error(f"[CS2] Error in Liquipedia sync: {e}", exc_info=True)


async def run_hltv_sync(db: AsyncSession):
    """Синхронизировать CS2 данные (вызывается scheduler)."""
    await collect_cs2_data(db)


async def run_hltv_history_sync(db: AsyncSession, pages: int = 10):
    """Заглушка — исторические данные CS2 получаем из Liquipedia при обычном синке."""
    logger.info("[CS2 History] History sync redirected to standard collect_cs2_data")
    await collect_cs2_data(db)


# Совместимость — старый класс оставляем как заглушку
class HLTVCollector:
    """
    Заглушка для обратной совместимости.
    HLTV не предоставляет публичного API.
    Используй collect_cs2_data() или run_hltv_sync() вместо этого класса.
    """

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def close(self):
        if self.session:
            await self.session.close()

    async def fetch_upcoming_matches(self) -> list[dict]:
        logger.warning("HLTVCollector.fetch_upcoming_matches is deprecated, use collect_cs2_data()")
        return []

    async def fetch_match_results(self, limit: int = 50) -> list[dict]:
        logger.warning("HLTVCollector.fetch_match_results is deprecated, use collect_cs2_data()")
        return []

    async def fetch_team_rankings(self) -> list[dict]:
        logger.warning("HLTVCollector.fetch_team_rankings is deprecated, use collect_cs2_data()")
        return []
