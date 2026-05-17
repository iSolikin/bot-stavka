"""
Хендлер новостного дайджеста.
Команда /news — показывает агрегированные новости из TG-каналов.
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from analyzer.news_analyzer import (
    get_recent_messages, build_digest, get_message_count, get_channel_count
)

logger = logging.getLogger(__name__)
news_router = Router()


def _news_keyboard(hours: int = 24) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎮 CS2", callback_data=f"news_cs2_{hours}"),
            InlineKeyboardButton(text="🐉 Dota2", callback_data=f"news_dota2_{hours}"),
            InlineKeyboardButton(text="🌐 Все", callback_data=f"news_all_{hours}"),
        ],
        [
            InlineKeyboardButton(text="⏰ 6ч", callback_data="news_all_6"),
            InlineKeyboardButton(text="⏰ 24ч", callback_data="news_all_24"),
            InlineKeyboardButton(text="⏰ 48ч", callback_data="news_all_48"),
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"news_all_{hours}"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
        ],
    ])


async def _send_news(
    db: AsyncSession,
    game: str | None,
    hours: int,
    respond_fn,
    edit_fn=None,
    keyboard=None,
):
    """Получить и отправить дайджест. respond_fn = message.answer, edit_fn = message.edit_text."""
    messages = await get_recent_messages(db, game=game, hours=hours, limit=300)
    parts = build_digest(messages, game=game, hours=hours)

    kb = keyboard or _news_keyboard(hours)

    if edit_fn:
        try:
            await edit_fn(parts[0], reply_markup=kb if len(parts) == 1 else None)
        except Exception:
            await respond_fn(parts[0], reply_markup=kb if len(parts) == 1 else None)
        for p in parts[1:]:
            await respond_fn(p, reply_markup=kb if p == parts[-1] else None)
    else:
        for i, p in enumerate(parts):
            await respond_fn(p, reply_markup=kb if i == len(parts) - 1 else None)


@news_router.message(Command("news"))
async def cmd_news(message: Message, db: AsyncSession):
    """
    /news — дайджест за 24ч
    /news cs2 — только CS2
    /news dota2 — только Dota2
    /news 6 — за 6 часов
    """
    args = (message.text or "").split()[1:]
    game = None
    hours = 24

    for arg in args:
        arg_low = arg.lower()
        if arg_low in ("cs2", "cs"):
            game = "cs2"
        elif arg_low in ("dota", "dota2", "d2"):
            game = "dota2"
        elif arg_low.isdigit():
            hours = max(1, min(int(arg_low), 168))  # 1-168 ч

    # Статистика каналов
    ch_count = await get_channel_count(db)
    msg_count = await get_message_count(db, hours=hours)

    if ch_count == 0:
        await message.answer(
            "⚠️ *Каналы не подключены*\n\n"
            "Добавь каналы через `/admin seed_channels` или `/admin add_channel @channel`",
        )
        return

    wait_msg = await message.answer(
        f"⏳ Собираю дайджест\\.\\.\\. "
        f"\\({msg_count} сообщений из {ch_count} каналов за {hours}ч\\)"
    )

    try:
        messages_db = await get_recent_messages(db, game=game, hours=hours, limit=300)
        parts = build_digest(messages_db, game=game, hours=hours)
        kb = _news_keyboard(hours)

        await wait_msg.delete()
        for i, p in enumerate(parts):
            await message.answer(p, reply_markup=kb if i == len(parts) - 1 else None)
    except Exception as ex:
        logger.error("cmd_news error: %s", ex, exc_info=True)
        await wait_msg.edit_text("❌ Ошибка при получении новостей\\. Попробуй позже\\.")


@news_router.callback_query(F.data.startswith("news_"))
async def cb_news(call: CallbackQuery, db: AsyncSession):
    """Фильтры дайджеста: news_cs2_24, news_all_6, и т.д."""
    await call.answer()
    parts_data = call.data.split("_")  # ["news", "cs2"|"dota2"|"all", "24"]

    if len(parts_data) < 3:
        return

    game_str = parts_data[1]
    hours_str = parts_data[2]

    game = None if game_str == "all" else game_str
    try:
        hours = int(hours_str)
    except ValueError:
        hours = 24

    await call.message.edit_text("⏳ Обновляю дайджест\\.\\.\\.")

    try:
        messages_db = await get_recent_messages(db, game=game, hours=hours, limit=300)
        parts = build_digest(messages_db, game=game, hours=hours)
        kb = _news_keyboard(hours)

        await call.message.edit_text(parts[0], reply_markup=kb if len(parts) == 1 else None)
        for p in parts[1:]:
            await call.message.answer(p, reply_markup=kb if p == parts[-1] else None)
    except Exception as ex:
        logger.error("cb_news error: %s", ex, exc_info=True)
        await call.message.edit_text("❌ Ошибка при обновлении дайджеста\\.")
