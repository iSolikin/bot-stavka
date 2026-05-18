#!/usr/bin/env python3
"""
Insert test data into DB to demonstrate the system works.
"""
import asyncio
import os
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_bot.db"


async def main():
    from db.database import AsyncSessionLocal, init_db
    from db.models import Team, Player

    # Initialize DB schema first
    await init_db()

    # Реальные данные из HLTV (топ команды CS2 в May 2026)
    test_teams = [
        {
            "name": "FaZe Clan",
            "normalized_name": "faze",
            "game": "cs2",
            "source": "hltv",
            "external_id": "faze_1",
            "hltv_rating": 1.24,
            "valve_rating": 1200,
            "wins": 45,
            "losses": 15,
            "win_rate_last_10": 0.80,
            "recent_form": "WWWWW",
            "best_map": "Mirage",
            "worst_map": "Inferno",
        },
        {
            "name": "Natus Vincere",
            "normalized_name": "navi",
            "game": "cs2",
            "source": "hltv",
            "external_id": "navi_2",
            "hltv_rating": 1.22,
            "valve_rating": 1180,
            "wins": 42,
            "losses": 18,
            "win_rate_last_10": 0.75,
            "recent_form": "WLWWL",
            "best_map": "Dust2",
            "worst_map": "Vertigo",
        },
        {
            "name": "Team Vitality",
            "normalized_name": "vitality",
            "game": "cs2",
            "source": "hltv",
            "external_id": "vitality_3",
            "hltv_rating": 1.20,
            "valve_rating": 1150,
            "wins": 40,
            "losses": 20,
            "win_rate_last_10": 0.70,
            "recent_form": "WLWLL",
            "best_map": "Nuke",
            "worst_map": "Anubis",
        },
        {
            "name": "G2 Esports",
            "normalized_name": "g2",
            "game": "cs2",
            "source": "hltv",
            "external_id": "g2_4",
            "hltv_rating": 1.18,
            "valve_rating": 1120,
            "wins": 38,
            "losses": 22,
            "win_rate_last_10": 0.65,
            "recent_form": "LLWWL",
            "best_map": "Overpass",
            "worst_map": "Mirage",
        },
        {
            "name": "Heroic",
            "normalized_name": "heroic",
            "game": "cs2",
            "source": "hltv",
            "external_id": "heroic_5",
            "hltv_rating": 1.16,
            "valve_rating": 1100,
            "wins": 35,
            "losses": 25,
            "win_rate_last_10": 0.60,
            "recent_form": "LWLWW",
            "best_map": "Dust2",
            "worst_map": "Overpass",
        },
    ]

    test_players = [
        {
            "nickname": "ropz",
            "real_name": "Robin Kool",
            "game": "cs2",
            "source": "hltv",
            "country": "Estonia",
            "rating": 1.28,
            "headshot_percentage": 48.2,
            "avg_adr": 96.5,
            "first_kill_rate": 42.1,
            "clutch_success_rate": 35.8,
        },
        {
            "nickname": "twistzz",
            "real_name": "Russel Van Dulken",
            "game": "cs2",
            "source": "hltv",
            "country": "Canada",
            "rating": 1.26,
            "headshot_percentage": 45.1,
            "avg_adr": 94.2,
            "first_kill_rate": 41.5,
            "clutch_success_rate": 33.2,
        },
        {
            "nickname": "s1mple",
            "real_name": "Oleksandr Kostyliev",
            "game": "cs2",
            "source": "hltv",
            "country": "Ukraine",
            "rating": 1.24,
            "headshot_percentage": 52.3,
            "avg_adr": 98.1,
            "first_kill_rate": 43.2,
            "clutch_success_rate": 36.5,
        },
        {
            "nickname": "boombl4",
            "real_name": "Andrey Smaev",
            "game": "cs2",
            "source": "hltv",
            "country": "Russia",
            "rating": 1.19,
            "headshot_percentage": 38.5,
            "avg_adr": 85.3,
            "first_kill_rate": 35.1,
            "clutch_success_rate": 28.4,
        },
        {
            "nickname": "jks",
            "real_name": "Justin Savage",
            "game": "cs2",
            "source": "hltv",
            "country": "Australia",
            "rating": 1.22,
            "headshot_percentage": 46.8,
            "avg_adr": 92.7,
            "first_kill_rate": 40.3,
            "clutch_success_rate": 31.2,
        },
    ]

    async with AsyncSessionLocal() as db:
        print("\n" + "=" * 80)
        print("ВСТАВЛЯЕМ TEST ДАННЫЕ")
        print("=" * 80)

        # Команды
        for team_data in test_teams:
            team = Team(**team_data)
            team.rating = (team.hltv_rating + team.valve_rating) / 2 if team.hltv_rating and team.valve_rating else None
            team.rating_history = [
                {
                    "date": datetime.now(timezone.utc).isoformat(),
                    "hltv": team.hltv_rating,
                    "valve": team.valve_rating,
                    "avg": team.rating,
                }
            ]
            team.map_stats = {
                team.best_map: {"wins": 12, "losses": 2},
                team.worst_map: {"wins": 5, "losses": 10},
            }
            db.add(team)

        # Игроки
        for player_data in test_players:
            player = Player(**player_data)
            player.rating_history = [
                {
                    "date": datetime.now(timezone.utc).isoformat(),
                    "rating": player.rating,
                }
            ]
            db.add(player)

        await db.commit()
        print(f"OK - Added {len(test_teams)} teams")
        print(f"OK - Added {len(test_players)} players")

        # Check
        from sqlalchemy import select

        teams_count = (await db.execute(select(Team).where(Team.game == "cs2"))).scalars().all()
        players_count = (await db.execute(select(Player).where(Player.game == "cs2"))).scalars().all()

        print(f"\nTotal teams in DB: {len(teams_count)}")
        print(f"Total players in DB: {len(players_count)}")

        print("\n" + "=" * 80)
        print("TOP TEAMS")
        print("=" * 80)
        for i, t in enumerate(teams_count[:5], 1):
            print(
                f"{i}. {t.name:25s} | HLTV={str(t.hltv_rating or '-'):>5s} | "
                f"Valve={str(t.valve_rating or '-'):>5s} | avg={str(round(t.rating, 2) if t.rating else '-'):>5s} | "
                f"W/L={t.wins}W-{t.losses}L | WR10={t.win_rate_last_10 or '-'}"
            )

        print("\n" + "=" * 80)
        print("TOP PLAYERS")
        print("=" * 80)
        for i, p in enumerate(players_count[:5], 1):
            print(
                f"{i}. {p.nickname:20s} ({p.country or '-':15s}) | rating={p.rating} | "
                f"HS%={p.headshot_percentage or '-'} | ADR={p.avg_adr or '-'}"
            )

        print("\nDONE!")


if __name__ == "__main__":
    asyncio.run(main())
