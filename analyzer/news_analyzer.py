"""
Анализ и агрегация новостей из Telegram-каналов.

Классифицирует сообщения по категориям, строит дайджест,
ищет новости по командам для интеграции с матч-анализом.
"""
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from db.models import TelegramMessage, TelegramChannel

logger = logging.getLogger(__name__)

# ───────────────────────────── Ключевые слова ─────────────────────────────

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "roster": [
        "трансфер", "transfer", "замена", "замен", "новый игрок", "новый состав",
        "покинул", "ушёл", "ушел", "вышел из", "покидает", "joined", "signs",
        "roster", "состав", "подписал", "подписание", "отстранён", "бан", "banned",
        "дисквалификация", "disqualified", "stand-in", "стэнд-ин", "буст",
    ],
    "result": [
        "победил", "выиграл", "проиграл", "счёт", "счет", "финал", "результат",
        "winner", "lost", "beat", "defeated", "knocked out", "вышел в финал",
        "прошёл", "выбыл", "eliminated", "advanced",
    ],
    "tournament": [
        "турнир", "tournament", "playoff", "плейофф", "grand final", "гранд финал",
        "группа", "group stage", "квалификация", "qualifier", "major", "мажор",
        "invited", "приглашены", "расписание", "schedule",
    ],
    "patch": [
        "патч", "patch", "обновление", "update", "нерф", "nerf", "баф", "buff",
        "изменения", "changes", "версия", "version",
    ],
    "analysis": [
        "прогноз", "prediction", "аналитика", "analytics", "ставка", "bet",
        "коэф", "odds", "разбор", "breakdown", "пик", "pick", "совет", "tip",
    ],
    "news": [
        "новость", "news", "объявил", "announced", "заявил", "сообщил",
        "по информации", "according to", "источник", "source",
    ],
}

# Слова-маркеры высокой важности
HIGH_IMPORTANCE_WORDS = [
    "трансфер", "transfer", "бан", "banned", "дисквалификация", "disqualified",
    "финал", "grand final", "major", "мажор", "чемпион", "champion",
    "распались", "disbanding", "новый состав", "roster",
]

# Минимальная длина сообщения для включения в дайджест
MIN_TEXT_LENGTH = 30


def classify_message(text: str) -> tuple[str, int]:
    """Определить категорию и важность сообщения (0=низкая, 1=средняя, 2=высокая)."""
    text_lower = text.lower()

    # Определяем категорию по приоритету
    category = "other"
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            category = cat
            break

    # Важность
    importance = 0
    if category in ("roster", "tournament"):
        importance = 1
    elif category == "result":
        importance = 1
    elif category in ("patch", "analysis", "news"):
        importance = 0

    # Повышаем если есть маркеры высокой важности
    if any(w in text_lower for w in HIGH_IMPORTANCE_WORDS):
        importance = 2

    return category, importance


def shorten_text(text: str, max_len: int = 220) -> str:
    """Обрезать текст до первых N символов, не разрывая слова."""
    text = text.strip().replace("\n\n\n", "\n\n")
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    last_space = max(cut.rfind(" "), cut.rfind("\n"))
    if last_space > max_len * 0.6:
        cut = cut[:last_space]
    return cut.rstrip() + "…"


# ───────────────────────────── Запросы к БД ─────────────────────────────

