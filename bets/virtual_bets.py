"""
Виртуальные ставки — демо-режим для оценки точности предиктора.

Бот автоматически ставит 100 виртуальных единиц на победителя каждого
проанализированного матча (только при уверенности средняя/высокая).
Ставки сводятся автоматически по результатам из OpenDota/HLTV.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from db.models import Match, VirtualBet

logger = logging.getLogger(__name__)

# Фиксированная ставка-фолбэк (когда нет реальных кэфов для value-расчёта)
from config import config as _cfg
STAKE = _cfg.FLAT_STAKE


async def place_auto_bet(
    db: AsyncSession,
    match_id: int | None,
    team1: str,
    team2: str,
    game: str,
    tournament: str | None,
    scheduled_at: datetime | None,
    pred,           # Prediction dataclass из predictor.py
    bookmaker_odds1: float | None = None,
    bookmaker_odds2: float | None = None,
) -> VirtualBet | None:
    """Поставить виртуальную ставку на основе предикта.

    Ставим только при уверенности 'средняя' или 'высокая'.
    Используем кэфы букмекера если есть, иначе считаем из вероятности.
    Возвращает созданную ставку или None если ставка не нужна.
    """
    # Ставим только при средней или высокой уверенности
    if pred.confidence == "низкая":
        logger.debug("VirtualBet: skip low-confidence match %s vs %s", team1, team2)
        return None

    # Не ставим дважды на один матч
    if match_id:
        existing = await db.execute(
            select(VirtualBet).where(VirtualBet.match_id == match_id)
        )
        if existing.scalar_one_or_none():
            logger.debug("VirtualBet: already have bet for match_id=%s", match_id)
            return None

    # Определяем на кого ставим
    t1_low = team1.lower()
    winner_low = pred.winner.lower()
    is_team1 = (winner_low in t1_low or t1_low in winner_low)

    if is_team1:
        bet_on = "team1"
        bet_team = team1
        prob = pred.team1_prob
        bk_odds = bookmaker_odds1
        opp_odds = bookmaker_odds2
    else:
        bet_on = "team2"
        bet_team = team2
        prob = pred.team2_prob
        bk_odds = bookmaker_odds2
        opp_odds = bookmaker_odds1

    from bets.value_betting import evaluate_bet, current_bankroll

    have_real_odds = bool(bk_odds and bk_odds >= 1.05)

    if have_real_odds:
        # VALUE-РЕЖИМ: ставим только при перевесе, размер по Келли
        odds = round(bk_odds, 2)
        bankroll = await current_bankroll(db)
        verdict = evaluate_bet(prob, odds, bankroll, opp_odds=opp_odds)
        if verdict is None:
            logger.info(
                "VirtualBet: no value %s vs %s (our %.0f%% vs odds %.2f) — skip",
                team1, team2, prob * 100, odds,
            )
            return None
        stake = verdict["stake"]
        edge = verdict["edge"]
    else:
        # FALLBACK: реальных кэфов нет → флэт-ставка по уверенности предиктора
        odds = round(1.0 / max(prob, 0.05), 2)
        odds = max(1.05, min(odds, 15.0))
        stake = STAKE
        edge = None

    bet = VirtualBet(
        match_id=match_id,
        team1_name=team1,
        team2_name=team2,
        game=game,
        tournament=tournament,
        scheduled_at=scheduled_at,
        bet_on=bet_on,
        bet_team_name=bet_team,
        pred_prob=round(prob, 3),
        confidence=pred.confidence,
        odds=odds,
        stake=round(stake, 2),
        edge=edge,
        status="pending",
    )
    db.add(bet)
    await db.commit()
    logger.info(
        "VirtualBet placed: %s vs %s → %s @ %.2f stake=%.0f%s [%s]",
        team1, team2, bet_team, odds, stake,
        f" edge={edge*100:.1f}%" if edge is not None else " (flat)",
        pred.confidence,
    )
    return bet


async def settle_pending_bets(db: AsyncSession) -> int:
    """Свести все pending-ставки у которых уже есть результат.

    Ищет завершённые матчи между теми же командами после времени ставки,
    агрегирует карты в серию и определяет победителя.
    Возвращает количество сведённых ставок.
    """
    result = await db.execute(
        select(VirtualBet).where(VirtualBet.status == "pending")
    )
    pending = result.scalars().all()

    if not pending:
        return 0

    now = datetime.utcnow()
    settled = 0

    for bet in pending:
        # Матч ещё не начался — пропускаем
        if bet.scheduled_at and bet.scheduled_at > now:
            continue

        sched = bet.scheduled_at or bet.created_at

        # Ищем finished-матчи между этими командами
        norm1 = bet.team1_name.lower()
        norm2 = bet.team2_name.lower()
        # Берём окно ±12 часов от scheduled_at чтобы поймать серию
        from_time = sched - timedelta(hours=12)
        until_time = sched + timedelta(hours=36)

        maps_result = await db.execute(
            select(Match).where(
                and_(
                    Match.game == bet.game,
                    Match.status == "finished",
                    Match.scheduled_at >= from_time,
                    Match.scheduled_at <= until_time,
                    or_(
                        and_(
                            Match.team1_name.ilike(f"%{norm1}%"),
                            Match.team2_name.ilike(f"%{norm2}%"),
                        ),
                        and_(
                            Match.team1_name.ilike(f"%{norm2}%"),
                            Match.team2_name.ilike(f"%{norm1}%"),
                        ),
                    ),
                )
            ).order_by(Match.scheduled_at)
        )
        maps = maps_result.scalars().all()

        if not maps:
            # Нет результата — ждём минимум 2 часа после начала,
            # или ставим void если прошло >48 ч
            elapsed = (now - sched).total_seconds()
            if elapsed < 7_200:
                continue
            if elapsed > 172_800:  # 48 часов
                bet.status = "void"
                bet.settled_at = now
                bet.profit = 0.0
                settled += 1
            continue

        # Агрегируем карты в серию
        # Определяем "эталонную" team1 по первой записи
        ref_t1 = maps[0].team1_name.lower()
        ref_is_bet_t1 = (norm1 in ref_t1 or ref_t1 in norm1)

        score_ref = 0    # счёт для ref_t1
        score_opp = 0
        for m in maps:
            s1 = m.score_team1 or 0
            s2 = m.score_team2 or 0
            if m.team1_name.lower() == ref_t1:
                score_ref += s1
                score_opp += s2
            else:
                score_ref += s2
                score_opp += s1

        # Переводим в счёт bet.team1 vs bet.team2
        if ref_is_bet_t1:
            score1, score2 = score_ref, score_opp
        else:
            score1, score2 = score_opp, score_ref

        if score1 == score2:
            # Ничья (не бывает в киберспорте, но на всякий случай — void)
            bet.status = "void"
            bet.profit = 0.0
        else:
            team1_won = score1 > score2
            bet_won = (
                (bet.bet_on == "team1" and team1_won)
                or (bet.bet_on == "team2" and not team1_won)
            )
            bet.status = "won" if bet_won else "lost"
            bet.profit = round(bet.stake * (bet.odds - 1), 2) if bet_won else -bet.stake

        bet.actual_score = f"{score1}:{score2}"
        bet.settled_at = now
        settled += 1

    if settled:
        await db.commit()
        logger.info("VirtualBets settled: %d", settled)

    return settled


async def get_bet_stats(db: AsyncSession) -> dict:
    """Получить сводную статистику по виртуальным ставкам."""
    result = await db.execute(select(VirtualBet))
    bets = result.scalars().all()

    total = len(bets)
    if total == 0:
        return {"total": 0}

    won = [b for b in bets if b.status == "won"]
    lost = [b for b in bets if b.status == "lost"]
    pending = [b for b in bets if b.status == "pending"]
    void_ = [b for b in bets if b.status == "void"]

    settled = won + lost
    total_staked = sum(b.stake for b in settled)
    total_profit = sum(b.profit for b in settled if b.profit is not None)
    roi = (total_profit / total_staked * 100) if total_staked > 0 else 0.0
    winrate = (len(won) / len(settled) * 100) if settled else 0.0

    # По уверенности предиктора
    by_conf: dict[str, dict] = {}
    for conf in ("высокая", "средняя"):
        sub = [b for b in settled if b.confidence == conf]
        if sub:
            w = sum(1 for b in sub if b.status == "won")
            p = sum(b.profit for b in sub if b.profit is not None)
            by_conf[conf] = {"total": len(sub), "won": w, "profit": round(p, 2)}

    # По играм
    by_game: dict[str, dict] = {}
    for game in ("cs2", "dota2"):
        sub = [b for b in settled if b.game == game]
        if sub:
            w = sum(1 for b in sub if b.status == "won")
            p = sum(b.profit for b in sub if b.profit is not None)
            by_game[game] = {"total": len(sub), "won": w, "profit": round(p, 2)}

    # Последние 10 ставок (любой статус кроме void)
    recent = sorted(
        [b for b in bets if b.status != "void"],
        key=lambda b: b.created_at,
        reverse=True,
    )[:10]

    # Серия: текущий streak
    streak = 0
    streak_type = ""
    for b in sorted(won + lost, key=lambda b: b.settled_at or datetime.min, reverse=True):
        if not streak_type:
            streak_type = b.status
        if b.status == streak_type:
            streak += 1
        else:
            break

    return {
        "total": total,
        "won": len(won),
        "lost": len(lost),
        "pending": len(pending),
        "void": len(void_),
        "total_staked": round(total_staked, 2),
        "total_profit": round(total_profit, 2),
        "roi": round(roi, 1),
        "winrate": round(winrate, 1),
        "by_conf": by_conf,
        "by_game": by_game,
        "recent": recent,
        "streak": streak,
        "streak_type": streak_type,
    }
