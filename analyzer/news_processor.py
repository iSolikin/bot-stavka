"""
Обработка новостей: извлечение структурированных событий через Grok (xAI).
Если ключ не задан или лимит исчерпан — keyword-fallback.

Событие:
  team_name, player_name, game, event_type, impact (-1..+1), summary
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from db.models import TelegramMessage, NewsEvent

logger = logging.getLogger(__name__)

# ──────────────────────── Prompt ────────────────────────

_EXTRACT_PROMPT = """\
Ты аналитик киберспортивных новостей. Извлеки структурированные события из текста.

Верни ТОЛЬКО JSON (без markdown-обёртки):
{
  "events": [
    {
      "team": "<точное имя команды или null>",
      "player": "<никнейм игрока или null>",
      "game": "<cs2 или dota2 или null>",
      "event_type": "<тип из списка ниже>",
      "impact": <число от -1.0 до 1.0>,
      "summary": "<одно предложение на русском>"
    }
  ]
}

Типы событий и значения impact:
- injury          → -0.3 до -0.5  (травма игрока)
- absence         → -0.2 до -0.4  (игрок не сыграет по любой причине)
- roster_remove   → -0.2 до -0.3  (уход ключевого игрока)
- roster_add      → +0.1 до +0.2  (приход сильного игрока)
- bootcamp        → +0.05 до +0.15 (бутcамп, подготовка)
- form_peak       → +0.1 до +0.2  (команда в отличной форме)
- form_poor       → -0.1 до -0.2  (плохая форма, проблемы)
- win_streak      → +0.1 до +0.15 (серия побед)
- loss_streak     → -0.1 до -0.15 (серия поражений)
- disqualified    → -0.9          (дисквалификация)
- other           → 0.0           (нейтральная новость)

Правила:
- Если игрок — звезда (топ игрок команды) → умножь impact на 1.5
- Если событие уже произошло (прошлое) → уменьши impact вдвое
- Если нет явных событий → верни {"events": []}
- game определяй по контексту (CS2/CSGO/Counter-Strike → cs2, Dota/Dota2 → dota2)

