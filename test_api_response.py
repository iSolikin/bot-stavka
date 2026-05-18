#!/usr/bin/env python3
"""
Check what API will return for teams.
"""
import asyncio
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./bot.db"


async def main():
    from db.database import AsyncSessionLocal
    from web_app import _team_dict
    from sqlalchemy import select
    from db.models import Team

    async with AsyncSessionLocal() as db:
        teams = (await db.execute(
            select(Team).where(Team.game == "cs2").order_by(Team.hltv_rating.desc()).limit(3)
        )).scalars().all()

        print("\n" + "=" * 80)
        print("WHAT API WILL RETURN FOR TOP 3 TEAMS")
        print("=" * 80)

        for team in teams:
            api_response = _team_dict(team)
            print(f"\nTeam: {team.name}")
            print("-" * 40)
            for key, value in api_response.items():
                if value is not None and value != [] and value != {}:
                    if isinstance(value, dict):
                        print(f"  {key}: {value}")
                    elif isinstance(value, list):
                        print(f"  {key}: {len(value)} items")
                    else:
                        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
