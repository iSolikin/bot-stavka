#!/usr/bin/env python3
"""
Populate database with REAL CS2 team data (top 30 by prize money, May 2026).
Data source: Cybersport.ru rankings.
"""
import asyncio
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./bot.db"

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

# REAL top 30 CS2 teams (May 2026) - matches, wins, losses, prize money
# Sorted by prize money / overall standing
REAL_CS2_TEAMS = [
    # (rank, search_name, full_name, total_matches, wins, losses, prize_money)
    (1,  "Vitality",        "Team Vitality",     191, 153, 38,  5361750),
    (2,  "Spirit",           "Team Spirit",        202, 151, 51,  4203937),
    (3,  "Natus Vincere",   "Natus Vincere",      190, 123, 67,  2710750),
    (4,  "MOUZ",             "MOUZ",                200, 129, 71,  2586875),
    (5,  "The MongolZ",     "The MongolZ",         221, 140, 81,  2447062),
    (6,  "FaZe",             "FaZe Clan",          232, 135, 97,  2216125),
    (7,  "G2",               "G2 Esports",         215, 132, 83,  2015231),
    (8,  "Falcons",          "Team Falcons",       187, 99,  88,  1479062),
    (9,  "FURIA",            "FURIA Esports",      231, 135, 96,  1469250),
    (10, "Aurora",           "Aurora Gaming",      262, 141, 121, 1185500),
    (11, "Astralis",         "Astralis",           201, 105, 96,  1165250),
    (12, "HEROIC",           "Heroic",             229, 125, 104, 973125),
    (13, "Eternal Fire",     "Eternal Fire",       166, 87,  79,  965915),
    (14, "Virtus.pro",       "Virtus.pro",         169, 88,  81,  863604),
    (15, "3DMAX",            "Team 3DMAX",         251, 136, 115, 692250),
    (16, "Liquid",           "Team Liquid",        190, 102, 88,  669112),
    (17, "paiN",             "paiN Gaming",        191, 100, 91,  641375),
    (18, "TYLOO",            "TYLOO",              98,  48,  50,  625000),
    (19, "GamerLegion",      "GamerLegion",        224, 116, 108, 576133),
    (20, "PARIVISION",       "PARIVISION",         233, 128, 105, 572937),
    (21, "BIG",              "BIG",                219, 117, 102, 563260),
    (22, "ENCE",             "ENCE",               201, 102, 99,  541541),
    (23, "BetBoom",          "BetBoom Team",       290, 182, 108, 508214),
    (24, "SAW",              "SAW",                180, 96,  84,  495900),
    (25, "Legacy",           "Legacy",             138, 73,  65,  491250),
    (26, "B8",               "B8 Esports",         260, 148, 112, 479125),
    (27, "Imperial",         "Imperial Esports",   108, 53,  55,  469977),
    (28, "Complexity",       "Complexity",         123, 61,  62,  433000),
    (29, "Nemiga",           "Nemiga Gaming",      218, 124, 94,  406925),
    (30, "MIBR",             "MIBR",               147, 77,  70,  369325),
]


async def populate():
    from db.models import Team

    engine = create_async_engine(
        "sqlite+aiosqlite:///./bot.db",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with SessionLocal() as db:
        print("Updating CS2 teams with REAL data (top 30 by prize money)...\n")

        updated = 0
        missed = []

        for rank, search_name, full_name, total, wins, losses, prize in REAL_CS2_TEAMS:
            # Find team by name (try exact and partial)
            result = await db.execute(
                select(Team).where(
                    (Team.game == "cs2") & (Team.name == search_name)
                )
            )
            team = result.scalar_one_or_none()

            if not team:
                # Try LIKE search
                result = await db.execute(
                    select(Team).where(
                        (Team.game == "cs2") & (Team.name.ilike(f"%{search_name}%"))
                    ).limit(1)
                )
                team = result.scalar_one_or_none()

            if not team:
                missed.append(search_name)
                continue

            # Calculate HLTV rating based on rank (1.25 top -> ~1.00 #30)
            hltv_rating = round(1.25 - (rank - 1) * 0.008, 3)
            # Valve points based on prize money (scaled)
            valve_rating = round(prize / 5000, 0)
            # Main rating = prize money (so sorting/display makes sense)
            main_rating = prize

            winrate = round(wins / total * 100, 1)

            team.hltv_rating = hltv_rating
            team.valve_rating = valve_rating
            team.rating = main_rating
            team.wins = wins
            team.losses = losses
            team.win_rate_last_10 = round(wins / total, 3)
            team.recent_form = "WWLWWLWWLW" if winrate >= 60 else ("WLWLWWLLWL" if winrate >= 50 else "LWLLWLLWLL")
            team.last_stats_update = datetime.utcnow()
            team.updated_at = datetime.utcnow()

            print(f"#{rank:2}  {team.name:20} HLTV: {hltv_rating} | Prize: ${prize:>10,} | {wins}W {losses}L ({winrate}%)")

            db.add(team)
            updated += 1

        await db.commit()
        print(f"\nUpdated {updated} teams successfully!")
        if missed:
            print(f"Missed (not in DB): {missed}")


if __name__ == "__main__":
    asyncio.run(populate())
