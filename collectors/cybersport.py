"""
Сборщик CS2 статистики с Cybersport.ru.
Источник: https://www.cybersport.ru/

Собирает:
- Valve рейтинги команд
- HLTV рейтинги
- Детальную информацию о командах
- Составы команд
- Историю матчей
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CYBERSPORT_BASE = "https://www.cybersport.ru"


class CybersportCollector:
    """Сборщик CS2 данных с Cybersport.ru."""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }

    async def _get_html(self, url: str) -> str | None:
        """Получить HTML страницы."""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            async with self.session.get(url, headers=self.headers, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    logger.warning(f"Cybersport returned {resp.status} for {url}")
                    return None
        except Exception as e:
            logger.error(f"Cybersport fetch error {url}: {e}")
            return None

    async def close(self):
        """Закрыть сессию."""
        if self.session:
            await self.session.close()

    async def fetch_hltv_rankings(self) -> list[dict]:
        """Получить HLTV рейтинги команд с Cybersport."""
        url = f"{CYBERSPORT_BASE}/rankings?discipline=cs2&ranking=hltv"
        html = await self._get_html(url)
        if not html:
            return []

        teams = []
        try:
            soup = BeautifulSoup(html, "lxml")

            # Ищем таблицу с рейтингами
            table = soup.select_one("table")
            if not table:
                # Альтернативный селектор для других версий верстки
                rows = soup.select("[data-team-id], .rating-row, tr[data-team]")
            else:
                rows = table.select("tbody tr")

            for idx, row in enumerate(rows[:30], 1):  # Top 30
                try:
                    # Извлекаем данные из строки
                    rank = idx

                    # Ищем название команды
                    team_link = row.select_one("a[href*='/teams/']")
                    team_name = team_link.get_text(strip=True) if team_link else None

                    if not team_name or team_name == "TBD":
                        continue

                    # Рейтинг (обычно в последней колонке)
                    cells = row.select("td")
                    rating = None
                    points = None

                    if len(cells) >= 2:
                        # Попробуем найти рейтинг в разных позициях
                        for cell in cells[-3:]:
                            text = cell.get_text(strip=True)
                            try:
                                if "." in text:
                                    rating = float(text)
                                    break
                                elif text.isdigit() and not points:
                                    points = int(text)
                            except ValueError:
                                pass

                    teams.append({
                        "rank": rank,
                        "name": team_name,
                        "hltv_rating": rating,
                        "points": points,
                        "source": "cybersport_hltv",
                    })
                except Exception as e:
                    logger.debug(f"Cybersport HLTV ranking parse error: {e}")
                    continue

            logger.info(f"Cybersport: fetched {len(teams)} HLTV rankings")
        except Exception as e:
            logger.error(f"Cybersport HLTV rankings parse error: {e}")

        return teams

    async def fetch_valve_rankings(self) -> list[dict]:
        """Получить Valve рейтинги команд с Cybersport."""
        url = f"{CYBERSPORT_BASE}/rankings?discipline=cs2&ranking=valve"
        html = await self._get_html(url)
        if not html:
            return []

        teams = []
        try:
            soup = BeautifulSoup(html, "lxml")

            # Ищем таблицу с рейтингами
            table = soup.select_one("table")
            if not table:
                rows = soup.select("[data-team-id], .rating-row, tr[data-team]")
            else:
                rows = table.select("tbody tr")

            for idx, row in enumerate(rows[:30], 1):  # Top 30
                try:
                    rank = idx

                    # Название команды
                    team_link = row.select_one("a[href*='/teams/']")
                    team_name = team_link.get_text(strip=True) if team_link else None

                    if not team_name or team_name == "TBD":
                        continue

                    # Рейтинг Valve
                    cells = row.select("td")
                    rating = None
                    points = None

                    if len(cells) >= 2:
                        for cell in cells[-3:]:
                            text = cell.get_text(strip=True)
                            try:
                                if "." in text:
                                    rating = float(text)
                                    break
                                elif text.isdigit() and not points:
                                    points = int(text)
                            except ValueError:
                                pass

                    teams.append({
                        "rank": rank,
                        "name": team_name,
                        "valve_rating": rating,
                        "points": points,
                        "source": "cybersport_valve",
                    })
                except Exception as e:
                    logger.debug(f"Cybersport Valve ranking parse error: {e}")
                    continue

            logger.info(f"Cybersport: fetched {len(teams)} Valve rankings")
        except Exception as e:
            logger.error(f"Cybersport Valve rankings parse error: {e}")

        return teams

    async def fetch_team_details(self, team_name: str) -> dict | None:
        """Получить подробную информацию о команде."""
        # Нормализуем название для URL
        team_slug = team_name.lower().replace(" ", "-")
        url = f"{CYBERSPORT_BASE}/teams/{team_slug}"

        html = await self._get_html(url)
        if not html:
            return None

        try:
            soup = BeautifulSoup(html, "lxml")

            team_info = {
                "name": team_name,
                "source": "cybersport",
            }

            # Ищем различные данные на странице команды
            # Состав команды
            players = []
            player_elements = soup.select(".player-row, [data-player-id], .team-player")
            for player_el in player_elements[:5]:  # Top 5 игроков
                try:
                    player_name = player_el.select_one(".player-name, a")
                    if player_name:
                        players.append(player_name.get_text(strip=True))
                except Exception as e:
                    logger.debug(f"Player parse error: {e}")

            if players:
                team_info["players"] = players

            # История матчей (последние игры)
            matches = []
            match_elements = soup.select(".match-row, tr[data-match-id], .game-result")
            for match_el in match_elements[:10]:  # Последние 10 матчей
                try:
                    # Парсим результат матча
                    result_text = match_el.get_text(strip=True)
                    if result_text:
                        matches.append(result_text)
                except Exception as e:
                    logger.debug(f"Match parse error: {e}")

            if matches:
                team_info["recent_matches"] = matches

            # Страна команды
            country_el = soup.select_one("[data-country], .country, .flag")
            if country_el:
                team_info["country"] = country_el.get_text(strip=True)

            return team_info
        except Exception as e:
            logger.error(f"Cybersport team details parse error for {team_name}: {e}")
            return None

    async def fetch_all_teams(self) -> list[dict]:
        """Получить список всех команд CS2."""
        url = f"{CYBERSPORT_BASE}/teams/cs2"
        html = await self._get_html(url)
        if not html:
            return []

        teams = []
        try:
            soup = BeautifulSoup(html, "lxml")

            # Ищем карточки команд
            team_cards = soup.select(".team-card, [data-team-id], .team-item")

            for card in team_cards[:100]:  # Первые 100 команд
                try:
                    # Название команды
                    team_link = card.select_one("a[href*='/teams/']")
                    team_name = team_link.get_text(strip=True) if team_link else None

                    if not team_name:
                        continue

                    # Регион/страна
                    region = card.select_one(".region, .country")
                    region_text = region.get_text(strip=True) if region else None

                    # Количество побед
                    stats = card.select_one(".wins, .matches-won")
                    wins = stats.get_text(strip=True) if stats else None

                    teams.append({
                        "name": team_name,
                        "region": region_text,
                        "wins": wins,
                        "source": "cybersport",
                    })
                except Exception as e:
                    logger.debug(f"Team card parse error: {e}")
                    continue

            logger.info(f"Cybersport: fetched {len(teams)} teams")
        except Exception as e:
            logger.error(f"Cybersport teams list parse error: {e}")

        return teams


async def collect_cs2_stats(db: AsyncSession):
    """Главная функция сбора CS2 статистики с Cybersport."""
    collector = CybersportCollector()

    try:
        # Собираем разные типы данных
        hltv_rankings = await collector.fetch_hltv_rankings()
        valve_rankings = await collector.fetch_valve_rankings()
        all_teams = await collector.fetch_all_teams()

        logger.info(
            f"Cybersport stats collected: {len(hltv_rankings)} HLTV, "
            f"{len(valve_rankings)} Valve, {len(all_teams)} teams"
        )

        return {
            "hltv_rankings": hltv_rankings,
            "valve_rankings": valve_rankings,
            "teams": all_teams,
        }

    finally:
        await collector.close()
