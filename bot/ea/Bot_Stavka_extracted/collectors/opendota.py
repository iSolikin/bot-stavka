"""
Сборщик данных Dota2 через OpenDota API.
Документация: https://docs.opendota.com/
"""
import asyncio
import logging
from datetime import datetime

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import config
from db.models import Match, Player, Team

logger = logging.getLogger(__name__)

BASE_URL = config.OPENDOTA_BASE_URL
HEADERS = {"User-Agent": "esports-bot/1.0"}


class OpenDotaCollector:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.api_key = config.OPENDOTA_API_KEY

    def _url(self, path: str) -> str:
        url = f"{BASE_URL}{path}"
        if self.api_key:
            url += f"?api_key={self.api_key}"
        return url

    async def _get(self, path: str) -> dict | list | None:
        url = self._url(path)
        try:
            async with self.session.get(url, headers=HEADERS) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning("OpenDota %s -> HTTP %s", path, resp.status)
                return None
        except Exception as e:
            logger.error("OpenDota request error %s: %s", path, e)
            return None

    async def fetch_pro_teams(self) -> list[dict]:
        """Получить список профессиональных команд."""
        data = await self._get("/teams")
        return data if isinstance(data, list) else []

    async def fetch_team_matches(self, team_id: int) -> list[dict]:
        """Получить последние матчи команды."""
        data = await self._get(f"/teams/{team_id}/matches")
        return data if isinstance(data, list) else []

    async def fetch_pro_matches(self) -> list[dict]:
        """Получить последние профессиональные матчи."""
        data = await self._get("/proMatches")
        return data if isinstance(data, list) else []

    async def fetch_upcoming_matches(self) -> list[dict]:
        """Получить предстоящие матчи через scheduled matches."""
        data = await self._get("/live")
        return data if isinstance(data, list) else []

    async def fetch_team_players(self, team_id: int) -> list[dict]:
        """Получить игроков команды."""
        data = await self._get(f"/teams/{team_id}/players")
        return data if isinstance(data, list) else []

    async def fetch_player(self, account_id: int) -> dict | None:
        """Получить профиль игрока."""
        return await self._get(f"/players/{account_id}")

    # --- Сохранение в БД ---

    async def save_teams(self, db: AsyncSession) -> int:
        """Загрузить и сохранить команды. Возвращает кол-во добавленных/обновлённых."""
        teams_data = await self.fetch_pro_teams()
        count = 0
        for t in teams_data[:200]:  # берём топ-200
            team_id = str(t.get("team_id", ""))
            if not team_id:
                continue

            result = await db.execute(
                select(Team).where(Team.external_id == team_id, Team.source == "opendota")
            )
            team = result.scalar_one_or_none()

            name = t.get("name") or t.get("tag") or f"team_{team_id}"
            normalized = name.lower().strip()

            if team is None:
                team = Team(
                    external_id=team_id,
                    source="opendota",
                    game="dota2",
                    name=name,
                    normalized_name=normalized,
                    tag=t.get("tag"),
                    logo_url=t.get("logo_url"),
                    wins=t.get("wins", 0),
                    losses=t.get("losses", 0),
                    rating=float(t.get("rating", 0) or 0),
                )
                db.add(team)
            else:
                team.name = name
                team.normalized_name = normalized
                team.tag = t.get("tag")
                team.logo_url = t.get("logo_url")
                team.wins = t.get("wins", 0)
                team.losses = t.get("losses", 0)
                team.rating = float(t.get("rating", 0) or 0)
                team.updated_at = datetime.utcnow()

            count += 1

        await db.commit()
        logger.info("OpenDota: saved %d teams", count)
        return count

    async def save_pro_matches(self, db: AsyncSession) -> int:
        """Загрузить и сохранить последние про-матчи."""
        matches_data = await self.fetch_pro_matches()
        count = 0
        for m in matches_data[:50]:
            match_id = str(m.get("match_id", ""))
            if not match_id:
                continue

            result = await db.execute(
                select(Match).where(Match.external_id == match_id, Match.source == "opendota")
            )
            if result.scalar_one_or_none():
                continue  # уже есть

            start_time = m.get("start_time")
            scheduled_at = datetime.utcfromtimestamp(start_time) if start_time else None

            match = Match(
                external_id=match_id,
                source="opendota",
                game="dota2",
                team1_name=m.get("radiant_name") or "Radiant",
                team2_name=m.get("dire_name") or "Dire",
                tournament=m.get("league_name"),
                scheduled_at=scheduled_at,
                status="finished",
                score_team1=1 if m.get("radiant_win") else 0,
                score_team2=0 if m.get("radiant_win") else 1,
            )
            db.add(match)
            count += 1

        await db.commit()
        logger.info("OpenDota: saved %d matches", count)
        return count


async def run_opendota_sync(db: AsyncSession) -> None:
    """Точка входа для планировщика."""
    async with aiohttp.ClientSession() as http:
        collector = OpenDotaCollector(http)
        await collector.save_teams(db)
        await collector.save_pro_matches(db)
        logger.info("OpenDota sync complete")
