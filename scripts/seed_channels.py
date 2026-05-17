"""
Скрипт для первоначального заполнения БД Telegram-каналами.
Запуск: python scripts/seed_channels.py

Каналы разбиты на категории:
  news   — новостные медиа (киберспорт, esports)
  bets   — каналы с прогнозами/аналитикой ставок
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db, AsyncSessionLocal
from db.models import TelegramChannel
from sqlalchemy import select

# -------------------------------------------------------------------
# НОВОСТНЫЕ КАНАЛЫ (проверенные, активные)
# -------------------------------------------------------------------
NEWS_CHANNELS = [
    # Русскоязычные новости
    {"username": "cybersport_ru",       "game": None,    "note": "Киберспорт.ру — главный RU esports портал"},
    {"username": "esforce",             "game": None,    "note": "ESforce media (VP, RuHub, Twitch RU)"},
    {"username": "gg_esports",          "game": None,    "note": "GG.ru — новости киберспорта"},
    {"username": "esports_ru",          "game": None,    "note": "Esports.ru новости"},
    {"username": "ruhub",               "game": None,    "note": "RuHub — русский esports стрим-хаб"},
    {"username": "liquipediabot",       "game": None,    "note": "Liquipedia уведомления"},

    # CS2 новости
    {"username": "cs2_news",            "game": "cs2",   "note": "CS2 официальные новости агрегатор"},
    {"username": "hltv_cs",             "game": "cs2",   "note": "HLTV CS2 новости"},
    {"username": "cs2ru",               "game": "cs2",   "note": "CS2 RU комьюнити"},
    {"username": "csgo2news",           "game": "cs2",   "note": "CS2 новости и обновления"},

    # Dota2 новости
    {"username": "dota2_ru",            "game": "dota2", "note": "Dota2 RU официальный"},
    {"username": "dota2news",           "game": "dota2", "note": "Dota2 новости агрегатор"},
    {"username": "dota2_updates",       "game": "dota2", "note": "Обновления и патчи Dota2"},
    {"username": "dotacinema_ru",       "game": "dota2", "note": "DotaCinema RU"},

    # Команды (аналитика через их официальные каналы)
    {"username": "natusvincere",        "game": None,    "note": "Natus Vincere official"},
    {"username": "virtuspro",           "game": None,    "note": "Virtus.pro official"},
    {"username": "teamspirit_gg",       "game": None,    "note": "Team Spirit official"},
    {"username": "Cloud9",              "game": None,    "note": "Cloud9 official"},
]

# -------------------------------------------------------------------
# АНАЛИТИКА / ПРОГНОЗЫ (каналы с разбором матчей — не реклама БК)
# -------------------------------------------------------------------
ANALYTICS_CHANNELS = [
    # CS2 аналитика
    {"username": "cs2_analytics",       "game": "cs2",   "note": "Разбор матчей CS2"},
    {"username": "csgo_prognoz",        "game": "cs2",   "note": "Прогнозы CS2 (аналитика)"},
    {"username": "cs2_picks",           "game": "cs2",   "note": "Пики и баны CS2"},
    {"username": "cs2_stats",           "game": "cs2",   "note": "Статистика CS2"},

    # Dota2 аналитика
    {"username": "dota2_prognozy",      "game": "dota2", "note": "Прогнозы Dota2 (аналитика)"},
    {"username": "dota2_bets_ana",      "game": "dota2", "note": "Dota2 аналитика матчей"},
    {"username": "dota2_picks",         "game": "dota2", "note": "Драфт и пики Dota2"},
    {"username": "epicenter_dota",      "game": "dota2", "note": "Epicenter аналитика"},

    # Общий киберспорт
    {"username": "esports_analysis",    "game": None,    "note": "Общая аналитика esports"},
    {"username": "esports_bets_ru",     "game": None,    "note": "Аналитика esports матчей"},
]


async def seed_channels() -> None:
    await init_db()

    all_channels = [
        *[{**c, "category": "news"} for c in NEWS_CHANNELS],
        *[{**c, "category": "analytics"} for c in ANALYTICS_CHANNELS],
    ]

    async with AsyncSessionLocal() as db:
        added = 0
        skipped = 0

        for ch in all_channels:
            username = ch["username"].lstrip("@").lower()

            # Проверяем дубликат
            existing = await db.execute(
                select(TelegramChannel).where(TelegramChannel.username == username)
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue

            channel = TelegramChannel(
                username=username,
                game=ch.get("game"),
                is_active=True,
            )
            db.add(channel)
            added += 1
            print(f"  + Added: @{username} [{ch.get('category')}] {ch.get('note', '')}")

        await db.commit()
        print(f"\nDone: {added} added, {skipped} already existed")


if __name__ == "__main__":
    asyncio.run(seed_channels())
