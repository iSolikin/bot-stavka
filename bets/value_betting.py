"""
Value-betting движок.

Идея: ставим не на «фаворита», а только когда НАША вероятность исхода выше
справедливой вероятности рынка (кэфа букмекера) — то есть когда у нас есть
математический перевес (edge). Размер ставки считаем по дробному критерию
Келли от текущего банка.

Формулы:
  implied_prob(odds)        = 1 / odds                  (вероятность из кэфа с маржой)
  fair (де-виг)             = p_i / (p1 + p2)           (убираем маржу букмекера)
  edge                      = our_prob - market_prob
  Kelly f*                  = (b*p - (1-p)) / b,  b = odds - 1
  stake                     = bank * f* * KELLY_FRACTION  (с потолком MAX_STAKE_PCT)
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.models import VirtualBet

logger = logging.getLogger(__name__)


def implied_prob(odds: float | None) -> float:
    """Вероятность, зашитая в кэф (с маржой букмекера)."""
    if not odds or odds <= 1.0:
        return 0.0
    return 1.0 / odds


def remove_vig_two_way(odds1: float, odds2: float) -> tuple[float, float] | tuple[None, None]:
    """Убрать маржу из пары кэфов -> справедливые вероятности обоих исходов."""
    p1, p2 = implied_prob(odds1), implied_prob(odds2)
    s = p1 + p2
    if s <= 0:
        return None, None
    return p1 / s, p2 / s


def kelly_fraction(prob: float, odds: float) -> float:
    """Доля банка по полному критерию Келли (0..1). Отрицательную обрезаем в 0."""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    f = (b * prob - (1.0 - prob)) / b
    return max(0.0, f)


def evaluate_bet(
    our_prob: float,
    odds: float,
    bankroll: float,
    opp_odds: float | None = None,
) -> dict | None:
    """
    Оценить ставку. Возвращает {edge, market_prob, kelly, stake} если ставка
    имеет перевес (value), иначе None.

    our_prob — наша вероятность исхода (0..1)
    odds     — кэф букмекера на этот исход
    opp_odds — кэф на противоположный исход (для де-вига; опционально)
    """
    if not odds or odds <= 1.0 or our_prob <= 0:
        return None

    # Справедливая вероятность рынка
    if opp_odds and opp_odds > 1.0:
        fair, _ = remove_vig_two_way(odds, opp_odds)
        market_prob = fair if fair is not None else implied_prob(odds)
    else:
        market_prob = implied_prob(odds)

    edge = our_prob - market_prob
    if edge < config.MIN_EDGE:
        return None

    kf = kelly_fraction(our_prob, odds) * config.KELLY_FRACTION
    if kf <= 0:
        return None

    stake = bankroll * kf
    stake = min(stake, bankroll * config.MAX_STAKE_PCT)
    if stake < config.MIN_STAKE:
        return None

    return {
        "edge": round(edge, 4),
        "market_prob": round(market_prob, 4),
        "kelly": round(kf, 4),
        "stake": round(stake, 2),
    }


async def current_bankroll(db: AsyncSession) -> float:
    """Текущий банк = стартовый + прибыль/убыток по сведённым ставкам."""
    res = await db.execute(select(VirtualBet))
    bets = res.scalars().all()
    profit = sum(
        b.profit for b in bets
        if b.profit is not None and b.status in ("won", "lost")
    )
    return float(config.INITIAL_BANK) + float(profit)
