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

    async def fetch_upcoming_matches(self, game: str) -> list[dict]:
        """
        game: 'dota2' или 'counterstrike'
        Парсим главную страницу Liquipedia:Matches + страницы активных турниров.
        """
        html = await self._get_html(game, "Liquipedia:Matches")
        matches = self._parse_html_matches(html or "", game)
        logger.info("Liquipedia %s: main page -> %d matches", game, len(matches))

        # Дополнительно парсим страницы активных турниров (через urllib — без SSL-проблем)
        if game == "counterstrike":
            extra = await asyncio.get_event_loop().run_in_executor(
                None, _fetch_cs2_tournament_matches
            )
            # Дедупликация: если (tournament, scheduled_at) уже есть — пропускаем
            # чтобы не было "1w Team" + "1w" для одного и того же матча
            existing_time_keys = {
                (m.get("tournament"), m.get("scheduled_at"))
                for m in matches
                if m.get("scheduled_at")
            }
            for m in extra:
                time_key = (m.get("tournament"), m.get("scheduled_at"))
                if time_key not in existing_time_keys:
                    matches.append(m)
                    existing_time_keys.add(time_key)
            logger.info("Liquipedia cs2: after tournament pages -> %d matches total", len(matches))

        return matches

    def _parse_html_matches(self, html: str, game: str) -> list[dict]:
        """Парсер HTML страницы матчей Liquipedia (новая структура 2025)."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        matches = []

        for row in soup.find_all("div", class_="match-info"):
            try:
                # Timestamp
                timer = row.find("span", class_="timer-object")
                scheduled_at = None
                if timer and timer.get("data-timestamp"):
                    ts = int(timer["data-timestamp"])
                    scheduled_at = datetime.utcfromtimestamp(ts)

                # Команды
                opponents = row.find_all("div", class_="match-info-header-opponent")
                if len(opponents) < 2:
                    continue

                def _team_name(el) -> str:
                    # Ищем a[title] внутри .name span
                    name_span = el.find("span", class_="name")
                    if name_span:
                        a = name_span.find("a")
                        if a and a.get("title"):
                            # Убираем суффикс "(page does not exist)"
                            return a["title"].replace("(page does not exist)", "").strip()
                        if name_span.get_text(strip=True):
                            return name_span.get_text(strip=True)
                    # Fallback: любой a[title]
                    a = el.find("a", title=True)
                    return a["title"].strip() if a else ""

                team1 = _team_name(opponents[0])
                team2 = _team_name(opponents[1])
                if not team1 or not team2:
                    continue

                # Формат (Bo3, Bo5...)
                score_lower = row.find("span", class_="match-info-header-scoreholder-lower")
                match_format = ""
                if score_lower:
                    txt = score_lower.get_text(strip=True).strip("()")
                    if txt:
                        match_format = txt

                # Турнир
                tournament = None
                tourn_div = row.find("div", class_="match-info-tournament")
                if tourn_div:
                    a = tourn_div.find("a", title=True)
                    if a:
                        # "Cringe Station/Lunar Horse Trophy/7#May 17" → берём чистое имя
                        tournament = a["title"].split("#")[0].strip()

                matches.append({
                    "team1": team1,
                    "team2": team2,
                    "scheduled_at": scheduled_at,
                    "match_format": match_format,
                    "tournament": tournament,
                    "game": "dota2" if game == "dota2" else "cs2",
                    "source": "liquipedia",
                })
            except Exception as ex:
                logger.debug("Error parsing match row: %s", ex)
                continue

        return matches

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

    async def save_upcoming_matches(self, db: AsyncSession, game: str) -> int:
        from datetime import timezone, timedelta
        from sqlalchemy import delete

        lp_game = "dota2" if game == "dota2" else "counterstrike"
        matches_data = await self.fetch_upcoming_matches(lp_game)

        # Удаляем все стухшие upcoming от этого источника для данной игры
        now = datetime.utcnow()
        await db.execute(
            delete(Match).where(
                Match.source == "liquipedia",
                Match.game == game,
                Match.status == "upcoming",
            )
        )

        count = 0
        cutoff_past = now - timedelta(days=7)  # не берём матчи старше 7 дней
        for m in matches_data:
            if not m.get("team1") or not m.get("team2"):
                continue
            scheduled = m.get("scheduled_at")
            # Пропускаем матчи без даты или слишком старые
            if scheduled and scheduled < cutoff_past:
                continue
            # Прошедшие матчи — finished, будущие — upcoming
            status = "finished" if scheduled and scheduled < now else "upcoming"

            match = Match(
                source="liquipedia",
                game=game,
                team1_name=m["team1"],
                team2_name=m["team2"],
                tournament=m.get("tournament"),
                match_format=m.get("match_format"),
                scheduled_at=scheduled,
                status=status,
            )
            db.add(match)
            count += 1

        await db.commit()
        logger.info("Liquipedia %s: saved %d matches", game, count)
        return count


def _fetch_page_matches_urllib(url: str, game_tag: str, tournament_name: str) -> list[dict]:
    """Синхронный парсер страницы турнира через urllib (без aiohttp SSL-проблем)."""
    import urllib.request
    import ssl
    import time

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "esports-bot/1.0", "Accept": "text/html"}
        )
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("Tournament page fetch failed %s: %s", url, e)
        return []

    soup = BeautifulSoup(html, "lxml")
    now = datetime.utcnow()
    matches = []
    seen = set()

    for row in soup.find_all("div", class_="match-info"):
        try:
            timer = row.find("span", class_="timer-object")
            if not timer or not timer.get("data-timestamp"):
                continue
            scheduled_at = datetime.utcfromtimestamp(int(timer["data-timestamp"]))
            if scheduled_at < now - __import__("datetime").timedelta(hours=2):
                continue

            # Пробуем match-info-header-opponent сначала, потом span.name как fallback
            def _name(el):
                ns = el.find("span", class_="name")
                if ns:
                    a = ns.find("a")
                    if a and a.get("title"):
                        return a["title"].replace("(page does not exist)", "").strip()
                    return ns.get_text(strip=True)
                a = el.find("a", title=True)
                return a["title"].strip() if a else ""

            opponents = row.find_all("div", class_="match-info-header-opponent")
            if len(opponents) >= 2:
                t1, t2 = _name(opponents[0]), _name(opponents[1])
            else:
                # Fallback для турнирных страниц: span.name напрямую
                names = [
                    n.get_text(strip=True)
                    for n in row.find_all("span", class_="name")
                    if n.get_text(strip=True) not in ("", "TBD")
                ]
                if len(names) < 2:
                    continue
                t1, t2 = names[0], names[-1]

            if not t1 or not t2 or t1 == t2 or "TBD" in (t1, t2):
                continue

            key = (t1, t2, scheduled_at.isoformat())
            if key in seen:
                continue
            seen.add(key)

            fmt_el = row.find("span", class_="match-info-header-scoreholder-lower")
            fmt = fmt_el.get_text(strip=True).strip("()") if fmt_el else ""

            matches.append({
                "team1": t1,
                "team2": t2,
                "scheduled_at": scheduled_at,
                "match_format": fmt,
                "tournament": tournament_name,
                "game": game_tag,
                "source": "liquipedia",
            })
        except Exception as ex:
            logger.debug("Tournament match parse error: %s", ex)

    return matches


# Список активных CS2 турниров для дополнительного парсинга
# Обновляй когда меняются турниры (slug = часть URL на liquipedia.net/counterstrike/<slug>)
CS2_ACTIVE_TOURNAMENTS = [
    ("NODWIN_Gaming/Clutch_Series/8",  "NODWIN Gaming/Clutch Series/8"),
    ("CS_Asia_Championships/2026",     "CS Asia Championships/2026"),
]


def _fetch_cs2_tournament_matches() -> list[dict]:
    """Собирает матчи со страниц активных CS2 турниров."""
    import time
    all_matches = []
    for slug, name in CS2_ACTIVE_TOURNAMENTS:
        url = f"https://liquipedia.net/counterstrike/{slug}"
        m = _fetch_page_matches_urllib(url, "cs2", name)
        logger.info("Tournament %s: %d matches", name, len(m))
        all_matches.extend(m)
        time.sleep(3)
    return all_matches


async def run_liquipedia_sync(db: AsyncSession) -> None:
    """Точка входа для планировщика."""
    import ssl
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(connector=connector) as http:
        collector = LiquipediaCollector(http)
        await collector.save_upcoming_matches(db, "dota2")
        await collector.save_upcoming_matches(db, "cs2")
        logger.info("Liquipedia sync complete")