Текст новости:
"""

# ──────────────────────── Grok (xAI) API ────────────────────────

_ai_unavailable: bool = False  # флаг: лимит/ошибка → keyword fallback


async def _call_groq(text: str, api_key: str, model: str = "llama-3.1-8b-instant") -> list[dict] | None:
    """
    Вызов Groq API (OpenAI-совместимый, бесплатно 14400 req/day).
    Возвращает список event-словарей или None → keyword fallback.
    """
    global _ai_unavailable
    if _ai_unavailable:
        return None

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a esports news analyst. Always respond with valid JSON only, no markdown.",
            },
            {
                "role": "user",
                "content": _EXTRACT_PROMPT + text[:2000],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 512,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        raw = data["choices"][0]["message"]["content"]
        # Убираем возможную markdown-обёртку ```json ... ```
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
        parsed = json.loads(raw)
        _ai_unavailable = False
        return parsed.get("events", [])

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 429:
            logger.warning("[Groq] Rate limit hit, switching to keyword fallback temporarily")
            # Не блокируем навсегда — rate limit временный
        elif status in (401, 403):
            logger.error("[Groq] Invalid API key!")
            _ai_unavailable = True
        else:
            logger.warning("[Groq] HTTP %s: %s", status, e)
        return None

    except json.JSONDecodeError as e:
        logger.warning("[Groq] JSON parse error: %s", e)
        return []  # пустой список, не None — ключ работает

    except Exception as e:
        logger.warning("[Groq] Call failed: %s", e)
        return None


# ──────────────────────── Keyword fallback ────────────────────────

_KW_ABSENCE = [
    "не сыграет", "пропустит", "не выйдет", "травмирован", "травма", "болен",
    "заменён", "won't play", "injured", "injury", "sick", "out of", "replaced",
    "не будет играть", "не выступит", "отстранён", "stand-in",
]
_KW_ROSTER_REMOVE = [
    "покинул", "ушёл", "ушел из", "вышел из", "покидает", "уволен",
    "left", "departs", "parts ways", "released", "dropped",
]
_KW_ROSTER_ADD = [
    "подписал", "перешёл в", "перешел в", "присоединился", "joins", "signs with",
    "new roster", "новый состав", "добавлен в",
]
_KW_DISQUALIFIED = [
    "дисквалифицирован", "дисквалификация", "бан", "banned", "disqualified",
    "читерство", "читер", "cheat", "vac ban",
]
_KW_FORM_GOOD = [
    "отличная форма", "в ударе", "горячая серия", "победная серия",
    "on fire", "great form", "hot streak", "5 wins", "5 побед",
]
_KW_FORM_BAD = [
    "плохая форма", "кризис", "проблемы", "слабая игра", "потеряли форму",
    "struggling", "bad form", "losing streak", "3 поражения",
]
_KW_BOOTCAMP = ["бутcamp", "bootcamp", "бутcamп", "подготовка к", "training camp"]


def _keyword_extract(text: str, mentioned_teams: str | None) -> list[dict]:
    """Простое keyword-based извлечение без AI."""
    t = text.lower()
    events = []

    teams = [x.strip() for x in (mentioned_teams or "").split(",") if x.strip()]
    team = teams[0] if teams else None

    if any(kw in t for kw in _KW_DISQUALIFIED):
        events.append({"team": team, "player": None, "game": None,
                        "event_type": "disqualified", "impact": -0.9,
                        "summary": "Дисквалификация"})
    elif any(kw in t for kw in _KW_ABSENCE):
        events.append({"team": team, "player": None, "game": None,
                        "event_type": "absence", "impact": -0.3,
                        "summary": "Игрок не сыграет"})
    elif any(kw in t for kw in _KW_ROSTER_REMOVE):
        events.append({"team": team, "player": None, "game": None,
                        "event_type": "roster_remove", "impact": -0.2,
                        "summary": "Игрок покинул команду"})
    elif any(kw in t for kw in _KW_ROSTER_ADD):
        events.append({"team": team, "player": None, "game": None,
                        "event_type": "roster_add", "impact": +0.15,
                        "summary": "Новый игрок в составе"})
    elif any(kw in t for kw in _KW_FORM_GOOD):
        events.append({"team": team, "player": None, "game": None,
                        "event_type": "form_peak", "impact": +0.12,
                        "summary": "Команда в хорошей форме"})
    elif any(kw in t for kw in _KW_FORM_BAD):
        events.append({"team": team, "player": None, "game": None,
                        "event_type": "form_poor", "impact": -0.12,
                        "summary": "Команда в плохой форме"})
    elif any(kw in t for kw in _KW_BOOTCAMP):
        events.append({"team": team, "player": None, "game": None,
                        "event_type": "bootcamp", "impact": +0.08,
                        "summary": "Команда на бутcampе"})

    return events


# ──────────────────────── Сохранение в БД ────────────────────────

def _make_news_event(ev: dict, msg: TelegramMessage, processed_by: str) -> NewsEvent | None:
    """Создать NewsEvent из сырого словаря."""
    impact = ev.get("impact", 0.0)
    if not isinstance(impact, (int, float)):
        impact = 0.0
    impact = max(-1.0, min(1.0, float(impact)))

    event_type = ev.get("event_type", "other") or "other"
    # Пропускаем нейтральные другие
    if event_type == "other" and abs(impact) < 0.05:
        return None

    game = ev.get("game") or msg.game
    if game not in ("cs2", "dota2"):
        game = msg.game  # fallback к тому что определил коллектор

    return NewsEvent(
        source_message_id=msg.id,
        channel_username=msg.channel_username,
        team_name=ev.get("team") or None,
        player_name=ev.get("player") or None,
        game=game,
        event_type=event_type,
        impact=round(impact, 3),
        summary=ev.get("summary") or None,
        processed_by=processed_by,
        valid_until=datetime.utcnow() + timedelta(days=7),
    )


async def process_unprocessed_messages(
    db: AsyncSession,
    gemini_key: str = "",  # оставляем параметр для совместимости (игнорируется)
    gemini_model: str = "grok-3-mini",
    batch_size: int = 30,
    only_important: bool = True,
) -> int:
    """
    Обработать необработанные TelegramMessage → создать NewsEvent.
    Использует Grok (xAI) если GROK_API_KEY задан, иначе keyword-fallback.
    Возвращает количество созданных событий.
    """
    from config import config

    grok_key = getattr(config, "GROQ_API_KEY", "") or ""
    grok_model = getattr(config, "GROQ_MODEL", "llama-3.1-8b-instant") or "llama-3.1-8b-instant"
    use_ai = bool(grok_key)

    # Находим ID уже обработанных сообщений
    processed_ids_result = await db.execute(
        select(NewsEvent.source_message_id).where(
            NewsEvent.source_message_id.isnot(None)
        )
    )
    processed_ids = {row[0] for row in processed_ids_result.fetchall()}

    # Берём свежие необработанные сообщения (за последние 48 ч)
    since = datetime.utcnow() - timedelta(hours=48)
    q = (
        select(TelegramMessage)
        .where(
            and_(
                TelegramMessage.posted_at >= since,
                TelegramMessage.id.not_in(processed_ids) if processed_ids else True,
                TelegramMessage.text.isnot(None),
            )
        )
        .order_by(TelegramMessage.posted_at.desc())
        .limit(batch_size)
    )
    result = await db.execute(q)
    messages = result.scalars().all()

    if not messages:
        logger.debug("news_processor: no unprocessed messages")
        return 0

    total_events = 0

    for msg in messages:
        text = (msg.text or "").strip()
        if len(text) < 20:
            continue

        # Если only_important — пропускаем сообщения без упомянутых команд и без ключевых слов
        if only_important:
            has_team = bool(msg.mentioned_teams)
            has_kw = any(kw in text.lower() for kw in (
                _KW_ABSENCE + _KW_ROSTER_REMOVE + _KW_ROSTER_ADD +
                _KW_DISQUALIFIED + _KW_FORM_GOOD + _KW_FORM_BAD
            ))
            if not has_team and not has_kw:
                continue

        raw_events = None
        processed_by = "keywords"

        if use_ai:
            raw_events = await _call_groq(text, grok_key, grok_model)
            if raw_events is not None:
                processed_by = "groq"
                # Соблюдаем rate limit (бесплатный тир: ~4 req/sec)
                await asyncio.sleep(0.3)

        if raw_events is None:
            raw_events = _keyword_extract(text, msg.mentioned_teams)
            processed_by = "keywords"

        for ev in raw_events:
            ne = _make_news_event(ev, msg, processed_by)
            if ne:
                db.add(ne)
                total_events += 1

    if total_events:
        await db.commit()
        logger.info("news_processor: created %d NewsEvents (%s)",
                    total_events, "grok" if use_ai else "keywords")

    return total_events


# ──────────────────────── Получение событий для матча ────────────────────────

async def get_team_events(
    db: AsyncSession,
    team_name: str,
    game: str | None = None,
    days: int = 7,
) -> list[NewsEvent]:
    """Получить актуальные NewsEvent для команды (для предиктора)."""
    now = datetime.utcnow()
    name_lower = team_name.lower()
    # Нормализуем: "Team Spirit" → "spirit"
    words = [w for w in name_lower.split() if len(w) > 2 and w not in ("team", "gaming", "esports", "club")]
    search = words[0] if words else name_lower

    filters = [
        NewsEvent.valid_until >= now,
        NewsEvent.created_at >= now - timedelta(days=days),
        NewsEvent.team_name.ilike(f"%{search}%"),
    ]
    if game:
        from sqlalchemy import or_
        filters.append(or_(NewsEvent.game == game, NewsEvent.game.is_(None)))

    result = await db.execute(
        select(NewsEvent)
        .where(*filters)
        .order_by(NewsEvent.created_at.desc())
        .limit(10)
    )
    return result.scalars().all()
