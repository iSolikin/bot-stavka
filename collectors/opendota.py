"""
Сборщик данных Dota2 через OpenDota API.
Документация: https://docs.opendota.com/
"""
import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from config import config
from db.models import Match, Player, Team
from aggregator.aggregator import normalize_team_name

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
            normalized = normalize_team_name(name)

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
                team.normalized_name = normalize_team_name(name)
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

    async def fetch_pro_matches_paginated(self, pages: int = 4) -> list[dict]:
        """Загрузить последние про-матчи с пагинацией (несколько страниц)."""
        all_matches: list[dict] = []
        last_id: int | None = None
        for _ in range(pages):
            if last_id:
                if self.api_key:
                    path = f"/proMatches?api_key={self.api_key}&less_than_match_id={last_id}"
                else:
                    path = f"/proMatches?less_than_match_id={last_id}"
            else:
                path = "/proMatches"
            data = await self._get_raw(path)
            if not data:
                break
            all_matches.extend(data)
            if data:
                last_id = min(int(m.get("match_id", 0)) for m in data if m.get("match_id"))
        return all_matches

    async def _get_raw(self, path: str) -> list | None:
        """GET запрос по полному пути (без добавления api_key — уже в пути)."""
        url = f"{BASE_URL}{path}"
        if "?" not in path and self.api_key:
            url += f"?api_key={self.api_key}"
        try:
            async with self.session.get(url, headers=HEADERS) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning("OpenDota raw %s -> HTTP %s", path, resp.status)
                return None
        except Exception as e:
            logger.error("OpenDota raw request error %s: %s", path, e)
            return None

    async def save_pro_matches(self, db: AsyncSession, pages: int = 1) -> int:
        """Загрузить и сохранить последние про-матчи."""
        if pages > 1:
            matches_data = await self.fetch_pro_matches_paginated(pages)
        else:
            matches_data = await self.fetch_pro_matches()
        count = 0
        for m in matches_data:
            match_id = str(m.get("match_id", ""))
            if not match_id:
                continue

            # Пропускаем матчи без нормальных имён команд
            team1 = m.get("radiant_name") or ""
            team2 = m.get("dire_name") or ""
            if not team1 or not team2:
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
                team1_name=team1,
                team2_name=team2,
                tournament=m.get("league_name"),
                scheduled_at=scheduled_at,
                status="finished",
                score_team1=1 if m.get("radiant_win") else 0,
                score_team2=0 if m.get("radiant_win") else 1,
            )
            db.add(match)
            count += 1

        await db.commit()
        logger.info("OpenDota: saved %d finished matches", count)
        return count

    async def save_live_matches(self, db: AsyncSession) -> int:
        """Сохранить текущие live-матчи Dota2. Перед вставкой удаляет устаревшие live-записи."""
        # Удаляем старые live-записи (старше 2 часов — уже точно завершились)
        cutoff = datetime.utcnow() - timedelta(hours=2)
        await db.execute(
            delete(Match).where(
                Match.game == "dota2",
                Match.status == "live",
                Match.scheduled_at < cutoff,
            )
        )

        matches_data = await self.fetch_upcoming_matches()
        count = 0
        for m in matches_data:
            match_id = str(m.get("match_id", ""))
            if not match_id:
                continue

            # Берём имена команд из вложенных объектов
            team1 = (m.get("radiant_team") or {}).get("team_name") or ""
            team2 = (m.get("dire_team") or {}).get("team_name") or ""
            # Пропускаем матчи без нормальных имён команд
            if not team1 or not team2:
                continue

            result = await db.execute(
                select(Match).where(Match.external_id == match_id, Match.source == "opendota")
            )
            if result.scalar_one_or_none():
                continue

            match = Match(
                external_id=match_id,
                source="opendota",
                game="dota2",
                team1_name=team1,
                team2_name=team2,
                tournament=(m.get("league") or {}).get("name"),
                scheduled_at=datetime.utcnow(),
                status="live",
            )
            db.add(match)
            count += 1

        await db.commit()
        logger.info("OpenDota: saved %d live matches", count)
        return count


    async def save_team_matches_bulk(self, db: AsyncSession, top_n: int = 60, months: int = 12) -> int:
        """Получить историю матчей для топ-N команд из БД через /teams/{id}/matches.
        Каждая игра сохраняется как отдельная запись (как и /proMatches).
        Агрегация в серии происходит в Aggregator._get_recent_matches.
        months — глубина истории в месяцах (по умолчанию 12).
        """
        cutoff_ts = (datetime.utcnow() - timedelta(days=30 * months)).timestamp()

        from db.models import Team as TeamModel
        result = await db.execute(
            select(TeamModel)
            .where(TeamModel.source == "opendota", TeamModel.game == "dota2")
            .order_by(TeamModel.rating.desc())
            .limit(top_n)
        )
        teams = result.scalars().all()
        logger.info("OpenDota team-matches bulk: fetching for %d teams (last %d months)", len(teams), months)

        total = 0
        for team in teams:
            try:
                team_id = int(team.external_id)
            except (ValueError, TypeError):
                continue

            raw = await self.fetch_team_matches(team_id)
            if not raw:
                continue

            # Фильтруем по глубине истории, берём до 100 игр
            raw_filtered = [
                m for m in raw
                if m.get("start_time", 0) >= cutoff_ts
            ][:100]

            for m in raw_filtered:  # до 100 игр за последние N месяцев
                match_id = str(m.get("match_id", ""))
                if not match_id:
                    continue

                opposing = (m.get("opposing_team_name") or "").strip()
                if not opposing:
                    continue

                # Проверяем дубликат
                dup = await db.execute(
                    select(Match).where(
                        Match.external_id == match_id,
                        Match.source == "opendota",
                    )
                )
                if dup.scalar_one_or_none():
                    continue

                start_time = m.get("start_time")
                scheduled_at = datetime.utcfromtimestamp(start_time) if start_time else None

                is_radiant: bool = bool(m.get("radiant"))
                radiant_win: bool = bool(m.get("radiant_win"))
                is_win = (is_radiant == radiant_win)

                # team1 = наша команда, team2 = соперник
                match = Match(
                    external_id=match_id,
                    source="opendota",
                    game="dota2",
                    team1_name=team.name,
                    team2_name=opposing,
                    tournament=m.get("league_name"),
                    scheduled_at=scheduled_at,
                    status="finished",
                    score_team1=1 if is_win else 0,
                    score_team2=0 if is_win else 1,
                )
                db.add(match)
                total += 1

            await db.commit()  # commit после каждой команды

        logger.info("OpenDota team-matches bulk: saved %d new records", total)
        return total


async def run_opendota_sync(db: AsyncSession) -> None:
    """Точка входа для планировщика (быстрый, каждые 2 часа)."""
    async with aiohttp.ClientSession() as http:
        collector = OpenDotaCollector(http)
        await collector.save_teams(db)
        await collector.save_pro_matches(db)
        await collector.save_live_matches(db)
        logger.info("OpenDota sync complete")


async def run_opendota_history_sync(db: AsyncSession) -> None:
    """Точка входа для ежедневного накопления истории матчей по командам."""
    async with aiohttp.ClientSession() as http:
        collector = OpenDotaCollector(http)
        # Загружаем больше глобальных матчей (4 страницы ≈ 400)
        await collector.save_pro_matches(db, pages=4)
        # Загружаем историю по каждой команде
        await collector.save_team_matches_bulk(db, top_n=60)
        logger.info("OpenDota history sync complete")
