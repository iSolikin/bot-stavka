#!/usr/bin/env python3
"""
Проверяем что реально собирают коллекторы.
"""
import asyncio
import logging
import aiohttp

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


async def main():
    # Тест HLTV API
    logger.info("\n" + "=" * 80)
    logger.info("ТЕСТ HLTV API")
    logger.info("=" * 80)

    urls = [
        "https://www.hltv.org/api/matches/upcoming",
        "https://www.hltv.org/api/matches/results",
        "https://www.hltv.org/api/teams/ranking",
        "https://www.hltv.org/api/players/rating",
    ]

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    async with aiohttp.ClientSession() as session:
        for url in urls:
            logger.info(f"\nПроверяем: {url}")
            try:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    logger.info(f"  Status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list):
                            logger.info(f"  ✓ Результат: {len(data)} записей")
                            if data:
                                logger.info(f"    Первая запись: {str(data[0])[:200]}")
                        else:
                            logger.info(f"  ✓ Результат: {str(data)[:200]}")
                    else:
                        text = await resp.text()
                        logger.info(f"  Ответ: {text[:200]}")
            except Exception as e:
                logger.error(f"  ✗ Ошибка: {e}")

    # Тест Cybersport
    logger.info("\n" + "=" * 80)
    logger.info("ТЕСТ CYBERSPORT")
    logger.info("=" * 80)

    async with aiohttp.ClientSession() as session:
        urls = [
            "https://www.cybersport.ru/rankings?discipline=cs2&ranking=hltv",
            "https://www.cybersport.ru/rankings?discipline=cs2&ranking=valve",
        ]

        for url in urls:
            logger.info(f"\nПроверяем: {url}")
            try:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    logger.info(f"  Status: {resp.status}")
                    if resp.status == 200:
                        text = await resp.text()
                        logger.info(f"  HTML длина: {len(text)} chars")
                        if "team" in text.lower():
                            logger.info("  ✓ HTML содержит 'team' — страница загружена")
                        else:
                            logger.info("  ⚠ HTML не содержит 'team' — может быть защита")
                    else:
                        text = await resp.text()
                        logger.info(f"  Ответ: {text[:200]}")
            except Exception as e:
                logger.error(f"  ✗ Ошибка: {e}")


if __name__ == "__main__":
    asyncio.run(main())
