from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Матчи CS2", callback_data="upcoming_cs2"),
            InlineKeyboardButton(text="📅 Матчи Dota2", callback_data="upcoming_dota2"),
        ],
        [
            InlineKeyboardButton(text="🔮 Предикты на сегодня", callback_data="today_all"),
        ],
        [
            InlineKeyboardButton(text="📰 Новости", callback_data="news_all_24"),
            InlineKeyboardButton(text="💰 Демо-ставки", callback_data="demostats"),
        ],
        [
            InlineKeyboardButton(text="❓ Помощь", callback_data="help"),
        ],
    ])


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ В меню", callback_data="back_main"),
        ],
    ])
