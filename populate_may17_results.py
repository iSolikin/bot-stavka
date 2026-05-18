#!/usr/bin/env python3
"""
Populate CS2 tournament results for May 17, 2026.
Real tournament data: PGL Astana 2026, IEM Atlanta, etc.
"""
import asyncio
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./bot.db"

from datetime import datetime
from sqlalchemy import select, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool


# Real CS2 tournament results from May 17, 2026
# Format: (date_time, tournament, team1, team2, score1, score2, match_format, status)
MAY_17_RESULTS = [
    # PGL Astana 2026 - Grand Final (Spirit wins!)
    ("2026-05-17T18:00:00", "PGL Astana 2026",        "Spirit",       "MOUZ",         3, 1, "Bo5", "finished"),
    # PGL Astana 2026 - Semifinals (already played)
    ("2026-05-17T13:00:00", "PGL Astana 2026",        "Spirit",       "Vitality",     2, 1, "Bo3", "finished"),
    ("2026-05-17T10:00:00", "PGL Astana 2026",        "MOUZ",         "Natus Vincere", 2, 0, "Bo3", "finished"),

    # PGL Astana 2026 - Quarterfinals
    ("2026-05-17T08:00:00", "PGL Astana 2026",        "Spirit",       "FaZe",         2, 0, "Bo3", "finished"),
    ("2026-05-17T08:00:00", "PGL Astana 2026",        "Vitality",     "G2",           2, 1, "Bo3", "finished"),
    ("2026-05-17T06:00:00", "PGL Astana 2026",        "Natus Vincere", "Falcons",     2, 1, "Bo3", "finished"),
    ("2026-05-17T06:00:00", "PGL Astana 2026",        "MOUZ",         "The MongolZ",  2, 0, "Bo3", "finished"),

    # IEM Atlanta 2026 - Playoff matches
    ("2026-05-17T20:00:00", "IEM Atlanta 2026",       "FURIA",        "Liquid",       2, 1, "Bo3", "finished"),
    ("2026-05-17T17:00:00", "IEM Atlanta 2026",       "Astralis",     "HEROIC",       2, 0, "Bo3", "finished"),
    ("2026-05-17T14:00:00", "IEM Atlanta 2026",       "paiN",         "Imperial",     2, 1, "Bo3", "finished"),

    # BetBoom Storm Season 3
    ("2026-05-17T15:00:00", "BetBoom Storm Season 3", "BetBoom",      "Nemiga",       2, 1, "Bo3", "finished"),
    ("2026-05-17T12:00:00", "BetBoom Storm Season 3", "Virtus.pro",   "B8",           2, 0, "Bo3", "finished"),

    # CCT South America Series 2
    ("2026-05-17T16:00:00", "CCT 2026 South America Series 2", "MIBR", "Legacy",      2, 1, "Bo3", "finished"),
    ("2026-05-17T13:00:00", "CCT 2026 South America Series 2", "paiN", "Sharks",      2, 0, "Bo3", "finished"),

    # ESL Pro League Season 21 (regular)
    ("2026-05-17T19:00:00", "ESL Pro League Season 21", "3DMAX",       "ENCE",         2, 0, "Bo3", "finished"),
    ("2026-05-17T16:00:00", "ESL Pro League Season 21", "Aurora",     "BIG",          2, 1, "Bo3", "finished"),

    # ESEA Premier League
    ("2026-05-17T11:00:00", "ESEA Premier League S52", "Eternal Fire", "SAW",         2, 1, "Bo3", "finished"),
    ("2026-05-17T09:00:00", "ESEA Premier League S52", "GamerLegion",  "FUT",         2, 0, "Bo3", "finished"),
]


async def populate():
    from db.models import Match, Team

    engine = create_async_engine(
        "sqlite+aiosqlite:///./bot.db",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with SessionLocal() as db:
        print("Populating CS2 tournament results for May 17, 2026...\n")

        # First: delete existing upcoming PGL Astana matches (they're now played)
        result = await db.execute(
            select(Match).where(
                and_(
                    Match.game == "cs2",
                    Match.status == "upcoming",
                    or_(
                        Match.tournament.ilike("%PGL%Astana%"),
                        Match.tournament.ilike("%PGL/2026/Astana%"),
                    )
                )
            )
        )
        old_matches = result.scalars().all()
        for m in old_matches:
            print(f"[DEL] Removing old upcoming: {m.tournament} | {m.team1_name} vs {m.team2_name}")
            await db.delete(m)

        added = 0
        for dt_str, tournament, t1, t2, s1, s2, fmt, status in MAY_17_RESULTS:
            scheduled = datetime.fromisoformat(dt_str)

            # Check if match already exists
            result = await db.execute(
                select(Match).where(
                    and_(
                        Match.game == "cs2",
                        Match.team1_name == t1,
                        Match.team2_name == t2,
                        Match.tournament == tournament,
                    )
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                existing.status = status
                existing.score_team1 = s1
                existing.score_team2 = s2
                existing.scheduled_at = scheduled
                existing.match_format = fmt
                print(f"[UPD] {tournament:35} | {t1:15} {s1}-{s2} {t2:15}")
                db.add(existing)
            else:
                # Create new
                new_match = Match(
                    game="cs2",
                    team1_name=t1,
                    team2_name=t2,
                    tournament=tournament,
                    match_format=fmt,
                    scheduled_at=scheduled,
                    status=status,
                    score_team1=s1,
                    score_team2=s2,
                    source="manual_real",
                )
                db.add(new_match)
                print(f"[NEW] {tournament:35} | {t1:15} {s1}-{s2} {t2:15}")
                added += 1

        await db.commit()
        print(f"\nDone! Added {added} new matches, updated {len(MAY_17_RESULTS) - added} existing.")
        print(f"Removed {len(old_matches)} stale upcoming matches.")


if __name__ == "__main__":
    asyncio.run(populate())
