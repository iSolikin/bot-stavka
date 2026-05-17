#!/usr/bin/env python3
"""
Debug all API endpoints to find 500 error.
"""
import asyncio
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./bot.db"

async def main():
    from fastapi.testclient import TestClient
    from web_app import app

    client = TestClient(app)

    endpoints = [
        ("/api/teams?game=cs2", "Teams"),
        ("/api/matches/upcoming?game=cs2", "Upcoming matches"),
        ("/api/matches/results?game=cs2", "Match results"),
        ("/api/bets/stats", "Bets stats"),
        ("/api/today", "Today predictions"),
    ]

    print("\n" + "=" * 80)
    print("TESTING ALL API ENDPOINTS")
    print("=" * 80)

    for endpoint, name in endpoints:
        print(f"\n{name}: {endpoint}")
        try:
            response = client.get(endpoint)
            status = response.status_code
            status_color = "OK" if status == 200 else f"ERROR {status}"
            print(f"  Status: {status_color}")

            if status != 200:
                try:
                    error_text = response.json()
                    print(f"  Error: {error_text.get('detail', error_text)}")
                except:
                    print(f"  Response: {response.text[:200]}")
        except Exception as e:
            print(f"  Exception: {e}")

if __name__ == "__main__":
    asyncio.run(main())
