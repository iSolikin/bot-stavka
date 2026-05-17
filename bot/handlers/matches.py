import re
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from analyzer.analyzer import Analyzer
from cache.redis_cache import cache
from bot.formatters.telegram_format import split_message, fmt_time
from bot.keyboards import back_to_menu
from db.models import Match

router = Router()

GAME_ALIASES = {
    "cs": "cs2", "cs2": "cs2", "counter-strike": "cs2",
    "dota": "dota2", "dota2": "dota2", "d2": "dota2",
}


def _matches_keyboard(matches: list[dict], game: str) -> InlineKeyboardMarkup:
    """Кнопка на каждый матч."""
    buttons = []
    for m in matches:
        time_str = fmt_time(m["scheduled_at"]) if m.get("scheduled_at") else "—"
        label = f"{time_str} ⚔ {m['team1']} vs {m['team2']}"
        if len(label) > 60:
            label = label[:57] + "…"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"analyze_{m['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ В меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _show_match_list(game: str, db: AsyncSession, target) -> None:
    """Показать список матчей с кнопками."""
    analyzer = Analyzer(db)
    matches = await analyzer.matches_today(game)

    gl = game.upper()
    if not matches:
        from bot.formatters.telegram_format import escape_md as e
        text = f"📅 *Матчи {e(gl)}*\n\nНа ближайшие 36 часов матчей не найдено\\."
        kb = back_to_menu()
    else:
        text = f"📅 *Матчи {gl}* — выбери матч для анализа:\n\n_Время указано в UTC_"
        kb = _matches_keyboard(matches, game)

    if hasattr(target, "edit_text"):
        await target.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.message(Command("upcoming"))
async def cmd_upcoming(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    game = "cs2"
    if len(args) > 1:
        game = GAME_ALIASES.get(args[1].strip().lower(), "cs2")
    await _show_match_list(game, db, message)


@router.message(Command("match"))
async def cmd_match(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используй: `/match NaVi vs Vitality`")
        return

    query = args[1].strip()
    game = "cs2"
    for alias, g in GAME_ALIASES.items():
        if query.lower().endswith(alias):
            game = g
            query = query[: -len(alias)].strip()
            break

    vs_match = re.split(r"\s+vs\.?\s+", query, flags=re.IGNORECASE)
    if len(vs_match) < 2:
        await message.answer("Формат: `/match NaVi vs Vitality`")
        return

    team1, team2 = vs_match[0].strip(), vs_match[1].strip()
    await message.answer("🔍 Анализирую матч, подожди немного…")

    cached = await cache.get_match_report(team1, team2, game)
    if cached:
        for part in split_message(cached):
            await message.answer(part, reply_markup=back_to_menu())
        return

    analyzer = Analyzer(db)
    report = await analyzer.full_match_analysis(team1, team2, game)
    await cache.set_match_report(team1, team2, game, report)
    for part in split_message(report):
        await message.answer(part, reply_markup=back_to_menu())


# --- Callbacks ---

@router.callback_query(F.data == "upcoming_cs2")
async def cb_upcoming_cs2(call: CallbackQuery, db: AsyncSession) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await _show_match_list("cs2", db, call.message)


@router.callback_query(F.data == "upcoming_dota2")
async def cb_upcoming_dota2(call: CallbackQuery, db: AsyncSession) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await _show_match_list("dota2", db, call.message)


@router.callback_query(F.data.startswith("analyze_"))
async def cb_analyze_match(call: CallbackQuery, db: AsyncSession) -> None:
    try:
        await call.answer("Анализирую…")
    except Exception:
        pass

    match_id_str = call.data.replace("analyze_", "")
    try:
        match_id = int(match_id_str)
    except ValueError:
        await call.message.answer("Ошибка: неверный ID матча")
        return

    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        await call.message.answer("Матч не найден в базе\\.")
        return

    from bot.formatters.telegram_format import escape_md as e
    await call.message.edit_text(
        f"🔍 Анализирую *{e(match.team1_name)}* vs *{e(match.team2_name)}*…\n_Это займёт несколько секунд_"
    )

    cached = await cache.get_match_report(match.team1_name, match.team2_name, match.game)
    if cached:
        report = cached
    else:
        analyzer = Analyzer(db)
        report = await analyzer.full_match_analysis(match.team1_name, match.team2_name, match.game, match_id)
        await cache.set_match_report(match.team1_name, match.team2_name, match.game, report)

    parts = split_message(report)
    for i, part in enumerate(parts):
        kb = back_to_menu() if i == len(parts) - 1 else None
        if i == 0:
            await call.message.edit_text(part, reply_markup=kb)
        else:
            await call.message.answer(part, reply_markup=kb)
