"""
FACEIT API — статистика игроков CS2.
Получить ключ: https://developers.faceit.com/ (бесплатно).
Кладём в .env как FACEIT_API_KEY.
"""
import logging
import os

import aiohttp
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Player

logger = logging.getLogger(__name__)

FACEIT_BASE = "https://open.faceit.com/data/v4"


class FaceitCollector:
    def __init__(self, http: aiohttp.ClientSession):
        self.http = http
        self.key = os.getenv("FACEIT_API_KEY", "")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.key}",
            "Accept": "application/json",
        }

    async def get_player_by_nickname(self, nickname: str) -> dict | None:
        """Найти игрока по нику."""
        if not self.key:
            return None
        url = f"{FACEIT_BASE}/players"
        try:
            async with self.http.get(
                url, params={"nickname": nickname}, headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 200:
                    return await r.json()
                logger.debug("FACEIT player %s -> %s", nickname, r.status)
                return None
        except Exception as e:
            logger.error("FACEIT player error: %s", e)
            return None

    async def get_player_stats(self, player_id: str, game: str = "cs2") -> dict | None:
        """Подробная статистика игрока в конкретной игре."""
        if not self.key:
            return None
        url = f"{FACEIT_BASE}/players/{player_id}/stats/{game}"
        try:
            async with self.http.get(
                url, headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 200:
                    return await r.json()
                return None
        except Exception as e:
            logger.error("FACEIT stats error: %s", e)
            return None

    async def enrich_player(self, db: AsyncSession, nickname: str) -> dict | None:
        """Дополнить данные игрока статистикой с FACEIT. Возвращает dict со статой."""
        if not self.key:
            return None

        player = await self.get_player_by_nickname(nickname)
        if not player:
            return None

        player_id = player.get("player_id")
        stats = await self.get_player_stats(player_id, "cs2") if player_id else None

        result = {
            "nickname": player.get("nickname"),
            "country": player.get("country"),
            "faceit_elo": player.get("games", {}).get("cs2", {}).get("faceit_elo"),
            "faceit_level": player.get("games", {}).get("cs2", {}).get("skill_level"),
        }
        if stats and "lifetime" in stats:
            lt = stats["lifetime"]
            result.update({
                "kd_ratio": float(lt.get("Average K/D Ratio", 0)) if lt.get("Average K/D Ratio") else None,
                "hs_pct": float(lt.get("Average Headshots %", 0)) if lt.get("Average Headshots %") else None,
                "winrate": float(lt.get("Win Rate %", 0)) if lt.get("Win Rate %") else None,
                "matches": int(lt.get("Matches", 0)) if lt.get("Matches") else None,
            })

        # Сохраняем в БД
        try:
            r = await db.execute(
                select(Player).where(
                    and_(Player.nickname.ilike(nickname), Player.game == "cs2")
                )
            )
            existing = r.scalar_one_or_none()
            if existing:
                if result.get("country"):
                    existing.country = result["country"]
                if result.get("faceit_elo"):
                    existing.rating = float(result["faceit_elo"])
                if not existing.external_id and player_id:
                    existing.external_id = player_id
                    existing.source = "faceit"
            else:
                nickname = result.get("nickname") or player_id  # fallback на ID если nickname None
                p = Player(
                    external_id=player_id,
                    source="faceit",
                    game="cs2",
                    nickname=nickname,
                    country=result.get("country"),
                    rating=float(result["faceit_elo"]) if result.get("faceit_elo") else None,
                )
                db.add(p)
            await db.commit()
        except Exception as e:
            logger.warning("FACEIT save error: %s", e)
            await db.rollback()

        return result


async def get_faceit_player(nickname: str) -> dict | None:
    """Быстрый одноразовый запрос."""
    if not os.getenv("FACEIT_API_KEY"):
        return None
    async with aiohttp.ClientSession() as http:
        c = FaceitCollector(http)
        player = await c.get_player_by_nickname(nickname)
        if not player:
            return None
        player_id = player.get("player_id")
        stats = await c.get_player_stats(player_id, "cs2") if player_id else None
        out = {
            "nickname": player.get("nickname"),
            "country": player.get("country"),
            "elo": player.get("games", {}).get("cs2", {}).get("faceit_elo"),
            "level": player.get("games", {}).get("cs2", {}).get("skill_level"),
        }
        if stats and "lifetime" in stats:
            lt = stats["lifetime"]
            out.update({
                "kd": lt.get("Average K/D Ratio"),
                "hs": lt.get("Average Headshots %"),
                "winrate": lt.get("Win Rate %"),
                "matches": lt.get("Matches"),
            })
        return out