async def get_recent_messages(
    db: AsyncSession,
    game: str | None = None,
    hours: int = 24,
    limit: int = 200,
) -> list[TelegramMessage]:
    """Получить свежие сообщения из БД за последние N часов."""
    since = datetime.utcnow() - timedelta(hours=hours)

    filters = [TelegramMessage.posted_at >= since]
    if game:
        filters.append(
            or_(
                TelegramMessage.game == game,
                TelegramMessage.game == "both",
                TelegramMessage.game.is_(None),  # не определена — включаем
            )
        )

    result = await db.execute(
        select(TelegramMessage)
        .where(and_(*filters))
        .order_by(TelegramMessage.posted_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def get_team_news(
    db: AsyncSession,
    team_name: str,
    game: str | None = None,
    days: int = 5,
    limit: int = 5,
) -> list[TelegramMessage]:
    """Найти новости о конкретной команде за последние N дней."""
    since = datetime.utcnow() - timedelta(days=days)

    # Нормализуем имя команды для поиска
    name_lower = team_name.lower()
    # Берём первое слово (Team Spirit → spirit) и полное имя
    words = [w for w in name_lower.split() if len(w) > 2 and w not in ("team", "gaming", "esports")]
    search_term = words[0] if words else name_lower

    filters = [
        TelegramMessage.posted_at >= since,
        or_(
            TelegramMessage.text.ilike(f"%{search_term}%"),
            TelegramMessage.mentioned_teams.ilike(f"%{search_term}%"),
        ),
    ]
    if game:
        filters.append(
            or_(TelegramMessage.game == game, TelegramMessage.game.is_(None))
        )

    result = await db.execute(
        select(TelegramMessage)
        .where(and_(*filters))
        .order_by(TelegramMessage.posted_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def get_channel_count(db: AsyncSession) -> int:
    """Количество активных каналов."""
    result = await db.execute(
        select(TelegramChannel).where(TelegramChannel.is_active == True)
    )
    return len(result.scalars().all())


async def get_message_count(db: AsyncSession, hours: int = 24) -> int:
    """Количество сообщений за последние N часов."""
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(TelegramMessage).where(TelegramMessage.posted_at >= since)
    )
    return len(result.scalars().all())


# ───────────────────────────── Построение дайджеста ─────────────────────

CATEGORY_LABELS = {
    "roster":   "🔄 Трансферы / Составы",
    "result":   "🏆 Результаты",
    "tournament": "🎯 Турниры",
    "patch":    "🔧 Патчи / Обновления",
    "analysis": "📊 Аналитика / Прогнозы",
    "news":     "📰 Новости",
    "other":    "💬 Прочее",
}

CATEGORY_ORDER = ["roster", "tournament", "result", "patch", "analysis", "news", "other"]


def build_digest(
    messages: list[TelegramMessage],
    game: str | None = None,
    hours: int = 24,
    max_per_category: int = 4,
) -> list[str]:
    """
    Построить дайджест новостей.
    Возвращает список строк-частей для отправки в Telegram (уже разбито по длине).
    """
    if not messages:
        return [f"_Новостей за последние {hours}ч не найдено\\._\n_Каналы ещё не подключены или не активны\\._"]

    # Фильтруем короткие сообщения
    filtered = [m for m in messages if m.text and len(m.text.strip()) >= MIN_TEXT_LENGTH]

    if not filtered:
        return ["_Нет достаточно содержательных новостей\\._"]

    # Классифицируем
    categorized: dict[str, list[tuple[TelegramMessage, int]]] = {cat: [] for cat in CATEGORY_ORDER}
    for msg in filtered:
        cat, importance = classify_message(msg.text or "")
        if cat not in categorized:
            cat = "other"
        categorized[cat].append((msg, importance))

    # Сортируем внутри категории по важности, потом по дате
    for cat in categorized:
        categorized[cat].sort(key=lambda x: (-x[1], -(x[0].posted_at.timestamp() if x[0].posted_at else 0)))

    # Строим текст
    game_label = {"cs2": "CS2", "dota2": "Dota 2"}.get(game or "", "Все игры")
    now_str = datetime.utcnow().strftime("%d.%m %H:%M") + " UTC"

    parts = []
    current_lines: list[str] = [
        f"📰 *Дайджест новостей* — {_esc(game_label)}",
        f"_За последние {hours}ч \\| {now_str}_\n",
    ]

    has_any = False
    for cat in CATEGORY_ORDER:
        items = categorized[cat]
        if not items:
            continue

        # Берём топ N по важности
        top = items[:max_per_category]

        current_lines.append(f"*{_esc(CATEGORY_LABELS[cat])}*")

        for msg, imp in top:
            has_any = True
            channel = f"@{msg.channel_username}" if msg.channel_username else "—"
            date_str = msg.posted_at.strftime("%d.%m %H:%M") if msg.posted_at else "—"
            text_short = shorten_text(msg.text or "", 200)

            # Иконка важности
            icon = "🔴" if imp == 2 else ("🟡" if imp == 1 else "⚪")

            block = (
                f"{icon} `{_esc(date_str)}` {_esc(channel)}\n"
                f"{_esc(text_short)}\n"
            )
            current_lines.append(block)

            # Разбиваем по длине
            if len("\n".join(current_lines)) > 3400:
                parts.append("\n".join(current_lines))
                current_lines = []

        current_lines.append("")  # пустая строка между категориями

    if current_lines:
        parts.append("\n".join(current_lines))

    if not has_any:
        return [f"_Новостей за последние {hours}ч не найдено\\._"]

    return parts


def format_team_news(
    messages: list[TelegramMessage],
    team_name: str,
) -> str:
    """Форматировать новости о команде для показа в анализе матча."""
    if not messages:
        return ""

    lines = [f"📰 *Новости о {_esc(team_name)}:*"]
    for msg in messages[:3]:
        date_str = msg.posted_at.strftime("%d.%m") if msg.posted_at else "—"
        text_short = shorten_text(msg.text or "", 120)
        cat, _ = classify_message(msg.text or "")
        icon = {"roster": "🔄", "result": "🏆", "tournament": "🎯", "patch": "🔧"}.get(cat, "📌")
        lines.append(f"{icon} `{_esc(date_str)}` {_esc(text_short)}")

    return "\n".join(lines)


def _esc(text: str) -> str:
    """Экранирование для MarkdownV2."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text
