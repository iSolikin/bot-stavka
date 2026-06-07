"""
Коэффициенты с The Odds API (https://the-odds-api.com).
Бесплатный тариф: 500 запросов в месяц.
"""
import logging
import time
import aiohttp
from config import config

logger = logging.getLogger(__name__)

SPORT_MAP = {
    "cs2": "esports_cs2",
    "dota2": "esports_dota2",
}

# Кэш кэфов по игре, чтобы не дёргать API на каждый матч.
# {game: (timestamp, [odds...])}; TTL 10 минут.
_ODDS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_ODDS_TTL = 600.0


class OddsCollector:
    def __init__(self, http: aiohttp.ClientSession):
        self.http = http
        self.key = config.ODDS_API_KEY

    async def get_odds(self, game: str) -> list[dict]:
        """Возвращает список {team1, team2, odds1, odds2, bookmaker}."""
        if not self.key:
            return []

        sport = SPORT_MAP.get(game)
        if not sport:
            return []

        url = f"{config.ODDS_API_BASE}/sports/{sport}/odds/"
        params = {
            "apiKey": self.key,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
        }
        try:
            async with self.http.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    return self._parse(data)
                logger.warning("Odds API %s -> HTTP %s", sport, r.status)
                return []
        except Exception as e:
            logger.error("Odds API error: %s", e)
            return []

    def _parse(self, data: list) -> list[dict]:
        results = []
        for event in data:
            teams = event.get("home_team"), event.get("away_team")
            if not all(teams):
                continue
            bookmakers = event.get("bookmakers", [])
            if not bookmakers:
                continue
            # Берём первого доступного букмекера
            for bk in bookmakers:
                markets = bk.get("markets", [])
                h2h = next((m for m in markets if m["key"] == "h2h"), None)
                if not h2h:
                    continue
                outcomes = {o["name"]: o["price"] for o in h2h.get("outcomes", [])}
                o1 = outcomes.get(teams[0])
                o2 = outcomes.get(teams[1])
                if o1 and o2:
                    results.append({
                        "team1": teams[0],
                        "team2": teams[1],
                        "odds1": o1,
                        "odds2": o2,
                        "bookmaker": bk.get("title", ""),
                    })
                    break

        return results

    def find_odds(self, team1: str, team2: str, odds_list: list[dict]) -> tuple[float | None, float | None]:
        """Найти кэфы для конкретного матча по названиям команд."""
        t1 = team1.lower()
        t2 = team2.lower()
        for o in odds_list:
            o1 = o["team1"].lower()
            o2 = o["team2"].lower()
            if (t1 in o1 or o1 in t1) and (t2 in o2 or o2 in t2):
                return o["odds1"], o["odds2"]
            if (t2 in o1 or o1 in t2) and (t1 in o2 or o2 in t1):
                return o["odds2"], o["odds1"]
        return None, None


async def get_odds_for_game(game: str) -> list[dict]:
    """Получить кэфы. Приоритет OddsPapi (киберспорт), фолбэк — The Odds API.
    Результат кэшируется на 10 минут (чтобы не дёргать API на каждый матч)."""
    # Кэш
    cached = _ODDS_CACHE.get(game)
    if cached and (time.time() - cached[0]) < _ODDS_TTL:
        return cached[1]

    odds: list[dict] = []

    # 1) OddsPapi — основной источник для киберспорта
    if config.ODDSPAPI_API_KEY:
        try:
            from collectors.oddspapi import get_odds_for_game as oddspapi_get
            odds = await oddspapi_get(game)
        except Exception as e:
            logger.warning("OddsPapi failed, fallback to Odds API: %s", e)

    # 2) The Odds API (не покрывает киберспорт, но оставлен как фолбэк)
    if not odds and config.ODDS_API_KEY:
        async with aiohttp.ClientSession() as http:
            collector = OddsCollector(http)
            odds = await collector.get_odds(game)

    _ODDS_CACHE[game] = (time.time(), odds)
    return odds
