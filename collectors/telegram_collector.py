"""
Сборщик новостей из открытых источников (без Telegram API).
Читает RSS и HTML-страницы новостных сайтов.
Сохраняет в таблицу telegram_messages для совместимости с news_processor.
"""
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import TelegramMessage

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

# ──────────────────────── Определение команд/игроков ────────────────────────

TEAM_ALIASES: dict[str, list[str]] = {
    "navi": ["natus vincere", "navi", "na`vi", "na'vi", "нави"],
    "vitality": ["team vitality", "vitality"],
    "faze": ["faze clan", "faze"],
    "g2": ["g2 esports", "g2 esports"],
    "heroic": ["heroic"],
    "spirit": ["team spirit", "spirit"],
    "liquid": ["team liquid", "liquid"],
    "mouz": ["mousesports", "mouz", "mouse"],
    "falcons": ["team falcons", "falcons"],
    "mongol": ["the mongolz", "mongolz"],
    "astralis": ["astralis"],
    "cloud9": ["cloud9", "c9"],
    "vp": ["virtus.pro", "virtuspro"],
    "og": ["og esports"],
    "tundra": ["tundra esports", "tundra"],
    "gaimin": ["gaimin gladiators", "gaimin"],
    "secret": ["team secret"],
    "bb": ["betboom team", "betboom"],
    "aurora": ["aurora gaming", "aurora"],
}

PLAYER_ALIASES: dict[str, list[str]] = {
    "s1mple": ["s1mple"],
    "zywoo": ["zywoo"],
    "niko": ["niko"],
    "device": ["device"],
    "puppey": ["puppey"],
    "miracle": ["miracle"],
    "topson": ["topson"],
}


def _find_mentions(text: str, aliases: dict[str, list[str]]) -> list[str]:
    text_lower = text.lower()
    return [k for k, vs in aliases.items() if any(v in text_lower for v in vs)]


def _detect_game(text: str) -> str | None:
    t = text.lower()
    has_cs = any(kw in t for kw in ["cs2", "cs:go", "counter-strike", "csgo", "hltv"])
    has_d2 = any(kw in t for kw in ["dota", "dota2", "dota 2", "the international"])
    if has_cs and not has_d2:
        return "cs2"
    if has_d2 and not has_cs:
        return "dota2"
    if has_cs and has_d2:
        return "both"
    return None


