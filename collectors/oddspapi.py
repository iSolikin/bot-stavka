"""
Коллектор кэфов с OddsPapi (https://oddspapi.io).
Бесплатный тариф: кэфы по киберспорту от 350+ контор (вкл. Pinnacle).

Структура API (v4):
  GET /fixtures?sportId=16&from=YYYY-MM-DD&to=YYYY-MM-DD
      -> [{fixtureId, participant1Name, participant2Name, hasOdds, startTime, ...}]
      (from/to обязательны, диапазон < 10 дней)
  GET /odds?fixtureId=ID
      -> {bookmakerOdds: {<book>: {markets: {"<marketId>": {outcomes:
            {"<outcomeId>": {players: {"0": {price, active, ...}}}}}}}}}

Рынок «победитель матча» (moneyline, 2 исхода):
  Dota2: marketId 161  (исход 161=команда1, 162=команда2)
  CS2:   marketId 171  (исход 171=команда1, 172=команда2)

Возвращает стандартный формат: [{team1, team2, odds1, odds2, bookmaker}]
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp

from config import config

logger = logging.getLogger(__name__)

SPORT_IDS = {"dota2": 16, "cs2": 17}

# marketId рынка «Winner» (moneyline) по игре; исход команды1 = marketId, команды2 = marketId+1
WINNER_MARKET = {"dota2": 161, "cs2": 171}

# Предпочитаемые конторы (Pinnacle = шарп, эталон честной цены)
PREFERRED_BOOKMAKERS = ["pinnacle", "bet365", "betano", "marathonbet", "1xbet", "bwin", "ggbet"]

# Ограничения: пауза между запросами (рейт-лимит ~2с) и макс. матчей за синк
_REQUEST_DELAY = 2.2
_MAX_FIXTURES = 30


async def _get(http: aiohttp.ClientSession, path: str, params: dict) -> object | None:
    url = f"{config.ODDSPAPI_BASE}{path}"
    p = {"apiKey": config.ODDSPAPI_API_KEY, **params}
    try:
        async with http.get(url, params=p, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 429:
                await asyncio.sleep(_REQUEST_DELAY)
                return None
            if r.status != 200:
                logger.warning("OddsPapi %s -> HTTP %s", path, r.status)
                return None
            return await r.json()
    except Exception as e:
        logger.error("OddsPapi %s error: %s", path, e)
        return None


def _extract_winner_odds(payload: dict, game: str) -> tuple[float | None, float | None, str]:
    """Вытащить пару кэфов на победителя матча от лучшей доступной конторы."""
    if not isinstance(payload, dict):
        return None, None, ""
    books = payload.get("bookmakerOdds")
    if not isinstance(books, dict):
        return None, None, ""

    market_id = str(WINNER_MARKET[game])
    out1_id = str(WINNER_MARKET[game])          # исход команды 1
    out2_id = str(WINNER_MARKET[game] + 1)      # исход команды 2

    def price(book_data: dict, outcome_id: str) -> float | None:
        try:
            market = book_data["markets"][market_id]
            if market.get("marketActive") is False or book_data.get("suspended"):
                return None
            players = market["outcomes"][outcome_id]["players"]
            cell = players.get("0") or next(iter(players.values()))
            if cell.get("active") is False:
                return None
            return float(cell["price"])
        except (KeyError, TypeError, ValueError, StopIteration):
            return None

    found: dict[str, tuple[float, float]] = {}
    for book, bdata in books.items():
        if not isinstance(bdata, dict):
            continue
        o1 = price(bdata, out1_id)
        o2 = price(bdata, out2_id)
        if o1 and o2 and o1 > 1.0 and o2 > 1.0:
            found[book.lower()] = (o1, o2)

    if not found:
        return None, None, ""
    for pref in PREFERRED_BOOKMAKERS:
        if pref in found:
            return found[pref][0], found[pref][1], pref
    book, (o1, o2) = next(iter(found.items()))
    return o1, o2, book


async def get_odds(http: aiohttp.ClientSession, game: str) -> list[dict]:
    """Список матчей с кэфами H2H на победителя для игры."""
    if not config.ODDSPAPI_API_KEY:
        return []
    sport_id = SPORT_IDS.get(game)
    if not sport_id or game not in WINNER_MARKET:
        return []

    today = datetime.utcnow().date()
    params = {
        "sportId": sport_id,
        "from": today.isoformat(),
        "to": (today + timedelta(days=9)).isoformat(),
    }
    fixtures = await _get(http, "/fixtures", params)
    if not isinstance(fixtures, list):
        return []

    with_odds = [f for f in fixtures if isinstance(f, dict) and f.get("hasOdds")][:_MAX_FIXTURES]

    results = []
    for fx in with_odds:
        team1 = fx.get("participant1Name")
        team2 = fx.get("participant2Name")
        fid = fx.get("fixtureId")
        if not team1 or not team2 or not fid:
            continue

        await asyncio.sleep(_REQUEST_DELAY)
        payload = await _get(http, "/odds", {"fixtureId": fid})
        if not isinstance(payload, dict):
            continue
        o1, o2, book = _extract_winner_odds(payload, game)
        if o1 and o2:
            results.append({
                "team1": str(team1), "team2": str(team2),
                "odds1": o1, "odds2": o2, "bookmaker": book or "oddspapi",
            })

    logger.info("OddsPapi %s: %d matches with winner odds", game, len(results))
    return results


async def get_odds_for_game(game: str) -> list[dict]:
    """Точка входа (создаёт свою HTTP-сессию)."""
    if not config.ODDSPAPI_API_KEY:
        return []
    async with aiohttp.ClientSession() as http:
        return await get_odds(http, game)


if __name__ == "__main__":
    async def _demo():
        for g in ("dota2", "cs2"):
            odds = await get_odds_for_game(g)
            print(f"\n=== {g}: {len(odds)} матчей с кэфами ===")
            for o in odds[:8]:
                print(f"  {o['team1']} ({o['odds1']}) vs {o['team2']} ({o['odds2']}) | {o['bookmaker']}")
    asyncio.run(_demo())
