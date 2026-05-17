"""
Сборщик данных CS2 с HLTV.org через Playwright (headless браузер).
HLTV активно блокирует ботов, поэтому используем реальный браузер + задержки.
"""
import asyncio
import logging
import random
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, Page
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Match, Team
from aggregator.aggregator import normalize_team_name

logger = logging.getLogger(__name__)

HLTV_BASE = "https://www.hltv.org"

# Месяцы для парсинга текстовых дат HLTV ("May 14th 2026", "14th May 2026")
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_hltv_date(text: str) -> datetime | None:
    """Парсит текстовую дату HLTV: 'May 14th 2026', '14th May 2026', '2026-05-14'."""
    if not text:
        return None
    import re
    text = text.strip()
    # ISO формат
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # "May 14th 2026" или "14th May 2026"
    parts = re.findall(r"[a-zA-Z]+|\d+", text)
    month, day, year = None, None, None
    for part in parts:
        if part.lower() in _MONTHS:
            month = _MONTHS[part.lower()]
        elif part.isdigit():
            n = int(part)
            if n > 31:
                year = n
            elif day is None:
                day = n
    if month and day and year:
        try:
            return datetime(year, month, day)
        except ValueError:
            pass
    return None

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


class HLTVCollector:
    def __init__(self, browser: Browser):
        self.browser = browser

    async def _new_page(self) -> Page:
        context = await self.browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = await context.new_page()
        # Блокируем тяжёлые ресурсы для ускорения
        await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2}", lambda r: r.abort())
        return page

    async def _get_html(self, url: str, wait_selector: str = "body") -> str | None:
        page = await self._new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector(wait_selector, timeout=10000)
            # Случайная задержка 3–6 сек чтобы не триггерить защиту
            await asyncio.sleep(random.uniform(3, 6))
            return await page.content()
        except Exception as e:
            logger.error("HLTV fetch error %s: %s", url, e)
            return None
        finally:
            await page.context.close()

    async def fetch_upcoming_matches(self) -> list[dict]:
        """Парсим предстоящие матчи CS2."""
        html = await self._get_html(f"{HLTV_BASE}/matches", ".upcomingMatchesSection")
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        matches = []

        for match_div in soup.select(".upcomingMatch"):
            try:
                teams = match_div.select(".matchTeamName")
                if len(teams) < 2:
                    continue

                team1 = teams[0].get_text(strip=True)
                team2 = teams[1].get_text(strip=True)

                # Время матча
                time_el = match_div.select_one(".matchTime")
                timestamp = None
                if time_el and time_el.get("data-unix"):
                    ts = int(time_el["data-unix"]) // 1000
                    timestamp = datetime.utcfromtimestamp(ts)

                # Турнир
                event_el = match_div.select_one(".matchEventName")
                tournament = event_el.get_text(strip=True) if event_el else None

                # Формат
                format_el = match_div.select_one(".matchMeta")
                match_format = format_el.get_text(strip=True) if format_el else None

                # Ссылка
                link_el = match_div.select_one("a.match")
                match_url = HLTV_BASE + link_el["href"] if link_el else None

                matches.append({
                    "team1": team1,
                    "team2": team2,
                    "scheduled_at": timestamp,
                    "tournament": tournament,
                    "match_format": match_format,
                    "match_url": match_url,
                })
            except Exception as e:
                logger.warning("HLTV match parse error: %s", e)
                continue

        logger.info("HLTV: parsed %d upcoming matches", len(matches))
        return matches

    async def fetch_match_results(self, pages: int = 10) -> list[dict]:
        """Парсим результаты завершённых матчей CS2 (страница /results).
        pages — сколько страниц результатов (по ~100 матчей на страницу).
        """
        all_matches: list[dict] = []
        for page_num in range(pages):
            offset = page_num * 100
            url = f"{HLTV_BASE}/results?offset={offset}&game=cs2"
            html = await self._get_html(url, "body")
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")

            # Ищем все блоки с датой и матчами внутри
            # HLTV: .results-sublist содержит заголовок даты и список матчей
            sublists = soup.select(".results-sublist")
            if not sublists:
                # Попробуем общий контейнер
                sublists = [soup]

            page_count = 0
            for sublist in sublists:
                # Дата блока: <div class="standard-headline results-date">May 14th 2026</div>
                # или <span data-unix="...">
                current_date: datetime | None = None
                date_el = sublist.select_one(".results-date, .standard-headline")
                if date_el:
                    # Пробуем data-unix
                    unix_el = date_el.find(attrs={"data-unix": True})
                    if unix_el:
                        try:
                            ts = int(unix_el["data-unix"]) // 1000
                            current_date = datetime.utcfromtimestamp(ts)
                        except (ValueError, TypeError):
                            pass
                    # Пробуем text-дату: "May 14th 2026" / "17th May 2026"
                    if not current_date:
                        date_text = date_el.get_text(strip=True)
                        current_date = _parse_hltv_date(date_text)

                # Матчи внутри блока
                result_items = sublist.select("a.a-reset[href*='/matches/']")
                if not result_items:
                    result_items = sublist.select(".result-con a, a.played")

                for item in result_items:
                    try:
                        # Команды: <div class="team">...</div>
                        teams = item.select(".team")
                        if len(teams) < 2:
                            # Альтернативный вариант
                            teams = item.select(".matchTeamName, .teamName")
                        if len(teams) < 2:
                            continue
                        team1 = teams[0].get_text(strip=True)
                        team2 = teams[1].get_text(strip=True)
                        if not team1 or not team2 or "TBD" in (team1, team2):
                            continue

                        # Счёт: <span class="won">2</span> - <span>1</span>
                        score1, score2 = None, None
                        score_el = item.select_one(".result-score, .score")
                        if score_el:
                            spans = score_el.select("span")
                            nums = []
                            for sp in spans:
                                txt = sp.get_text(strip=True).replace("-", "").strip()
                                if txt.isdigit():
                                    nums.append(int(txt))
                            if len(nums) >= 2:
                                score1, score2 = nums[0], nums[1]

                        # Турнир
                        event_el = item.select_one(".event-name, .matchEventName")
                        tournament = event_el.get_text(strip=True) if event_el else None

                        # Формат (Bo3, Bo1 и т.д.)
                        meta_el = item.select_one(".map-text, .matchMeta, .bestof")
                        match_format = meta_el.get_text(strip=True) if meta_el else None

                        # URL матча
                        href = item.get("href", "")
                        match_url = HLTV_BASE + href if href else None

                        all_matches.append({
                            "team1": team1,
                            "team2": team2,
                            "score1": score1,
                            "score2": score2,
                            "tournament": tournament,
                            "match_format": match_format,
                            "scheduled_at": current_date,
                            "match_url": match_url,
                        })
                        page_count += 1
                    except Exception as ex:
                        logger.debug("HLTV result item parse error: %s", ex)
                        continue

            logger.info("HLTV results page %d: parsed %d matches", page_num, page_count)
            if page_count == 0:
                logger.warning("HLTV results page %d: 0 matches, stopping", page_num)
                break
            await asyncio.sleep(random.uniform(2, 4))

        logger.info("HLTV results total: %d matches", len(all_matches))
        return all_matches

    async def fetch_team_rankings(self) -> list[dict]:
        """Парсим рейтинг команд CS2."""
        html = await self._get_html(f"{HLTV_BASE}/ranking/teams", ".ranking")
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        teams = []

        for item in soup.select(".ranked-team"):
            try:
                rank_el = item.select_one(".ranking-number")
                name_el = item.select_one(".name")
                points_el = item.select_one(".points")

                if not name_el:
                    continue

                rank = int(rank_el.get_text(strip=True)) if rank_el else None
                name = name_el.get_text(strip=True)
                points_text = points_el.get_text(strip=True) if points_el else "0"
                points = int("".join(filter(str.isdigit, points_text)) or 0)

                teams.append({"rank": rank, "name": name, "points": points})
            except Exception as e:
                logger.warning("HLTV team parse error: %s", e)
                continue

        logger.info("HLTV: parsed %d teams", len(teams))
        return teams

    # --- Сохранение в БД ---

    async def save_upcoming_matches(self, db: AsyncSession) -> int:
        matches_data = await self.fetch_upcoming_matches()
        count = 0
        for m in matches_data:
            # Проверяем дубликат по именам команд и времени
            result = await db.execute(
                select(Match).where(
                    Match.team1_name == m["team1"],
                    Match.team2_name == m["team2"],
                    Match.source == "hltv",
                    Match.scheduled_at == m["scheduled_at"],
                )
            )
            if result.scalar_one_or_none():
                continue

            match = Match(
                source="hltv",
                game="cs2",
                team1_name=m["team1"],
                team2_name=m["team2"],
                tournament=m["tournament"],
                match_format=m["match_format"],
                scheduled_at=m["scheduled_at"],
                match_url=m["match_url"],
                status="upcoming",
            )
            db.add(match)
            count += 1

        await db.commit()
        logger.info("HLTV: saved %d upcoming matches", count)
        return count

    async def save_team_rankings(self, db: AsyncSession) -> int:
        teams_data = await self.fetch_team_rankings()
        count = 0
        for t in teams_data:
            name = t["name"]
            normalized = normalize_team_name(name)

            result = await db.execute(
                select(Team).where(Team.normalized_name == normalized, Team.source == "hltv")
            )
            team = result.scalar_one_or_none()

            if team is None:
                team = Team(
                    source="hltv",
                    game="cs2",
                    name=name,
                    normalized_name=normalized,
                    rating=float(t["points"]),
                )
                db.add(team)
            else:
                team.rating = float(t["points"])
                team.updated_at = datetime.utcnow()

            count += 1

        await db.commit()
        logger.info("HLTV: saved %d teams", count)
        return count


    async def save_match_results(self, db: AsyncSession, pages: int = 10) -> int:
        """Сохранить результаты завершённых матчей CS2 с HLTV."""
        matches_data = await self.fetch_match_results(pages=pages)
        count = 0
        for m in matches_data:
            team1 = m["team1"]
            team2 = m["team2"]
            scheduled_at = m.get("scheduled_at")

            # Дедупликация по командам + времени + источнику
            result = await db.execute(
                select(Match).where(
                    Match.source == "hltv",
                    Match.status == "finished",
                    Match.team1_name == team1,
                    Match.team2_name == team2,
                    Match.scheduled_at == scheduled_at,
                )
            )
            if result.scalar_one_or_none():
                continue

            s1 = m.get("score1")
            s2 = m.get("score2")

            match = Match(
                source="hltv",
                game="cs2",
                team1_name=team1,
                team2_name=team2,
                tournament=m.get("tournament"),
                match_format=m.get("match_format"),
                scheduled_at=scheduled_at,
                match_url=m.get("match_url"),
                status="finished",
                score_team1=s1,
                score_team2=s2,
            )
            db.add(match)
            count += 1

        await db.commit()
        logger.info("HLTV: saved %d finished match results", count)
        return count


async def run_hltv_sync(db: AsyncSession) -> None:
    """Точка входа для планировщика (быстрый — только upcoming + rankings)."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            collector = HLTVCollector(browser)
            await collector.save_upcoming_matches(db)
            await collector.save_team_rankings(db)
            logger.info("HLTV sync complete")
        finally:
            await browser.close()


async def run_hltv_history_sync(db: AsyncSession, pages: int = 10) -> None:
    """Сбор исторических результатов CS2 с HLTV (запускается раз в день)."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            collector = HLTVCollector(browser)
            await collector.save_match_results(db, pages=pages)
            logger.info("HLTV history sync complete")
        finally:
            await browser.close()
