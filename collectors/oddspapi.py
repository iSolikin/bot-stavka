"""
Коллектор кэфов с OddsPapi (https://oddspapi.io).
Бесплатный тариф: кэфы по киберспорту от 350+ контор (вкл. Pinnacle).

Возвращает тот же формат что и collectors/odds.py:
    [{team1, team2, odds1, odds2, bookmaker}]

ВАЖНО: точная структура ответа уточняется по факту первого реального ответа
(см. probe_oddspapi()). Парсинг написан защитно — пробует несколько вариантов
имён полей.
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp

from config import config

logger = logging.getLogger(__name__)

# sportId в OddsPapi
SPORT_IDS = {
    "dota2": 16,
    "cs2": 17,
}

# Предпочитаемые конторы (Pinnacle = шарп, эталон честной цены)
PREFERRED_BOOKMAKERS = ["pinnacle", "bet365", "1xbet", "betano", "ggbet"]


def _f(d: dict, *names):
    """Достать первое непустое поле из возможных вариантов имени."""
    for n in names:
        if n in d and d[n] not in (None, "", 0):
            return d[n]
    return None


async def _get(http: aiohttp.ClientSession, path: str, params: dict) -> object:
    url = f"{config.ODDSPAPI_BASE}{path}"
    p = {"apiKey": config.ODDSPAPI_API_KEY, **params}
    try:
        async with http.get(url, params=p, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                logger.warning("OddsPapi %s -> HTTP %s", path, r.status)
                return None
            return await r.json()
    except Exception as e:
        logger.error("OddsPapi %s error: %s", path, e)
        return None


def _pick_h2h_odds(odds_payload: object) -> tuple[float | None, float | None, str]:
    """Из ответа /odds вытащить пару кэфов H2H (1X2 без ничьей) от лучшей конторы."""
    # Ожидаем список котировок по конторам и рынкам. Структура уточняется probe-ом.
    if not isinstance(odds_payload, (list, dict)):
        return None, None, ""

    rows = odds_payload if isinstance(odds_payload, list) else odds_payload.get("data") or odds_payload.get("odds") or []
    if not isinstance(rows, list):
        return None, None, ""

    # Сгруппируем по конторе: ищем рынок "match winner" / "h2h" / "moneyline"
    by_book: dict[str, tuple[float, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        market = str(_f(row, "market", "market_name", "marketType", "key") or "").lower()
        if market and not any(k in market for k in ("h2h", "moneyline", "match", "winner", "1x2", "ml")):
            continue
        book = str(_f(row, "bookmaker", "bookmaker_name", "book", "bookie") or "").lower()
        o1 = _f(row, "odds1", "home", "price1", "team1_odds", "outcome1")
        o2 = _f(row, "odds2", "away", "price2", "team2_odds", "outcome2")
        if book and o1 and o2:
            try:
                by_book[book] = (float(o1), float(o2))
            except (TypeError, ValueError):
                continue

    if not by_book:
        return None, None, ""

    for pref in PREFERRED_BOOKMAKERS:
        if pref in by_book:
            o1, o2 = by_book[pref]
            return o1, o2, pref
    # иначе любая контора
    book, (o1, o2) = next(iter(by_book.items()))
    return o1, o2, book


async def get_odds(http: aiohttp.ClientSession, game: str) -> list[dict]:
    """Список матчей с кэфами H2H для игры."""
    if not config.ODDSPAPI_API_KEY:
        return []
    sport_id = SPORT_IDS.get(game)
    if not sport_id:
        return []

    fixtures = await _get(http, "/fixtures", {"sportId": sport_id, "hasOdds": "true"})
    rows = fixtures if isinstance(fixtures, list) else (fixtures or {}).get("data") or []
    if not isinstance(rows, list):
        return []

    results = []
    for fx in rows:
        if not isinstance(fx, dict):
            continue
        team1 = _f(fx, "team1", "home", "home_team", "homeTeam", "team_home", "participant1")
        team2 = _f(fx, "team2", "away", "away_team", "awayTeam", "team_away", "participant2")
        fixture_id = _f(fx, "id", "fixtureId", "fixture_id", "matchId", "match_id")
        if not team1 or not team2:
            continue

        # Кэфы могут быть встроены в fixture, либо тянутся отдельным запросом
        o1, o2, book = _pick_h2h_odds(fx.get("odds") or fx.get("markets") or [])
        if (not o1 or not o2) and fixture_id:
            await asyncio.sleep(0.3)
            odds_payload = await _get(http, "/odds", {"fixtureId": fixture_id})
            o1, o2, book = _pick_h2h_odds(odds_payload)

        if o1 and o2:
            results.append({
                "team1": str(team1), "team2": str(team2),
                "odds1": o1, "odds2": o2, "bookmaker": book or "oddspapi",
            })

    logger.info("OddsPapi %s: %d matches with odds", game, len(results))
    return results


async def get_odds_for_game(game: str) -> list[dict]:
    """Точка входа (создаёт свою HTTP-сессию)."""
    if not config.ODDSPAPI_API_KEY:
        return []
    async with aiohttp.ClientSession() as http:
        return await get_odds(http, game)


# ---- Отладка: посмотреть реальную структуру ответа ----
async def probe_oddspapi() -> None:
    """Распечатать сырые ответы /sports, /fixtures, /odds для калибровки парсинга."""
    import json
    async with aiohttp.ClientSession() as http:
        sports = await _get(http, "/sports", {})
        print("=== /sports (esports?) ===")
        if isinstance(sports, list):
            for s in sports:
                blob = json.dumps(s, ensure_ascii=False).lower()
                if any(k in blob for k in ("dota", "cs2", "csgo", "counter", "esport", "league")):
                    print(" ", s)
        else:
            print(" ", str(sports)[:300])

        fx = await _get(http, "/fixtures", {"sportId": 16, "hasOdds": "true"})
        rows = fx if isinstance(fx, list) else (fx or {}).get("data") or []
        print(f"\n=== /fixtures dota2: {len(rows) if isinstance(rows,list) else '?'} ===")
        if isinstance(rows, list) and rows:
            print("Пример fixture (ключи):", list(rows[0].keys()))
            print(json.dumps(rows[0], ensure_ascii=False)[:600])
            fid = _f(rows[0], "id", "fixtureId", "fixture_id", "matchId", "match_id")
            if fid:
                odds = await _get(http, "/odds", {"fixtureId": fid})
                print(f"\n=== /odds fixture {fid} ===")
                print(json.dumps(odds, ensure_ascii=False)[:800])


if __name__ == "__main__":
    asyncio.run(probe_oddspapi())
