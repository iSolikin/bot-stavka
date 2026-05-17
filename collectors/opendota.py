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
from db.models import Match, Player, Team, MatchDetailStats
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


    async def fetch_match_detail(self, match_id: int) -> dict | None:
        """Получить детальную статистику одного матча."""
        return await self._get(f"/matches/{match_id}")

    @staticmethod
    def _count_towers_destroyed(status_bits: int, total: int = 9) -> int:
        """Считаем уничтоженные башни из bitmask (1=стоит, 0=снесена)."""
        standing = bin(status_bits).count("1")
        return max(0, total - standing)

    @staticmethod
    def _had_megacreeps(radiant_barracks: int, dire_barracks: int) -> bool:
        """Были ли мегакрипы (все казармы одной стороны снесены)."""
        return radiant_barracks == 0 or dire_barracks == 0

    @staticmethod
    def _first_blood_team(objectives: list, is_team1_radiant: bool) -> str | None:
        """Определяем кто взял первую кровь."""
        for obj in objectives:
            if obj.get("type") == "CHAT_MESSAGE_FIRSTBLOOD":
                # player_slot 0-4 = radiant, 128-132 = dire
                slot = obj.get("player_slot", -1)
                fb_radiant = slot is not None and slot < 100
                if is_team1_radiant:
                    return "team1" if fb_radiant else "team2"
                else:
                    return "team2" if fb_radiant else "team1"
        return None

    @staticmethod
    def _first_tower_team(objectives: list, is_team1_radiant: bool) -> str | None:
        """Кто снёс первую башню."""
        for obj in sorted(objectives, key=lambda o: o.get("time", 9999)):
            if obj.get("type") in ("CHAT_MESSAGE_TOWER_KILL", "building_kill"):
                # team = 2 (radiant kills) или 3 (dire kills)
                team = obj.get("team")
                if team == 2:  # radiant team kills
                    return "team1" if is_team1_radiant else "team2"
                elif team == 3:
                    return "team2" if is_team1_radiant else "team1"
        return None

    @staticmethod
    def _count_roshans(objectives: list) -> int:
        """Считаем убийства Рошана."""
        return sum(1 for o in objectives if "ROSHAN" in o.get("type", "").upper())

    async def save_match_detail_stats(
        self,
        db: AsyncSession,
        match_ids: list[int],
        team_name_map: dict[int, tuple[str, str, bool]],  # match_id → (team1_name, team2_name, team1_is_radiant)
    ) -> int:
        """
        Загружаем детальную статистику для списка match_id.
        team_name_map: {match_id: (team1_name, team2_name, team1_is_radiant)}
        """
        saved = 0
        for match_id in match_ids:
            ext_id = str(match_id)
            # Проверяем дубликат
            dup = await db.execute(
                select(MatchDetailStats).where(
                    MatchDetailStats.external_match_id == ext_id,
                    MatchDetailStats.source == "opendota",
                )
            )
            if dup.scalar_one_or_none():
                continue

            detail = await self.fetch_match_detail(match_id)
            if not detail or "match_id" not in detail:
                await asyncio.sleep(1)
                continue

            team1_name, team2_name, t1_radiant = team_name_map.get(
                match_id, ("Team 1", "Team 2", True)
            )

            # Килы
            r_score = detail.get("radiant_score", 0) or 0
            d_score = detail.get("dire_score", 0) or 0
            t1_kills = r_score if t1_radiant else d_score
            t2_kills = d_score if t1_radiant else r_score

            # Башни
            r_towers = detail.get("tower_status_radiant", 511) or 511  # 511 = все стоят
            d_towers = detail.get("tower_status_dire", 511) or 511
            t1_towers_dest = self._count_towers_destroyed(d_towers if t1_radiant else r_towers)
            t2_towers_dest = self._count_towers_destroyed(r_towers if t1_radiant else d_towers)

            # Казармы / мегакрипы
            r_barracks = detail.get("barracks_status_radiant", 63) or 63
            d_barracks = detail.get("barracks_status_dire", 63) or 63
            megacreeps = self._had_megacreeps(r_barracks, d_barracks)

            # Objectives (первая кровь, рошаны, первая башня)
            objectives = detail.get("objectives") or []
            fb_team = self._first_blood_team(objectives, t1_radiant)
            ft_team = self._first_tower_team(objectives, t1_radiant)
            roshans = self._count_roshans(objectives)

            # Победитель
            radiant_win = bool(detail.get("radiant_win"))
            winner = ("team1" if radiant_win else "team2") if t1_radiant else \
                     ("team2" if radiant_win else "team1")

            start_time = detail.get("start_time")
            match_date = datetime.utcfromtimestamp(start_time) if start_time else None

            stat = MatchDetailStats(
                external_match_id=ext_id,
                source="opendota",
                game="dota2",
                team1_name=team1_name,
                team2_name=team2_name,
                winner=winner,
                duration_seconds=detail.get("duration"),
                total_kills=r_score + d_score,
                team1_kills=t1_kills,
                team2_kills=t2_kills,
                team1_towers=t1_towers_dest,
                team2_towers=t2_towers_dest,
                total_towers=t1_towers_dest + t2_towers_dest,
                total_roshans=roshans,
                first_blood_team=fb_team,
                first_tower_team=ft_team,
                had_megacreeps=megacreeps,
                match_date=match_date,
                tournament=detail.get("league", {}).get("name") if isinstance(detail.get("league"), dict) else None,
            )
            db.add(stat)
            saved += 1
            await asyncio.sleep(0.5)  # rate limit: 60 req/min без ключа

            if saved % 20 == 0:
                await db.commit()
                logger.info("OpenDota detail stats: saved %d so far", saved)

        if saved:
            await db.commit()
        return saved

    async def sync_detail_stats_for_teams(
        self, db: AsyncSession, top_n: int = 30, games_per_team: int = 20
    ) -> int:
        """
        Для топ-N команд загружаем детальную статистику последних игр.
        """
        from db.models import Team as TeamModel
        result = await db.execute(
            select(TeamModel)
            .where(TeamModel.source == "opendota", TeamModel.game == "dota2")
            .order_by(TeamModel.rating.desc())
            .limit(top_n)
        )
        teams = result.scalars().all()
        logger.info("OpenDota: syncing detail stats for %d teams", len(teams))

        total = 0
        for team in teams:
            try:
                team_id = int(team.external_id)
            except (ValueError, TypeError):
                continue

            raw = await self.fetch_team_matches(team_id)
            if not raw:
                continue

            # Берём последние N игр
            recent = sorted(raw, key=lambda m: m.get("start_time", 0), reverse=True)[:games_per_team]

            match_ids = []
            name_map = {}
            for m in recent:
                mid = m.get("match_id")
                if not mid:
                    continue
                opposing = (m.get("opposing_team_name") or "").strip() or "Unknown"
                is_radiant = bool(m.get("radiant"))
                t1_name = team.name if is_radiant else opposing
                t2_name = opposing if is_radiant else team.name
                match_ids.append(mid)
                name_map[mid] = (t1_name, t2_name, is_radiant)

            saved = await self.save_match_detail_stats(db, match_ids, name_map)
            total += saved
            logger.info("OpenDota detail stats: %s → %d games", team.name, saved)
            await asyncio.sleep(1)

        logger.info("OpenDota detail stats sync complete: %d total", total)
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


async def run_opendota_detail_stats_sync(db: AsyncSession) -> None:
    """Точка входа для сбора детальной статистики (kills, towers, roshans)."""
    async with aiohttp.ClientSession() as http:
        collector = OpenDotaCollector(http)
        await collector.sync_detail_stats_for_teams(db, top_n=40, games_per_team=25)
        logger.info("OpenDota detail stats sync complete")
