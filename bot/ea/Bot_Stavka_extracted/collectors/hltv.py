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

logger = logging.getLogger(__name__)

HLTV_BASE = "https://www.hltv.org"

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
            normalized = name.lower().strip()

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


async def run_hltv_sync(db: AsyncSession) -> None:
    """Точка входа для планировщика."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            collector = HLTVCollector(browser)
            await collector.save_upcoming_matches(db)
            await collector.save_team_rankings(db)
            logger.info("HLTV sync complete")
        finally:
            await browser.close()
