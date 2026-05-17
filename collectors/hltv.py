"""
Сборщик данных CS2 с HLTV.org API (быстро, надёжно, без браузера).
HLTV предоставляет бесплатный API для доступа к текущим матчам, турнирам и статистике.

API endpoints:
- https://www.hltv.org/api/matches/upcoming
- https://www.hltv.org/api/matches/results
- https://www.hltv.org/api/teams/ranking
- https://www.hltv.org/api/players/rating
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Match, Team
from aggregator.aggregator import normalize_team_name

logger = logging.getLogger(__name__)

HLTV_API = "https://www.hltv.org/api"


class HLTVCollector:
    """
    Сборщик CS2 данных через HLTV API.
    Без браузера, без задержек, без проблем с блокировкой.
    """

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    async def _get_json(self, url: str) -> dict | list | None:
        """Получить JSON с API HLTV."""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            async with self.session.get(url, headers=self.headers, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.warning(f"HLTV API returned {resp.status} for {url}")
                    return None
        except Exception as e:
            logger.error(f"HLTV API fetch error {url}: {e}")
            return None

    async def close(self):
        """Закрыть сессию."""
        if self.session:
            await self.session.close()

    async def fetch_upcoming_matches(self) -> list[dict]:
        """Получить предстоящие матчи CS2 из HLTV API."""
        data = await self._get_json(f"{HLTV_API}/matches/upcoming")
        if not data or not isinstance(data, list):
            return []

        matches = []
        for match in data:
            try:
                # HLTV API структура
                team1_data = match.get("team1", {})
                team2_data = match.get("team2", {})

                team1_name = team1_data.get("name", "").strip()
                team2_name = team2_data.get("name", "").strip()

                if not team1_name or not team2_name or "TBD" in (team1_name, team2_name):
                    continue

                # Дата/время матча (unix timestamp в секундах)
                timestamp = None
                if match.get("date"):
                    try:
                        timestamp = datetime.utcfromtimestamp(int(match["date"]))
                    except (ValueError, TypeError):
                        pass

                # Турнир
                event = match.get("event", {})
                tournament = event.get("name", "") if isinstance(event, dict) else str(event)

                # Формат (Bo1, Bo3 и т.д.)
                match_format = None
                if match.get("bestOf"):
                    match_format = f"Bo{match['bestOf']}"

                # URL матча
                match_id = match.get("id")
                match_url = f"https://www.hltv.org/matches/{match_id}" if match_id else None

                # Рейтинги команд (если доступны)
                team1_rating = team1_data.get("rating")
                team2_rating = team2_data.get("rating")

                matches.append({
                    "match_id": match_id,
                    "team1": team1_name,
                    "team2": team2_name,
                    "team1_rating": team1_rating,
                    "team2_rating": team2_rating,
                    "scheduled_at": timestamp,
                    "tournament": tournament,
                    "match_format": match_format,
                    "match_url": match_url,
                    "status": "upcoming",
                })
            except Exception as e:
                logger.warning(f"HLTV upcoming match parse error: {e}")
                continue

        logger.info(f"HLTV: fetched {len(matches)} upcoming CS2 matches")
        return matches

    async def fetch_match_results(self, limit: int = 50) -> list[dict]:
        """Получить результаты завершённых матчей CS2 из HLTV API."""
        data = await self._get_json(f"{HLTV_API}/matches/results")
        if not data or not isinstance(data, list):
            return []

        matches = []
        for match in data[:limit]:
            try:
                team1_data = match.get("team1", {})
                team2_data = match.get("team2", {})

                team1_name = team1_data.get("name", "").strip()
                team2_name = team2_data.get("name", "").strip()

                if not team1_name or not team2_name or "TBD" in (team1_name, team2_name):
                    continue

                # Результат матча
                result = match.get("result", {})
                score1 = result.get("team1", 0) if isinstance(result, dict) else 0
                score2 = result.get("team2", 0) if isinstance(result, dict) else 0

                # Дата завершения
                timestamp = None
                if match.get("date"):
                    try:
                        timestamp = datetime.utcfromtimestamp(int(match["date"]))
                    except (ValueError, TypeError):
                        pass

                # Турнир
                event = match.get("event", {})
                tournament = event.get("name", "") if isinstance(event, dict) else str(event)

                # Формат
                match_format = None
                if match.get("bestOf"):
                    match_format = f"Bo{match['bestOf']}"

                # URL матча
                match_id = match.get("id")
                match_url = f"https://www.hltv.org/matches/{match_id}" if match_id else None

                matches.append({
                    "match_id": match_id,
                    "team1": team1_name,
                    "team2": team2_name,
                    "score1": score1,
                    "score2": score2,
                    "scheduled_at": timestamp,
                    "tournament": tournament,
                    "match_format": match_format,
                    "match_url": match_url,
                    "status": "finished",
                })
            except Exception as e:
                logger.warning(f"HLTV result match parse error: {e}")
                continue

        logger.info(f"HLTV: fetched {len(matches)} CS2 match results")
        return matches

    async def fetch_team_rankings(self) -> list[dict]:
        """Получить рейтинги команд CS2 из HLTV API."""
        data = await self._get_json(f"{HLTV_API}/teams/ranking")
        if not data or not isinstance(data, list):
            return []

        teams = []
        for idx, team_data in enumerate(data):
            try:
                team_name = team_data.get("name", "").strip()
                team_id = team_data.get("id")

                if not team_name:
                    continue

                teams.append({
                    "name": team_name,
                    "team_id": team_id,
                    "rank": idx + 1,
                    "points": team_data.get("points"),
                    "rating": team_data.get("rating", 0.0),
                    "matches_played": team_data.get("matches"),
                    "country": team_data.get("country", {}).get("name") if isinstance(team_data.get("country"), dict) else None,
                })
            except Exception as e:
                logger.warning(f"HLTV ranking parse error: {e}")
                continue

        logger.info(f"HLTV: fetched {len(teams)} team rankings")
        return teams

    async def fetch_player_ratings(self, limit: int = 100) -> list[dict]:
        """Получить рейтинги лучших игроков CS2 из HLTV API."""
        data = await self._get_json(f"{HLTV_API}/players/rating")
        if not data or not isinstance(data, list):
            return []

        players = []
        for player_data in data[:limit]:
            try:
                player_name = player_data.get("name", "").strip()
                player_id = player_data.get("id")

                if not player_name:
                    continue

                players.append({
                    "name": player_name,
                    "player_id": player_id,
                    "rating": player_data.get("rating", 0.0),
                    "team": player_data.get("team", {}).get("name") if isinstance(player_data.get("team"), dict) else None,
                    "country": player_data.get("country", {}).get("name") if isinstance(player_data.get("country"), dict) else None,
                    "maps_played": player_data.get("maps"),
                })
            except Exception as e:
                logger.warning(f"HLTV player rating parse error: {e}")
                continue

        logger.info(f"HLTV: fetched {len(players)} player ratings")
        return players

    async def fetch_match_details(self, match_id: int) -> dict | None:
        """Получить детали конкретного матча (включая live данные)."""
        data = await self._get_json(f"{HLTV_API}/matches/{match_id}")
        if not data or not isinstance(data, dict):
            return None

        try:
            team1_data = data.get("team1", {})
            team2_data = data.get("team2", {})

            return {
                "match_id": match_id,
                "team1": team1_data.get("name"),
                "team1_rating": team1_data.get("rating"),
                "team2": team2_data.get("name"),
                "team2_rating": team2_data.get("rating"),
                "status": data.get("status"),
                "live_score": data.get("liveScore"),  # Актуальный счёт если матч идёт
                "maps": data.get("maps", []),
                "current_map": data.get("currentMap"),
                "result": data.get("result"),
                "tournament": data.get("event", {}).get("name") if isinstance(data.get("event"), dict) else None,
                "event_id": data.get("eventId"),
            }
        except Exception as e:
            logger.error(f"HLTV match details parse error for match {match_id}: {e}")
            return None


async def collect_cs2_data(db: AsyncSession):
    """Главная функция сбора CS2 данных (вызывается из scheduler)."""
    collector = HLTVCollector()

    try:
        # Собираем разные типы данных
        upcoming = await collector.fetch_upcoming_matches()
        results = await collector.fetch_match_results(limit=100)
        rankings = await collector.fetch_team_rankings()
        ratings = await collector.fetch_player_ratings(limit=200)

        logger.info(f"CS2 data collected: {len(upcoming)} upcoming, {len(results)} results, {len(rankings)} teams, {len(ratings)} players")

        # TODO: Сохранить в БД
        return {
            "upcoming_matches": upcoming,
            "match_results": results,
            "team_rankings": rankings,
            "player_ratings": ratings,
        }

    finally:
        await collector.close()
