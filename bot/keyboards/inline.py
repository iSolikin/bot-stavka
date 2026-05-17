"""
Инлайн-клавиатуры для бота.
"""
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# --- CallbackData классы ---

class UpcomingCallback(CallbackData, prefix="upcoming"):
    game: str


class TeamCallback(CallbackData, prefix="team"):
    name: str
    game: str


class MatchCallback(CallbackData, prefix="match"):
    team1: str
    team2: str
    game: str


class SubCallback(CallbackData, prefix="sub"):
    action: str   # "sub" или "unsub"
    team: str     # нормализованное имя
    game: str


# --- Фабрики клавиатур ---

def upcoming_keyboard(game: str) -> InlineKeyboardMarkup:
    """Кнопки под /upcoming: переключение игры и обновление."""
    builder = InlineKeyboardBuilder()
    other_game = "dota2" if game == "cs2" else "cs2"
    other_label = "Dota2" if game == "cs2" else "CS2"

    builder.button(
        text=f"🔄 Обновить",
        callback_data=UpcomingCallback(game=game),
    )
    builder.button(
        text=f"🎮 Переключить на {other_label}",
        callback_data=UpcomingCallback(game=other_game),
    )
    builder.adjust(1)
    return builder.as_markup()


def team_keyboard(team_name: str, game: str, is_subscribed: bool = False) -> InlineKeyboardMarkup:
    """Кнопки под /team: обновление и подписка."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔄 Обновить",
        callback_data=TeamCallback(name=team_name, game=game),
    )

    if is_subscribed:
        builder.button(
            text="🔕 Отписаться",
            callback_data=SubCallback(action="unsub", team=team_name, game=game),
        )
    else:
        builder.button(
            text="🔔 Подписаться на матчи",
            callback_data=SubCallback(action="sub", team=team_name, game=game),
        )

    builder.adjust(1)
    return builder.as_markup()


def match_keyboard(team1: str, team2: str, game: str) -> InlineKeyboardMarkup:
    """Кнопки под /match: обновление и ссылки на команды."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔄 Обновить",
        callback_data=MatchCallback(team1=team1, team2=team2, game=game),
    )
    builder.button(
        text=f"📊 {team1}",
        callback_data=TeamCallback(name=team1, game=game),
    )
    builder.button(
        text=f"📊 {team2}",
        callback_data=TeamCallback(name=team2, game=game),
    )
    builder.adjust(1, 2)
    return builder.as_markup()
