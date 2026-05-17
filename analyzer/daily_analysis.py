"""
Массовый анализ всех матчей на сегодня/ближайшие 36 часов.
Запускается автоматически при старте бота и через /today.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from db.models import Match, VirtualBet
from analyzer.analyzer import Analyzer

logger = logging.getLogger(__name__)


async def analyze_all_today(db: AsyncSession) -> list[dict]:
    """Пробежать по всем матчам на ближайшие 36 часов, сделать предикты, поставить ставки.

    Возвращает список результатов:
    [{
        "match_id": int,
        "team1": str, "team2": str, "game": str,
        "tournament": str, "scheduled_at": datetime,
        "pred": Prediction,
        "t1_form": str, "t2_form": str,
        "t1_rating": float|None, "t2_rating": float|None,
        "bet_placed": bool,
        "already_analyzed": bool,
    }]
    """
    now = datetime.utcnow()
    until = now + timedelta(hours=36)
    from_time = now - timedelta(hours=3)  # включаем live

    result = await db.execute(
        select(Match).where(
            and_(
                Match.status.in_(["upcoming", "live"]),
                Match.scheduled_at >= from_time,
                Match.scheduled_at <= until,
            )
        ).order_by(Match.scheduled_at)
    )
    matches = result.scalars().all()

    if not matches:
        logger.info("daily_analysis: no matches found for next 36h")
        return []

    logger.info("daily_analysis: analyzing %d matches", len(matches))

    # Матчи у которых уже есть ставка — не анализируем повторно
    existing_bets_result = await db.execute(
        select(VirtualBet.match_id).where(VirtualBet.status == "pending")
    )
    already_bet_ids = {row[0] for row in existing_bets_result.fetchall() if row[0]}

    analyzer = Analyzer(db)
    results = []

    for m in matches:
        # Пропускаем TBD и неизвестных участников
        if not m.team1_name or not m.team2_name:
            continue
        if "TBD" in (m.team1_name.upper(), m.team2_name.upper()):
            continue

        already = m.id in already_bet_ids
        try:
            pred, report = await analyzer.quick_predict(
                team1=m.team1_name,
                team2=m.team2_name,
                game=m.game,
                match_id=m.id,
                scheduled_at=m.scheduled_at,
                tournament=m.tournament,
            )

            t1 = report.team1_stats
            t2 = report.team2_stats

            results.append({
                "match_id": m.id,
                "team1": m.team1_name,
                "team2": m.team2_name,
                "game": m.game,
                "tournament": m.tournament,
                "scheduled_at": m.scheduled_at,
                "status": m.status,
                "pred": pred,
                "t1_form": t1.form if t1 else "—",
                "t2_form": t2.form if t2 else "—",
                "t1_rating": t1.rating if t1 else None,
                "t2_rating": t2.rating if t2 else None,
                "h2h_count": len(report.head_to_head),
                "bet_placed": not already,  # поставили ставку сейчас
                "already_analyzed": already,
            })

        except Exception as ex:
            logger.warning("daily_analysis: error on %s vs %s: %s", m.team1_name, m.team2_name, ex)
            continue

    bets_new = sum(1 for r in results if r["bet_placed"])
    logger.info("daily_analysis: done %d matches, %d new bets placed", len(results), bets_new)
    return results


def format_daily_report(results: list[dict], game_filter: str | None = None) -> list[str]:
    """Форматировать результаты анализа в Telegram MarkdownV2.
    Возвращает список частей (split_message уже применён внутри).
    """
    from bot.formatters.telegram_format import escape_md as e, fmt_time

    if game_filter:
        results = [r for r in results if r["game"] == game_filter]

    if not results:
        return ["_Матчей не найдено\\._"]

    conf_emoji = {"низкая": "🟡", "средняя": "🟠", "высокая": "🟢"}
    bet_icons = {"won": "✅", "lost": "❌", "pending": "💰", "void": "⚪"}

    # Группируем по игре
    cs2 = [r for r in results if r["game"] == "cs2"]
    dota = [r for r in results if r["game"] == "dota2"]

    parts = []
    current = []

    def flush(force=False):
        nonlocal current
        text = "\n".join(current)
        if len(text) > 3800 or force:
            parts.append(text)
            current = []

    for game_label, game_results in [("CS2", cs2), ("Dota2", dota)]:
        if not game_results:
            continue

        current.append(f"🎮 *{game_label}* — {e(str(len(game_results)))} матчей\n")

        prev_tournament = None
        for r in game_results:
            p = r["pred"]
            conf = p.confidence
            c_emoji = conf_emoji.get(conf, "⚪")

            tournament = r.get("tournament") or "Без турнира"
            if tournament != prev_tournament:
                current.append(f"🏆 _{e(tournament)}_")
                prev_tournament = tournament

            # Время
            sched = r.get("scheduled_at")
            is_live = r.get("status") == "live"
            if is_live:
                time_str = "🔴 LIVE"
            else:
                time_str = e(fmt_time(sched)) + " ЕКБ" if sched else "—"

            t1 = e(r["team1"])
            t2 = e(r["team2"])
            winner = e(p.winner)
            p1pct = e(f"{p.team1_prob * 100:.0f}")
            p2pct = e(f"{p.team2_prob * 100:.0f}")

            # Форма
            f1 = e(r.get("t1_form") or "—")
            f2 = e(r.get("t2_form") or "—")

            # Ставка
            bet_icon = "💰" if r.get("bet_placed") else ("🔄" if r.get("already_analyzed") else "")

            line = (
                f"{time_str}\n"
                f"⚔️ *{t1}* vs *{t2}*\n"
                f"  Форма: `{f1}` vs `{f2}`\n"
                f"  {c_emoji} Победитель: *{winner}* \\({p1pct}% / {p2pct}%\\) {bet_icon}\n"
            )
            current.append(line)

            # Сбрасываем часть если накопилось много
            text_so_far = "\n".join(current)
            if len(text_so_far) > 3500:
                parts.append(text_so_far)
                current = []

        current.append("")

    if current:
        parts.append("\n".join(current))

    return parts if parts else ["_Нет данных_"]
