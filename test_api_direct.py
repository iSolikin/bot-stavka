#!/usr/bin/env python3
"""
Test API endpoints directly.
"""
import asyncio
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./bot.db"


async def main():
    from fastapi.testclient import TestClient
    from web_app import app

    # Create test client
    client = TestClient(app)

    print("\nTesting /api/teams endpoint...")
    try:
        response = client.get("/api/teams?game=cs2&limit=3")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Got {len(data)} teams")
            if data:
                print(f"First team: {data[0].get('name')}")
                print(f"  HLTV: {data[0].get('hltv_rating')}")
                print(f"  Valve: {data[0].get('valve_rating')}")
        else:
            print(f"Error: {response.text[:200]}")
    except Exception as e:
        print(f"Exception: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
