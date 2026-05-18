"""
Кэш на Redis. Кэшируем готовые текстовые отчёты.
"""
import hashlib
import logging

import redis.asyncio as aioredis

from config import config

logger = logging.getLogger(__name__)


class RedisCache:
    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(
            config.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await self._client.ping()
        logger.info("Redis connected: %s", config.REDIS_URL)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            logger.info("Redis connection closed")

    def _make_key(self, prefix: str, *args: str) -> str:
        raw = ":".join(str(a).lower().strip() for a in args)
        digest = hashlib.md5(raw.encode()).hexdigest()[:8]
        return f"esports:{prefix}:{digest}"

    async def get(self, key: str) -> str | None:
        if not self._client:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.warning("Redis GET error: %s", e)
            return None

    async def set(self, key: str, value: str, ttl: int) -> None:
        if not self._client:
            return
        try:
            await self._client.setex(key, ttl, value)
        except Exception as e:
            logger.warning("Redis SET error: %s", e)

    async def delete(self, key: str) -> None:
        if not self._client:
            return
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.warning("Redis DELETE error: %s", e)

    # --- Удобные методы для конкретных типов кэша ---

    async def get_team_report(self, team_name: str, game: str) -> str | None:
        key = self._make_key("team", team_name, game)
        return await self.get(key)

    async def set_team_report(self, team_name: str, game: str, report: str) -> None:
        key = self._make_key("team", team_name, game)
        await self.set(key, report, config.CACHE_TTL_REPORT)

    async def get_match_report(self, team1: str, team2: str, game: str) -> str | None:
        key = self._make_key("match", team1, team2, game)
        return await self.get(key)

    async def set_match_report(self, team1: str, team2: str, game: str, report: str) -> None:
        key = self._make_key("match", team1, team2, game)
        await self.set(key, report, config.CACHE_TTL_REPORT)

    async def get_upcoming(self, game: str) -> str | None:
        key = self._make_key("upcoming", game)
        return await self.get(key)

    async def set_upcoming(self, game: str, report: str) -> None:
        key = self._make_key("upcoming", game)
        await self.set(key, report, config.CACHE_TTL_MATCHES)

    async def get_player_report(self, nickname: str, game: str) -> str | None:
        key = self._make_key("player", nickname, game)
        return await self.get(key)

    async def set_player_report(self, nickname: str, game: str, report: str) -> None:
        key = self._make_key("player", nickname, game)
        await self.set(key, report, config.CACHE_TTL_REPORT)

    async def get_patch(self, game: str) -> str | None:
        key = self._make_key("patch", game)
        return await self.get(key)

    async def set_patch(self, game: str, report: str) -> None:
        key = self._make_key("patch", game)
        await self.set(key, report, config.CACHE_TTL_MATCHES)

    async def invalidate_game(self, game: str) -> None:
        """Сбросить весь кэш по игре (при обновлении данных)."""
        if not self._client:
            return
        try:
            pattern = f"esports:*:{game}*"
            keys = await self._client.keys(pattern)
            if keys:
                await self._client.delete(*keys)
                logger.info("Cache invalidated: %d keys for %s", len(keys), game)
        except Exception as e:
            logger.warning("Redis invalidate error: %s", e)


# Глобальный экземпляр
cache = RedisCache()
