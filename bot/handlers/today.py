"""
Команда /today — показывает предикты бота на все матчи сегодня/ближайшие 36 часов.
Бот анализирует каждый матч по статистике из БД и делает виртуальную ставку.
"""
import asyncio
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from analyzer.daily_analysis import analyze_all_today, format_daily_report
from bot.formatters.telegram_format import escape_md as e, split_message
from bot.keyboards import back_to_menu

router = Router()


def _today_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎮 CS2", callback_data="today_cs2"),
            InlineKeyboardButton(text="🎮 Dota2", callback_data="today_dota2"),
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="today_all"),
            InlineKeyboardButton(text="◀️ В меню", callback_data="back_main"),
        ],
    ])


async def _run_and_send(target, db: AsyncSession, game_filter: str | None = None) -> None:
    """Запустить анализ и отправить результат."""
    is_message = hasattr(target, "answer") and not hasattr(target, "message")

    # Отправляем сообщение "думаю..."
    hint = "⏳ Анализирую все матчи\\.\\.\\. _это займёт несколько секунд_"
    if is_message:
        thinking = await target.answer(hint)
    else:
        try:
            await target.message.edit_text(hint)
        except Exception:
            pass

    # Запускаем анализ
    results = await analyze_all_today(db)

    # Форматируем
    parts = format_daily_report(results, game_filter=game_filter)

    total = len(results)
    new_bets = sum(1 for r in results if r.get("bet_placed"))
    header_game = f" \\[{e(game_filter.upper())}\\]" if game_filter else ""
    header = (
        f"📊 *Предикты бота на сегодня*{header_game}\n"
        f"Матчей: *{e(str(total))}* \\| Новых ставок: *{e(str(new_bets))}*\n\n"
    )
    parts[0] = header + parts[0]

    kb = _today_keyboard()

    if is_message:
        # Удаляем "думаю..." и шлём результаты
        try:
            await thinking.delete()
        except Exception:
            pass
        for i, part in enumerate(parts):
            await target.answer(part, reply_markup=kb if i == len(parts) - 1 else None)
    else:
        # callback — редактируем первое, досылаем остальные
        try:
            await target.message.edit_text(parts[0], reply_markup=kb if len(parts) == 1 else None)
        except Exception:
            await target.message.answer(parts[0])
        for i, part in enumerate(parts[1:], 1):
            await target.message.answer(part, reply_markup=kb if i == len(parts) - 1 else None)


@router.message(Command("today"))
async def cmd_today(message: Message, db: AsyncSession) -> None:
    await _run_and_send(message, db)


@router.callback_query(F.data == "today_all")
async def cb_today_all(call: CallbackQuery, db: AsyncSession) -> None:
    try:
        await call.answer("Обновляю предикты...")
    except Exception:
        pass
    await _run_and_send(call, db)


@router.callback_query(F.data == "today_cs2")
async def cb_today_cs2(call: CallbackQuery, db: AsyncSession) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await _run_and_send(call, db, game_filter="cs2")


@router.callback_query(F.data == "today_dota2")
async def cb_today_dota2(call: CallbackQuery, db: AsyncSession) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await _run_and_send(call, db, game_filter="dota2")