def _html_to_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#8217;", "'", text)
    text = re.sub(r"&#[0-9]+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


# ──────────────────────── RSS парсер ────────────────────────

RSS_SOURCES = [
    # (channel_username, url, game_hint)
    ("vpesports_cs2",   "https://vpesports.com/feed",        "cs2"),
    ("dotabuff_blog",   "https://www.dotabuff.com/blog.rss", "dota2"),
    ("cybersport_scrape", None, None),   # HTML scraper, не RSS
]


def _parse_rss(xml_text: str, channel: str, game_hint: str | None) -> list[dict]:
    """Парсим RSS/Atom XML и возвращаем список сообщений."""
    messages = []
    try:
        # Убираем BOM и ведущие пробелы/переносы до <?xml
        xml_text = xml_text.lstrip("﻿ \t\r\n")
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("RSS parse error for %s: %s", channel, e)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # RSS 2.0
    items = root.findall(".//item")
    # Atom
    if not items:
        items = root.findall(".//atom:entry", ns) or root.findall(".//entry")

    for i, item in enumerate(items[:30]):
        # Заголовок
        title_el = item.find("title")
        title = _html_to_text(title_el.text or "") if title_el is not None else ""

        # Описание / summary
        for tag in ("description", "summary", "content", "{http://purl.org/rss/1.0/modules/content/}encoded"):
            desc_el = item.find(tag)
            if desc_el is not None and desc_el.text:
                desc = _html_to_text(desc_el.text)[:500]
                break
        else:
            desc = ""

        text = f"{title}. {desc}".strip(". ") if desc else title
        if len(text) < 10:
            continue

        # Дата
        pub_el = item.find("pubDate") or item.find("published") or item.find("updated")
        posted_at = datetime.utcnow()
        if pub_el is not None and pub_el.text:
            try:
                dt = parsedate_to_datetime(pub_el.text)
                posted_at = dt.replace(tzinfo=None)
            except Exception:
                try:
                    posted_at = datetime.fromisoformat(
                        pub_el.text.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except Exception:
                    pass

        # Уникальный ID (используем порядковый номер + хэш)
        link_el = item.find("link") or item.find("{http://www.w3.org/2005/Atom}link")
        link = ""
        if link_el is not None:
            link = link_el.text or link_el.get("href", "")
        msg_id = abs(hash(link or text[:50])) % (10**9)

        game = _detect_game(text) or game_hint

        messages.append({
            "channel": channel,
            "message_id": msg_id,
            "text": text[:4096],
            "posted_at": posted_at,
            "game": game,
        })

    return messages


# ──────────────────────── cybersport.ru HTML scraper ────────────────────────

async def _scrape_cybersport(client: httpx.AsyncClient) -> list[dict]:
    """Скрапим заголовки новостей с cybersport.ru."""
    messages = []
    try:
        resp = await client.get("https://cybersport.ru/", timeout=15)
        if resp.status_code != 200:
            return []
        html = resp.text
        # Ищем заголовки новостей
        titles = re.findall(
            r'<(?:h[123]|a)[^>]+class="[^"]*(?:title|heading|news)[^"]*"[^>]*>\s*([^<]{15,200})\s*<',
            html, re.IGNORECASE
        )
        # Fallback — просто все h2/h3 теги
        if not titles:
            titles = re.findall(r'<h[23][^>]*>\s*<a[^>]*>([^<]{15,150})</a>', html)

        seen = set()
        for i, title in enumerate(titles[:20]):
            title = _html_to_text(title).strip()
            if len(title) < 15 or title in seen:
                continue
            seen.add(title)
            game = _detect_game(title)
            msg_id = abs(hash(title)) % (10**9)
            messages.append({
                "channel": "cybersport_scrape",
                "message_id": msg_id,
                "text": title,
                "posted_at": datetime.utcnow(),
                "game": game,
            })
    except Exception as e:
        logger.warning("cybersport.ru scrape failed: %s", e)
    return messages


# ──────────────────────── Сохранение в БД ────────────────────────

async def _save_messages(db: AsyncSession, messages: list[dict]) -> int:
    count = 0
    for m in messages:
        existing = await db.execute(
            select(TelegramMessage).where(
                TelegramMessage.channel_username == m["channel"],
                TelegramMessage.message_id == m["message_id"],
            )
        )
        if existing.scalar_one_or_none():
            continue

        text = m.get("text") or ""
        game = m.get("game") or _detect_game(text)
        mentioned_teams = _find_mentions(text, TEAM_ALIASES)
        mentioned_players = _find_mentions(text, PLAYER_ALIASES)

        msg = TelegramMessage(
            channel_username=m["channel"],
            message_id=m["message_id"],
            text=text,
            mentioned_teams=",".join(mentioned_teams) if mentioned_teams else None,
            mentioned_players=",".join(mentioned_players) if mentioned_players else None,
            game=game,
            posted_at=m.get("posted_at") or datetime.utcnow(),
        )
        db.add(msg)
        count += 1

    if count:
        await db.commit()
    return count


# ──────────────────────── Точка входа ────────────────────────

async def run_telegram_sync(db: AsyncSession) -> None:
    """Собираем новости из RSS и HTML-скраперов."""
    total = 0
    async with httpx.AsyncClient(timeout=15, headers=_HEADERS, follow_redirects=True) as client:

        # RSS источники
        for channel, url, game_hint in RSS_SOURCES:
            if url is None:
                continue
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    msgs = _parse_rss(resp.text, channel, game_hint)
                    saved = await _save_messages(db, msgs)
                    if saved:
                        logger.info("News [%s]: %d new items", channel, saved)
                    total += saved
                else:
                    logger.warning("RSS %s: HTTP %s", channel, resp.status_code)
            except Exception as e:
                logger.warning("RSS fetch failed [%s]: %s", channel, e)

        # HTML скрапер cybersport.ru
        msgs = await _scrape_cybersport(client)
        saved = await _save_messages(db, msgs)
        if saved:
            logger.info("News [cybersport.ru]: %d new items", saved)
        total += saved

    if total:
        logger.info("News sync complete: %d new items total", total)
