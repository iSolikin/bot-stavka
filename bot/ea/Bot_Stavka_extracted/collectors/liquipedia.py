"""
Сборщик данных с Liquipedia (турниры, составы, расписание).
Используем Liquipedia API + HTML парсинг как fallback.
"""
import asyncio
import logging
import random
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Match, Player, Team

logger = logging.getLogger(__name__)

LIQUIPEDIA_API = "https://liquipedia.net"
HEADERS = {
    "User-Agent": "esports-bot/1.0 (contact: your@email.com)",
    "Accept": "application/json",
}
# Liquipedia требует задержку между запросами
REQUEST_DELAY = 30  # секунд (по правилам API)


class LiquipediaCollector:
    def __init__(self, http: aiohttp.ClientSession):
        self.http = http
        self._last_request: float = 0

    async def _throttle(self) -> None:
        """Соблюдаем rate limit Liquipedia."""
        import time
        elapsed = time.time() - self._last_request
        if elapsed < REQUEST_DELAY:
            await asyncio.sleep(REQUEST_DELAY - elapsed)
        self._last_request = time.time()

    async def _get_api(self, game: str, params: dict) -> dict | None:
        await self._throttle()
        url = f"{LIQUIPEDIA_API}/{game}/api.php"
        try:
            async with self.http.get(url, params=params, headers=HEADERS) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                logger.warning("Liquipedia API %s -> HTTP %s", url, resp.status)
                return None
        except Exception as e:
            logger.error("Liquipedia request error: %s", e)
            return None

    async def _get_html(self, game: str, page: str) -> str | None:
        await self._throttle()
        url = f"{LIQUIPEDIA_API}/{game}/{page}"
        try:
            async with self.http.get(url, headers={**HEADERS, "Accept": "text/html"}) as resp:
                if resp.status == 200:
                    return await resp.text()
                return None
        except Exception as e:
            logger.error("Liquipedia HTML error: %s", e)
            return None

    async def fetch_matches(self, game: str) -> list[dict]:
        """Парсит и upcoming и completed. game: 'dota2' / 'counterstrike'"""
        lp_game = game if game == "dota2" else "counterstrike"
        html = await self._get_html(lp_game, "Liquipedia:Matches")
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        matches = []
        tournament_urls = set()  # для последующего глубокого парсинга

        for block in soup.select(".match-info"):
            # Запоминаем ссылки на турниры — потом туда сходим за полной историей
            wrapper = block.select_one(".match-info-tournament-wrapper")
            if wrapper:
                link = wrapper.find("a")
                if link and link.get("href"):
                    href = link["href"].split("#")[0]  # обрезаем якорь #Playoffs
                    if href.startswith("/"):
                        tournament_urls.add(href)
            try:
                opponents = block.select(".match-info-header-opponent")
                if len(opponents) < 2:
                    continue

                team1 = opponents[0].get_text(strip=True)
                team2 = opponents[1].get_text(strip=True)
                if not team1 or not team2 or team1 == "TBD" or team2 == "TBD":
                    continue

                tournament_el = block.select_one(".match-info-tournament-name")
                tournament = tournament_el.get_text(strip=True) if tournament_el else None

                # Определяем статус по верхней строке счёта: "vs" -> upcoming, иначе цифры
                upper = block.select_one(".match-info-header-scoreholder-upper")
                upper_text = upper.get_text(strip=True) if upper else "vs"
                lower = block.select_one(".match-info-header-scoreholder-lower")
                lower_text = lower.get_text(strip=True) if lower else ""

                if upper_text.lower() == "vs":
                    status = "upcoming"
                    match_format = lower_text or None
                    score1, score2 = None, None
                else:
                    status = "finished"
                    match_format = None
                    score1, score2 = self._parse_score(upper_text)
                    # Иногда формат прячется в .match-info-header-scoreholder-divider
                    div = block.select_one(".match-info-header-scoreholder-divider")
                    if div:
                        match_format = div.get_text(strip=True) or match_format

                countdown_el = block.select_one(".match-info-countdown")
                scheduled_at = self._parse_lp_time(countdown_el.get_text(strip=True) if countdown_el else "")

                matches.append({
                    "team1": team1,
                    "team2": team2,
                    "tournament": tournament,
                    "match_format": match_format,
                    "scheduled_at": scheduled_at,
                    "status": status,
                    "score1": score1,
                    "score2": score2,
                    "game": "dota2" if game == "dota2" else "cs2",
                    "source": "liquipedia",
                })
            except Exception as e:
                logger.debug("Liquipedia match parse error: %s", e)
                continue

        logger.info("Liquipedia %s: parsed %d matches (main page)", game, len(matches))
        # Сохраняем найденные турниры — пригодятся для глубокого парсинга
        self._last_tournament_urls = tournament_urls
        return matches

    async def fetch_tournament_matches(self, tournament_path: str, game: str) -> list[dict]:
        """Парсит конкретный турнир — даёт групповые матчи которых нет на главной."""
        await self._throttle()
        url = f"{LIQUIPEDIA_API}{tournament_path}"
        try:
            async with self.http.get(url, headers={**HEADERS, "Accept": "text/html"}) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
        except Exception as e:
            logger.error("Tournament %s error: %s", tournament_path, e)
            return []

        soup = BeautifulSoup(html, "lxml")
        # Имя турнира из заголовка
        title_el = soup.select_one("h1#firstHeading, h1.firstHeading")
        tournament_name = title_el.get_text(strip=True) if title_el else tournament_path.split("/")[-1]

        matches = []
        # Группа: brkts-matchlist-match
        for m in soup.select(".brkts-matchlist-match"):
            opps = m.select(".brkts-matchlist-opponent")
            scores = m.select(".brkts-matchlist-score")
            if len(opps) < 2 or len(scores) < 2:
                continue
            t1 = opps[0].get_text(strip=True)
            t2 = opps[1].get_text(strip=True)
            try:
                s1 = int(scores[0].get_text(strip=True))
                s2 = int(scores[1].get_text(strip=True))
            except ValueError:
                continue
            if not t1 or not t2 or t1.lower() in ("tbd", "bye") or t2.lower() in ("tbd", "bye"):
                continue

            matches.append({
                "team1": t1,
                "team2": t2,
                "tournament": tournament_name,
                "match_format": None,
                "scheduled_at": None,
                "status": "finished" if (s1 + s2) > 0 else "upcoming",
                "score1": s1 if (s1 + s2) > 0 else None,
                "score2": s2 if (s1 + s2) > 0 else None,
                "game": "dota2" if game == "dota2" else "cs2",
                "source": "liquipedia",
            })

        logger.info("Tournament %s: %d matches", tournament_path, len(matches))
        return matches

    def _parse_score(self, text: str) -> tuple[int | None, int | None]:
        """'2:1' -> (2, 1)"""
        import re
        m = re.match(r"(\d+)\s*[:\-]\s*(\d+)", text)
        if not m:
            return None, None
        return int(m.group(1)), int(m.group(2))

    async def fetch_upcoming_matches(self, game: str) -> list[dict]:
        """Бэк-совместимость: только upcoming."""
        return [m for m in await self.fetch_matches(game) if m["status"] == "upcoming"]

    def _parse_lp_time(self, text: str) -> datetime | None:
        """Парсим строку вида 'May 15, 2026 - 16:45EDT' в datetime UTC."""
        import re
        from datetime import timezone, timedelta

        TZ_OFFSETS = {
            "EDT": -4, "EST": -5, "PDT": -7, "PST": -8,
            "CEST": 2, "CET": 1, "UTC": 0, "BST": 1,
            "MSK": 3, "CST": 8, "JST": 9, "KST": 9,
        }

        m = re.search(r"(\w+ \d+, \d{4})\s*-\s*(\d{1,2}:\d{2})(\w+)?", text)
        if not m:
            return None
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %d, %Y %H:%M")
            tz_str = m.group(3) or "UTC"
            offset = TZ_OFFSETS.get(tz_str, 0)
            dt = dt - timedelta(hours=offset)
            return dt
        except Exception:
            return None

    async def fetch_team_roster(self, game: str, team_page: str) -> list[dict]:
        """Получить состав команды по названию страницы."""
        html = await self._get_html(game, team_page)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        players = []

        for row in soup.select(".roster-card tr"):
            cols = row.select("td")
            if len(cols) < 2:
                continue
            try:
                nickname_el = row.select_one(".ID")
                name_el = row.select_one(".Name")
                country_el = row.select_one(".flag")

                if not nickname_el:
                    continue

                players.append({
                    "nickname": nickname_el.get_text(strip=True),
                    "real_name": name_el.get_text(strip=True) if name_el else None,
                    "country": country_el.get("title") if country_el else None,
                })
            except Exception:
                continue

        return players

    # --- Сохранение в БД ---

    async def save_matches(self, db: AsyncSession, game: str, deep: bool = True) -> tuple[int, int]:
        """Сохраняет и upcoming и finished. deep=True парсит ещё и страницы турниров."""
        lp_game = "dota2" if game == "dota2" else "counterstrike"
        matches_data = await self.fetch_matches(lp_game)

        # Глубокий парсинг — проходимся по турнирам с главной страницы
        if deep and hasattr(self, "_last_tournament_urls"):
            tournament_urls = list(self._last_tournament_urls)
            # Лимит чтобы не упереться в rate limit (30 сек на запрос)
            for tpath in tournament_urls[:6]:
                deep_matches = await self.fetch_tournament_matches(tpath, game)
                matches_data.extend(deep_matches)

        new_up, new_fin = 0, 0

        for m in matches_data:
            if not m.get("team1") or not m.get("team2"):
                continue

            # Дубликат: ищем по командам + турниру (без жёсткой привязки ко времени)
            from sqlalchemy import or_, and_
            result = await db.execute(
                select(Match).where(
                    Match.team1_name == m["team1"],
                    Match.team2_name == m["team2"],
                    Match.source == "liquipedia",
                    or_(
                        Match.tournament == m.get("tournament"),
                        and_(
                            Match.scheduled_at.isnot(None),
                            Match.scheduled_at == m.get("scheduled_at"),
                        ),
                    ),
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                changed = False
                # upcoming -> finished
                if existing.status != m["status"] and m["status"] == "finished":
                    existing.status = "finished"
                    existing.score_team1 = m.get("score1")
                    existing.score_team2 = m.get("score2")
                    new_fin += 1
                    changed = True
                # Подмержим время если его не было
                if existing.scheduled_at is None and m.get("scheduled_at"):
                    existing.scheduled_at = m["scheduled_at"]
                    changed = True
                if existing.match_format is None and m.get("match_format"):
                    existing.match_format = m["match_format"]
                    changed = True
                continue

            match = Match(
                source="liquipedia",
                game=game,
                team1_name=m["team1"],
                team2_name=m["team2"],
                tournament=m.get("tournament"),
                match_format=m.get("match_format"),
                scheduled_at=m.get("scheduled_at"),
                status=m["status"],
                score_team1=m.get("score1"),
                score_team2=m.get("score2"),
            )
            db.add(match)
            if m["status"] == "finished":
                new_fin += 1
            else:
                new_up += 1

        await db.commit()
        logger.info("Liquipedia %s: +%d upcoming, +%d finished", game, new_up, new_fin)
        return new_up, new_fin

    async def save_upcoming_matches(self, db: AsyncSession, game: str) -> int:
        """Бэк-совместимость."""
        up, fin = await self.save_matches(db, game)
        return up + fin


async def run_liquipedia_sync(db: AsyncSession) -> None:
    """Точка входа для планировщика."""
    async with aiohttp.ClientSession() as http:
        collector = LiquipediaCollector(http)
        await collector.save_matches(db, "dota2")
        await collector.save_matches(db, "cs2")
        # После сбора матчей пересчитываем рейтинги команд
        from collectors.rating import recalculate_ratings
        await recalculate_ratings(db, "cs2")
        await recalculate_ratings(db, "dota2")
        logger.info("Liquipedia sync complete")
