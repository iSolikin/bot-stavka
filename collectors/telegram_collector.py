"""
Сборщик сообщений из Telegram-каналов через Telethon.
Работает как обычный пользователь (не бот).
"""
import logging
import re
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.tl.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import config
from db.models import TelegramChannel, TelegramMessage

logger = logging.getLogger(__name__)

# Словари для определения упомянутых команд/игроков
TEAM_ALIASES: dict[str, list[str]] = {
    # CS2
    "navi": ["natus vincere", "navi", "na`vi", "na'vi", "навигатор", "нави"],
    "vitality": ["team vitality", "vitality", "виталити"],
    "faze": ["faze clan", "faze", "фейз"],
    "g2": ["g2 esports", "g2", "же два"],
    "heroic": ["heroic", "хероик"],
    "spirit": ["team spirit", "spirit", "спирит"],
    "liquid": ["team liquid", "liquid", "ликвид"],
    "mouz": ["mousesports", "mouz", "mouse"],
    "falcons": ["team falcons", "falcons", "фалконс"],
    "mongol": ["the mongolz", "mongolz", "монголз"],
    "astralis": ["astralis", "астралис"],
    "ence": ["ence"],
    "apeks": ["apeks"],
    "cloud9": ["cloud9", "c9", "клауд9"],
    "vp": ["virtus.pro", "virtuspro", "vp", "вп", "виртус"],
    # Dota2
    "og": ["og", "оджи"],
    "tundra": ["tundra esports", "tundra", "тундра"],
    "gaimin": ["gaimin gladiators", "gaimin", "гаймин"],
    "secret": ["team secret", "secret", "сикрет"],
    "xtreme": ["xtreme gaming", "xtreme"],
    "bb": ["betboom team", "betboom", "bb team", "бетбум"],
    "aurora": ["aurora gaming", "aurora", "аурора"],
    "gl": ["gamelegion", "game legion", "gl"],
    "nouns": ["nouns esports", "nouns"],
    "beastcoast": ["beastcoast"],
    "talon": ["talon esports", "talon"],
}

PLAYER_ALIASES: dict[str, list[str]] = {
    "s1mple": ["s1mple", "александр костылев"],
    "zywoo": ["zywoo", "mathieu herbaut"],
    "niko": ["niko", "nikola kovač"],
    "device": ["device", "nicolai reedtz"],
    "puppey": ["puppey", "clement ivanov"],
    "miracle": ["miracle-", "miracle"],
    "topson": ["topson", "topias taavitsainen"],
}


def _find_mentions(text: str, aliases: dict[str, list[str]]) -> list[str]:
    """Найти упоминания в тексте по словарю алиасов."""
    text_lower = text.lower()
    found = []
    for key, variants in aliases.items():
        if any(v in text_lower for v in variants):
            found.append(key)
    return found


def _detect_game(text: str) -> str | None:
    text_lower = text.lower()
    cs2_keywords = ["cs2", "cs:go", "counter-strike", "csgo", "hltv"]
    dota_keywords = ["dota", "dota2", "dota 2", "ti", "the international"]

    has_cs2 = any(kw in text_lower for kw in cs2_keywords)
    has_dota = any(kw in text_lower for kw in dota_keywords)

    if has_cs2 and not has_dota:
        return "cs2"
    if has_dota and not has_cs2:
        return "dota2"
    if has_cs2 and has_dota:
        return "both"
    return None


class TelegramCollector:
    def __init__(self, client: TelegramClient):
        self.client = client

    async def get_active_channels(self, db: AsyncSession) -> list[str]:
        """Получить список активных каналов из БД."""
        result = await db.execute(
            select(TelegramChannel.username).where(TelegramChannel.is_active == True)
        )
        return [row[0] for row in result.fetchall()]

    async def fetch_new_messages(
        self, channel: str, db: AsyncSession, limit: int = 20
    ) -> list[dict]:
        """Получить новые сообщения из канала."""
        # Находим ID последнего сохранённого сообщения
        result = await db.execute(
            select(TelegramMessage.message_id)
            .where(TelegramMessage.channel_username == channel)
            .order_by(TelegramMessage.message_id.desc())
            .limit(1)
        )
        row = result.fetchone()
        min_id = row[0] if row else 0

        messages = []
        try:
            async for msg in self.client.iter_messages(channel, limit=limit, min_id=min_id):
                if not isinstance(msg, Message) or not msg.text:
                    continue
                messages.append({
                    "channel": channel,
                    "message_id": msg.id,
                    "text": msg.text,
                    "posted_at": msg.date.replace(tzinfo=None) if msg.date else None,
                })
        except Exception as e:
            logger.error("Telegram fetch error for %s: %s", channel, e)

        return messages

    async def save_messages(self, db: AsyncSession, messages: list[dict]) -> int:
        count = 0
        for m in messages:
            # Проверяем что такого сообщения ещё нет в БД
            existing = await db.execute(
                select(TelegramMessage).where(
                    TelegramMessage.channel_username == m["channel"],
                    TelegramMessage.message_id == m["message_id"],
                )
            )
            if existing.scalar_one_or_none():
                continue

            text = m["text"] or ""
            mentioned_teams = _find_mentions(text, TEAM_ALIASES)
            mentioned_players = _find_mentions(text, PLAYER_ALIASES)
            game = _detect_game(text)

            msg = TelegramMessage(
                channel_username=m["channel"],
                message_id=m["message_id"],
                text=text[:4096],
                mentioned_teams=",".join(mentioned_teams) if mentioned_teams else None,
                mentioned_players=",".join(mentioned_players) if mentioned_players else None,
                game=game,
                posted_at=m["posted_at"],
            )
            db.add(msg)
            count += 1

        if count:
            await db.commit()
        return count

    async def sync_all_channels(self, db: AsyncSession) -> int:
        """Синхронизировать все активные каналы."""
        channels = await self.get_active_channels(db)
        if not channels:
            logger.info("Telegram: no active channels configured")
            return 0

        total = 0
        for channel in channels:
            messages = await self.fetch_new_messages(channel, db)
            saved = await self.save_messages(db, messages)
            total += saved
            logger.info("Telegram: %s -> %d new messages", channel, saved)

        return total


async def run_telegram_sync(db: AsyncSession) -> None:
    """Точка входа для планировщика."""
    if not config.TG_API_ID or not config.TG_API_HASH:
        logger.debug("Telegram sync skipped: TG_API_ID/TG_API_HASH not configured")
        return

    client = TelegramClient(
        "esports_bot_session",
        config.TG_API_ID,
        config.TG_API_HASH,
    )
    try:
        async with client:
            await client.start(phone=config.TG_PHONE)
            collector = TelegramCollector(client)
            total = await collector.sync_all_channels(db)
            logger.info("Telegram sync complete: %d new messages", total)
    except Exception as e:
        logger.warning("Telegram sync failed: %s", e)
