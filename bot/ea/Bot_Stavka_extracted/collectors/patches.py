"""
Сборщик патч-ноутов CS2 и Dota2.
CS2: store.steampowered.com/news/app/730
Dota2: dota2.com/patches
"""
import logging
import re
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Patch

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

CS2_NEWS_URL = "https://store.steampowered.com/events/ajaxgetpartnereventspageable/?appid=730&count=10&lang=english"
DOTA2_PATCHES_URL = "https://www.dota2.com/patches"


class PatchCollector:
    def __init__(self, http: aiohttp.ClientSession):
        self.http = http

    async def _get(self, url: str) -> str | None:
        try:
            async with self.http.get(url, headers=HEADERS) as resp:
                if resp.status == 200:
                    return await resp.text()
                logger.warning("Patch fetch %s -> HTTP %s", url, resp.status)
                return None
        except Exception as e:
            logger.error("Patch fetch error %s: %s", url, e)
            return None

    async def fetch_cs2_patches(self) -> list[dict]:
        """Получить последние патчи CS2 через Steam API."""
        try:
            async with self.http.get(CS2_NEWS_URL, headers=HEADERS) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.error("CS2 patch fetch error: %s", e)
            return []

        patches = []
        events = data.get("events", []) if isinstance(data, dict) else []

        for event in events:
            title = event.get("event_name", "")
            # Фильтруем только патчи
            if not any(kw in title.lower() for kw in ["update", "patch", "release notes"]):
                continue

            # Извлекаем версию из заголовка
            version_match = re.search(r"(\d+\.\d+[\.\d]*)", title)
            version = version_match.group(1) if version_match else title[:32]

            timestamp = event.get("announcement_body", {}).get("posttime", 0)
            released_at = datetime.utcfromtimestamp(timestamp) if timestamp else None

            url = f"https://store.steampowered.com/news/app/730/view/{event.get('gid', '')}"

            patches.append({
                "game": "cs2",
                "version": version,
                "released_at": released_at,
                "url": url,
                "summary": event.get("announcement_body", {}).get("headline", ""),
            })

        logger.info("CS2: found %d patches", len(patches))
        return patches

    async def fetch_dota2_patches(self) -> list[dict]:
        """Получить список патчей Dota2."""
        html = await self._get(DOTA2_PATCHES_URL)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        patches = []

        # Dota2 рендерит патчи через JS, пробуем найти данные в script-тегах
        for script in soup.find_all("script"):
            text = script.string or ""
            if "PatchData" not in text and "patches" not in text.lower():
                continue

            # Ищем версии вида 7.35, 7.35b и т.д.
            versions = re.findall(r'"version"\s*:\s*"([\d\.]+[a-z]?)"', text)
            dates = re.findall(r'"timestamp"\s*:\s*(\d+)', text)

            for i, version in enumerate(versions):
                ts = int(dates[i]) if i < len(dates) else 0
                released_at = datetime.utcfromtimestamp(ts) if ts else None
                patches.append({
                    "game": "dota2",
                    "version": version,
                    "released_at": released_at,
                    "url": f"https://www.dota2.com/patches/{version}",
                    "summary": None,
                })
            break

        # Fallback: парсим HTML напрямую
        if not patches:
            for link in soup.select("a[href*='/patches/']"):
                href = link.get("href", "")
                version_match = re.search(r"/patches/([\d\.]+[a-z]?)", href)
                if version_match:
                    version = version_match.group(1)
                    patches.append({
                        "game": "dota2",
                        "version": version,
                        "released_at": None,
                        "url": f"https://www.dota2.com{href}",
                        "summary": None,
                    })

        logger.info("Dota2: found %d patches", len(patches))
        return patches[:10]  # последние 10

    # --- Сохранение в БД ---

    async def save_patches(self, db: AsyncSession, patches_data: list[dict]) -> int:
        count = 0
        for p in patches_data:
            result = await db.execute(
                select(Patch).where(Patch.game == p["game"], Patch.version == p["version"])
            )
            if result.scalar_one_or_none():
                continue

            patch = Patch(
                game=p["game"],
                version=p["version"],
                released_at=p.get("released_at"),
                url=p.get("url"),
                summary=p.get("summary"),
            )
            db.add(patch)
            count += 1

        await db.commit()
        logger.info("Patches: saved %d new patches", count)
        return count


async def run_patches_sync(db: AsyncSession) -> None:
    """Точка входа для планировщика."""
    async with aiohttp.ClientSession() as http:
        collector = PatchCollector(http)

        cs2_patches = await collector.fetch_cs2_patches()
        await collector.save_patches(db, cs2_patches)

        dota2_patches = await collector.fetch_dota2_patches()
        await collector.save_patches(db, dota2_patches)

        logger.info("Patches sync complete")
