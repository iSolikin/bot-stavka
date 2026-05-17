"""
Предиктор рыночных маркетов для Dota 2 и CS2.

Маркеты Dota 2:
  - map_winner          — победитель карты
  - first_blood         — кто возьмёт первую кровь
  - total_kills         — тотал убийств (линии: 44.5, 47.5, 50.5, 53.5, 56.5, ...)
  - team_kills          — убийства команды (линии: 22.5, 25.5, 28.5, ...)
  - kill_handicap       — фора по убийствам (-7.5 / -5.5 / -3.5)
  - first_tower         — кто снесёт первую башню
  - total_towers        — тотал башен (линии: 10.5, 12.5, 14.5)
  - first_barracks      — кто снесёт первые казармы
  - megacreeps          — будут ли мегакрипы (да/нет)
  - total_roshans       — тотал рошанов (линии: 1.5, 2.5, 3.5)
  - roshan_race         — кто убьёт первого рошана

Маркеты CS2:
  - map_winner          — победитель карты
  - total_rounds        — тотал раундов (линии: 24.5, 26.5, 28.5, ...)
  - round_handicap      — фора по раундам (-3.5 / -5.5 / -7.5)
  - first_kill          — кто возьмёт первый килл на карте
  - pistol_rounds       — кто выиграет пистольные раунды (1-й и 16-й)

Для каждого маркета возвращается:
  {
    "market": "total_kills",
    "description": "Тотал убийств",
    "lines": [
      {"line": 50.5, "over_prob": 0.62, "under_prob": 0.38, "over_odds": 1.61, "under_odds": 2.63, "pick": "over"},
      ...
    ],
    "best_pick": {"line": 50.5, "side": "over", "prob": 0.62, "odds": 1.61},
    "avg_value": 52.3,
    "data_games": 15
  }
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MatchDetailStats, Team

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────

def _prob_to_odds(p: float) -> float:
    """Вероятность → честный коэффициент."""
    if p <= 0:
        return 99.0
    if p >= 1:
        return 1.0
    return round(1.0 / p, 2)


def _over_prob_normal(avg: float, std: float, line: float) -> float:
    """
    Вероятность превышения линии при нормальном распределении.
    P(X > line) используя приближение через erf.
    """
    if std <= 0:
        return 1.0 if avg > line else 0.0
    z = (line - avg) / (std * math.sqrt(2))
    return round((1 - math.erf(z)) / 2, 4)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return max(values[0] * 0.25, 5.0) if values else 5.0
    avg = sum(values) / len(values)
    variance = sum((x - avg) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _lines_for_avg(avg: float, step: float, count: int = 3) -> list[float]:
    """Генерируем линии вокруг среднего."""
    base = round(avg / step) * step - step
    return [round(base + step * i + 0.5, 1) for i in range(count)]


@dataclass
class MarketResult:
    market: str
    description: str
    avg_value: float | None
    data_games: int
    lines: list[dict] = field(default_factory=list)
    best_pick: dict | None = None
    team1_prob: float | None = None   # для бинарных маркетов (first_blood, winner)
    team2_prob: float | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "market": self.market,
            "description": self.description,
            "avg_value": round(self.avg_value, 1) if self.avg_value else None,
            "data_games": self.data_games,
            "lines": self.lines,
            "best_pick": self.best_pick,
        }
        if self.team1_prob is not None:
            d["team1_prob"] = round(self.team1_prob, 3)
            d["team2_prob"] = round(self.team2_prob, 3)
            d["team1_odds"] = _prob_to_odds(self.team1_prob)
            d["team2_odds"] = _prob_to_odds(self.team2_prob)
        if self.extra:
            d.update(self.extra)
        return d


# ──────────────────────────────────────────────────────────────
# Загрузка исторических данных
# ──────────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """Нормализуем имя команды для поиска."""
    n = name.lower().strip()
    for prefix in ("team ", "gaming ", "esports ", "club "):
        n = n.replace(prefix, "")
    return n


async def _get_team_stats(
    db: AsyncSession,
    team_name: str,
    game: str,
    days: int = 90,
    limit: int = 30,
) -> list[MatchDetailStats]:
    """Загружаем последние игры команды для аналитики."""
    since = datetime.utcnow() - timedelta(days=days)
    norm = _normalize(team_name)
    words = [w for w in norm.split() if len(w) > 2]
    search = words[0] if words else norm

    result = await db.execute(
        select(MatchDetailStats)
        .where(
            and_(
                MatchDetailStats.game == game,
                MatchDetailStats.match_date >= since,
                or_(
                    MatchDetailStats.team1_name.ilike(f"%{search}%"),
                    MatchDetailStats.team2_name.ilike(f"%{search}%"),
                ),
            )
        )
        .order_by(MatchDetailStats.match_date.desc())
        .limit(limit)
    )
    return result.scalars().all()


def _team_side(stat: MatchDetailStats, team_name: str) -> str:
    """Определяем за какую сторону играла команда (team1/team2)."""
    norm = _normalize(team_name)
    n1 = _normalize(stat.team1_name)
    n2 = _normalize(stat.team2_name)
    words = [w for w in norm.split() if len(w) > 2]
    search = words[0] if words else norm
    if search in n1:
        return "team1"
    return "team2"


# ──────────────────────────────────────────────────────────────
# Dota 2 маркеты
# ──────────────────────────────────────────────────────────────

def _build_total_market(
    values: list[float],
    market: str,
    description: str,
    step: float = 3.0,
    n_lines: int = 3,
) -> MarketResult:
    """Универсальный тотал-маркет."""
    if not values:
        return MarketResult(market=market, description=description,
                            avg_value=None, data_games=0)

    avg = sum(values) / len(values)
    std = _std(values)
    lines_raw = _lines_for_avg(avg, step, n_lines)

    lines_out = []
    for line in lines_raw:
        op = _over_prob_normal(avg, std, line)
        up = 1 - op
        lines_out.append({
            "line": line,
            "over_prob": round(op, 3),
            "under_prob": round(up, 3),
            "over_odds": _prob_to_odds(op),
            "under_odds": _prob_to_odds(up),
            "pick": "over" if op > 0.55 else ("under" if up > 0.55 else "skip"),
        })

    # Лучший пик — наибольший edge
    best = max(lines_out, key=lambda x: max(x["over_prob"], x["under_prob"]))
    if max(best["over_prob"], best["under_prob"]) < 0.55:
        best_pick = None
    else:
        side = "over" if best["over_prob"] > best["under_prob"] else "under"
        best_pick = {
            "line": best["line"],
            "side": side,
            "prob": best[f"{side}_prob"],
            "odds": best[f"{side}_odds"],
        }

    return MarketResult(
        market=market,
        description=description,
        avg_value=avg,
        data_games=len(values),
        lines=lines_out,
        best_pick=best_pick,
    )


def _build_binary_market(
    team1_rate: float,
    team1_name: str,
    team2_name: str,
    market: str,
    description: str,
    data_games: int,
) -> MarketResult:
    """Бинарный маркет (команда1 vs команда2)."""
    t1 = max(0.05, min(0.95, team1_rate))
    t2 = 1 - t1
    return MarketResult(
        market=market,
        description=description,
        avg_value=None,
        data_games=data_games,
        team1_prob=round(t1, 3),
        team2_prob=round(t2, 3),
        best_pick={
            "team": team1_name if t1 > t2 else team2_name,
            "prob": max(t1, t2),
            "odds": _prob_to_odds(max(t1, t2)),
        },
        extra={"team1_name": team1_name, "team2_name": team2_name},
    )


async def predict_dota2_markets(
    db: AsyncSession,
    team1_name: str,
    team2_name: str,
    team1_win_prob: float = 0.5,
) -> list[dict]:
    """Предсказания по всем Dota 2 маркетам."""
    stats1 = await _get_team_stats(db, team1_name, "dota2")
    stats2 = await _get_team_stats(db, team2_name, "dota2")
    all_stats = list({s.id: s for s in stats1 + stats2}.values())

    results = []

    # ── Тотал убийств ──────────────────────────────────────────
    kill_values = [s.total_kills for s in all_stats if s.total_kills is not None]
    results.append(
        _build_total_market(kill_values, "total_kills", "Тотал убийств", step=3.0, n_lines=4).to_dict()
    )

    # ── Убийства team1 ──────────────────────────────────────────
    t1_kills = []
    for s in stats1:
        side = _team_side(s, team1_name)
        val = s.team1_kills if side == "team1" else s.team2_kills
        if val is not None:
            t1_kills.append(float(val))
    results.append(
        _build_total_market(t1_kills, "team1_kills",
                            f"Убийства {team1_name}", step=2.0, n_lines=3).to_dict()
    )

    # ── Убийства team2 ──────────────────────────────────────────
    t2_kills = []
    for s in stats2:
        side = _team_side(s, team2_name)
        val = s.team1_kills if side == "team1" else s.team2_kills
        if val is not None:
            t2_kills.append(float(val))
    results.append(
        _build_total_market(t2_kills, "team2_kills",
                            f"Убийства {team2_name}", step=2.0, n_lines=3).to_dict()
    )

    # ── Фора убийств ────────────────────────────────────────────
    if t1_kills and t2_kills:
        avg1 = sum(t1_kills) / len(t1_kills)
        avg2 = sum(t2_kills) / len(t2_kills)
        diff = avg1 - avg2
        std1 = _std(t1_kills)
        std2 = _std(t2_kills)
        combined_std = math.sqrt(std1**2 + std2**2)

        handicap_lines = [-7.5, -5.5, -3.5, -1.5, 1.5, 3.5, 5.5, 7.5]
        # Выбираем линии вокруг среднего
        close_lines = sorted(handicap_lines, key=lambda x: abs(x - diff))[:4]
        close_lines.sort()

        hcap_lines = []
        for h in close_lines:
            # P(kills1 - kills2 > h) для team1
            p_t1 = _over_prob_normal(diff, combined_std, h)
            p_t2 = 1 - p_t1
            hcap_lines.append({
                "handicap": h,
                "team1_name": team1_name,
                "team2_name": team2_name,
                "team1_prob": round(p_t1, 3),
                "team2_prob": round(p_t2, 3),
                "team1_odds": _prob_to_odds(p_t1),
                "team2_odds": _prob_to_odds(p_t2),
            })

        results.append({
            "market": "kill_handicap",
            "description": "Фора убийств",
            "avg_diff": round(diff, 1),
            "data_games": min(len(t1_kills), len(t2_kills)),
            "team1_name": team1_name,
            "team2_name": team2_name,
            "lines": hcap_lines,
            "best_pick": None,
        })

    # ── Первая кровь ────────────────────────────────────────────
    t1_fb = sum(1 for s in stats1 if s.first_blood_team == _team_side(s, team1_name))
    fb_total = sum(1 for s in stats1 if s.first_blood_team is not None)
    if fb_total >= 3:
        fb_rate = t1_fb / fb_total
        results.append(
            _build_binary_market(fb_rate, team1_name, team2_name,
                                  "first_blood", "Первая кровь", fb_total).to_dict()
        )

    # ── Тотал башен ──────────────────────────────────────────
    tower_values = [s.total_towers for s in all_stats if s.total_towers is not None]
    results.append(
        _build_total_market(tower_values, "total_towers", "Тотал башен", step=2.0, n_lines=3).to_dict()
    )

    # ── Первая башня ─────────────────────────────────────────
    t1_ft = sum(1 for s in stats1 if s.first_tower_team == _team_side(s, team1_name))
    ft_total = sum(1 for s in stats1 if s.first_tower_team is not None)
    if ft_total >= 3:
        ft_rate = t1_ft / ft_total
        results.append(
            _build_binary_market(ft_rate, team1_name, team2_name,
                                  "first_tower", "Первая башня", ft_total).to_dict()
        )

    # ── Мегакрипы ────────────────────────────────────────────
    mega_values = [s.had_megacreeps for s in all_stats if s.had_megacreeps is not None]
    if mega_values:
        mega_rate = sum(mega_values) / len(mega_values)
        results.append({
            "market": "megacreeps",
            "description": "Будут мегакрипы",
            "avg_value": None,
            "data_games": len(mega_values),
            "yes_prob": round(mega_rate, 3),
            "no_prob": round(1 - mega_rate, 3),
            "yes_odds": _prob_to_odds(mega_rate),
            "no_odds": _prob_to_odds(1 - mega_rate),
            "best_pick": {
                "side": "yes" if mega_rate > 0.5 else "no",
                "prob": max(mega_rate, 1 - mega_rate),
                "odds": _prob_to_odds(max(mega_rate, 1 - mega_rate)),
            } if max(mega_rate, 1 - mega_rate) > 0.6 else None,
        })

    # ── Тотал рошанов ─────────────────────────────────────────
    roshan_values = [float(s.total_roshans) for s in all_stats if s.total_roshans is not None]
    results.append(
        _build_total_market(roshan_values, "total_roshans", "Тотал рошанов", step=1.0, n_lines=3).to_dict()
    )

    # ── Продолжительность (по минутам, как у букмекеров) ──────
    dur_values = [s.duration_seconds / 60 for s in all_stats if s.duration_seconds]
    if dur_values:
        avg_dur = sum(dur_values) / len(dur_values)
        std_dur = _std(dur_values)
        # Генерируем 5 линий вокруг среднего с шагом 1 минута
        base_min = max(25, int(avg_dur) - 2)
        dur_lines = []
        for minute in range(base_min, base_min + 5):
            op = _over_prob_normal(avg_dur, std_dur, minute)
            up = 1 - op
            dur_lines.append({
                "line": float(minute),
                "label": f"Больше {minute} минут",
                "over_prob": round(op, 3),
                "under_prob": round(up, 3),
                "over_odds": _prob_to_odds(op),
                "under_odds": _prob_to_odds(up),
                "pick": "over" if op > 0.6 else ("under" if up > 0.6 else "skip"),
            })
        results.append({
            "market": "duration",
            "description": "Продолжительность карты",
            "avg_value": round(avg_dur, 1),
            "data_games": len(dur_values),
            "lines": dur_lines,
            "best_pick": None,
            "format": "duration",
        })

    return [r for r in results if r.get("data_games", 0) > 0]


# ──────────────────────────────────────────────────────────────
# CS2 маркеты
# ──────────────────────────────────────────────────────────────

async def predict_cs2_markets(
    db: AsyncSession,
    team1_name: str,
    team2_name: str,
    team1_win_prob: float = 0.5,
) -> list[dict]:
    """Предсказания по всем CS2 маркетам."""
    stats1 = await _get_team_stats(db, team1_name, "cs2")
    stats2 = await _get_team_stats(db, team2_name, "cs2")
    all_stats = list({s.id: s for s in stats1 + stats2}.values())

    results = []

    # ── Тотал раундов ─────────────────────────────────────────
    round_values = [float(s.total_rounds) for s in all_stats if s.total_rounds is not None]
    results.append(
        _build_total_market(round_values, "total_rounds", "Тотал раундов", step=2.0, n_lines=4).to_dict()
    )

    # ── Раунды team1 ──────────────────────────────────────────
    t1_rounds = []
    for s in stats1:
        side = _team_side(s, team1_name)
        val = s.team1_rounds if side == "team1" else s.team2_rounds
        if val is not None:
            t1_rounds.append(float(val))
    results.append(
        _build_total_market(t1_rounds, "team1_rounds",
                            f"Раунды {team1_name}", step=1.5, n_lines=3).to_dict()
    )

    # ── Раунды team2 ──────────────────────────────────────────
    t2_rounds = []
    for s in stats2:
        side = _team_side(s, team2_name)
        val = s.team1_rounds if side == "team1" else s.team2_rounds
        if val is not None:
            t2_rounds.append(float(val))
    results.append(
        _build_total_market(t2_rounds, "team2_rounds",
                            f"Раунды {team2_name}", step=1.5, n_lines=3).to_dict()
    )

    # ── Фора раундов ──────────────────────────────────────────
    if t1_rounds and t2_rounds:
        avg1 = sum(t1_rounds) / len(t1_rounds)
        avg2 = sum(t2_rounds) / len(t2_rounds)
        diff = avg1 - avg2
        std1 = _std(t1_rounds)
        std2 = _std(t2_rounds)
        combined_std = math.sqrt(std1**2 + std2**2)

        handicap_lines = [-7.5, -5.5, -4.5, -3.5, -1.5, 1.5, 3.5, 4.5, 5.5, 7.5]
        close_lines = sorted(handicap_lines, key=lambda x: abs(x - diff))[:4]
        close_lines.sort()

        hcap_lines = []
        for h in close_lines:
            p_t1 = _over_prob_normal(diff, combined_std, h)
            hcap_lines.append({
                "handicap": h,
                "team1_name": team1_name,
                "team2_name": team2_name,
                "team1_prob": round(p_t1, 3),
                "team2_prob": round(1 - p_t1, 3),
                "team1_odds": _prob_to_odds(p_t1),
                "team2_odds": _prob_to_odds(1 - p_t1),
            })

        results.append({
            "market": "round_handicap",
            "description": "Фора раундов",
            "avg_diff": round(diff, 1),
            "data_games": min(len(t1_rounds), len(t2_rounds)),
            "team1_name": team1_name,
            "team2_name": team2_name,
            "lines": hcap_lines,
            "best_pick": None,
        })

    return [r for r in results if r.get("data_games", 0) > 0]


# ──────────────────────────────────────────────────────────────
# Главная точка входа
# ──────────────────────────────────────────────────────────────

async def predict_markets(
    db: AsyncSession,
    team1_name: str,
    team2_name: str,
    game: str,
    team1_win_prob: float = 0.5,
) -> dict[str, Any]:
    """
    Полный анализ по всем маркетам для матча.
    Возвращает dict с ключами markets, team1_name, team2_name, game, data_available.
    """
    if game == "dota2":
        markets = await predict_dota2_markets(db, team1_name, team2_name, team1_win_prob)
    elif game == "cs2":
        markets = await predict_cs2_markets(db, team1_name, team2_name, team1_win_prob)
    else:
        markets = []

    total_games = sum(m.get("data_games", 0) for m in markets)
    return {
        "team1_name": team1_name,
        "team2_name": team2_name,
        "game": game,
        "team1_win_prob": round(team1_win_prob, 3),
        "markets": markets,
        "data_available": total_games > 0,
        "total_data_games": total_games // max(len(markets), 1),
    }
