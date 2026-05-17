"""
Хендлеры для виртуальных ставок — демо-режим.
/demostats — сводная статистика по авто-ставкам бота.
/bets      — последние 10 ставок.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bets.virtual_bets import get_bet_stats, settle_pending_bets
from bot.formatters.telegram_format import escape_md as e, fmt_time
from bot.keyboards import back_to_menu
from db.models import VirtualBet

router = Router()


def _profit_emoji(profit: float) -> str:
    if profit > 0:
        return "🟢"
    if profit < 0:
        return "🔴"
    return "⚪"


def _format_stats(stats: dict) -> str:
    if stats.get("total", 0) == 0:
        return (
            "📊 *Демо\\-ставки бота*\n\n"
            "_Ставок пока нет\\._\n\n"
            "Ставки появляются автоматически при анализе матчей\\.\n"
            "Нажми любой матч в списке 👇"
        )

    total = stats["total"]
    won = stats["won"]
    lost = stats["lost"]
    pending = stats["pending"]
    void_ = stats.get("void", 0)
    settled = won + lost

    profit = stats["total_profit"]
    roi = stats["roi"]
    wr = stats["winrate"]

    profit_sign = "\\+" if profit >= 0 else ""
    profit_str = e(f"{profit_sign}{profit:.0f}")
    roi_sign = "\\+" if roi >= 0 else ""
    roi_str = e(f"{roi_sign}{roi:.1f}%")
    wr_str = e(f"{wr:.1f}%")

    p_emoji = _profit_emoji(profit)

    lines = [
        "📊 *Демо\\-ставки бота*",
        "",
        f"🎯 *Всего ставок:* {e(str(total))}",
        f"  ✅ Выиграно: *{e(str(won))}*",
        f"  ❌ Проиграно: *{e(str(lost))}*",
        f"  ⏳ Ожидает: *{e(str(pending))}*",
        *([ f"  ⚪ Void: {e(str(void_))}" ] if void_ else []),
        "",
        f"📈 *Результат* \\(с {e(str(settled))} ставок\\)",
        f"  Винрейт: *{wr_str}*",
        f"  P&L: {p_emoji} *{profit_str} ед\\.*",
        f"  ROI: *{roi_str}*",
        f"  Банк: *{e(str(100 * total + int(profit)))} ед\\.* \\(старт 100/ставка\\)",
    ]

    # По уверенности
    by_conf = stats.get("by_conf", {})
    if by_conf:
        lines.append("")
        lines.append("🔬 *По уверенности предиктора*")
        conf_labels = {"высокая": "🟢 Высокая", "средняя": "🟠 Средняя"}
        for conf, label in conf_labels.items():
            d = by_conf.get(conf)
            if d:
                cwr = round(d["won"] / d["total"] * 100, 1) if d["total"] else 0
                cp = d["profit"]
                cp_sign = "\\+" if cp >= 0 else ""
                lines.append(
                    f"  {e(label)}: {e(str(d['won']))}/{e(str(d['total']))} "
                    f"\\({e(f'{cwr:.0f}')}%\\) → {_profit_emoji(cp)} {e(f'{cp_sign}{cp:.0f}')}"
                )

    # По игре
    by_game = stats.get("by_game", {})
    if by_game:
        lines.append("")
        lines.append("🎮 *По игре*")
        for game, d in by_game.items():
            cwr = round(d["won"] / d["total"] * 100, 1) if d["total"] else 0
            cp = d["profit"]
            cp_sign = "\\+" if cp >= 0 else ""
            lines.append(
                f"  *{e(game.upper())}*: {e(str(d['won']))}/{e(str(d['total']))} "
                f"\\({e(f'{cwr:.0f}')}%\\) → {_profit_emoji(cp)} {e(f'{cp_sign}{cp:.0f}')}"
            )

    # Текущий стрик
    streak = stats.get("streak", 0)
    streak_type = stats.get("streak_type", "")
    if streak >= 2:
        s_emoji = "🔥" if streak_type == "won" else "💧"
        s_label = "выигрышей" if streak_type == "won" else "проигрышей"
        lines.append("")
        lines.append(f"{s_emoji} Серия: *{e(str(streak))} {e(s_label)} подряд*")

    lines.append("")
    lines.append("_Ставка фиксированная: 100 единиц_")
    lines.append("_Ставим при уверенности средняя/высокая_")

    return "\n".join(lines)


def _format_recent_bets(bets: list) -> str:
    if not bets:
        return "📋 *Последние ставки*\n\n_Ставок пока нет_"

    lines = ["📋 *Последние ставки*", ""]
    status_icons = {"won": "✅", "lost": "❌", "pending": "⏳", "void": "⚪"}

    for b in bets:
        icon = status_icons.get(b.status, "❓")
        date = fmt_time(b.created_at, "%d.%m") if b.created_at else "—"
        t1 = e(b.team1_name)
        t2 = e(b.team2_name)
        bet_team = e(b.bet_team_name)
        odds_str = e(f"{b.odds:.2f}")
        game_str = e(b.game.upper())

        line = f"{icon} *{bet_team}* @ {odds_str} \\| {t1} vs {t2} \\[{game_str}\\] {e(date)}"

        if b.status == "won":
            profit_str = e(f"+{b.profit:.0f}")
            line += f"\n   → 🟢 {profit_str} ед\\."
        elif b.status == "lost":
            line += f"\n   → 🔴 \\-{e(str(int(b.stake)))} ед\\."
        elif b.status == "pending":
            if b.actual_score:
                line += f"\n   → Счёт: {e(b.actual_score)}"
        lines.append(line)

    return "\n".join(lines)


@router.message(Command("demostats"))
async def cmd_demostats(message: Message, db: AsyncSession) -> None:
    # Сначала сводим pending-ставки
    try:
        settled = await settle_pending_bets(db)
        if settled:
            pass  # тихо сводим
    except Exception as ex:
        pass

    stats = await get_bet_stats(db)
    text = _format_stats(stats)
    await message.answer(text, reply_markup=back_to_menu())


@router.message(Command("bets"))
async def cmd_bets(message: Message, db: AsyncSession) -> None:
    result = await db.execute(
        select(VirtualBet)
        .where(VirtualBet.status != "void")
        .order_by(VirtualBet.created_at.desc())
        .limit(10)
    )
    bets = result.scalars().all()
    text = _format_recent_bets(bets)
    await message.answer(text, reply_markup=back_to_menu())


@router.callback_query(F.data == "demostats")
async def cb_demostats(call: CallbackQuery, db: AsyncSession) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    try:
        await settle_pending_bets(db)
    except Exception:
        pass
    stats = await get_bet_stats(db)
    text = _format_stats(stats)
    try:
        await call.message.edit_text(text, reply_markup=back_to_menu())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_menu())
