"""
Алгоритм предикта победителя на основе статистики.
Использует форму, рейтинг и H2H. Никаких магических чисел — только данные.
"""
from dataclasses import dataclass


@dataclass
class Prediction:
    winner: str
    team1: str
    team2: str
    team1_prob: float   # 0.0 — 1.0
    team2_prob: float
    confidence: str     # "низкая" / "средняя" / "высокая"
    reasoning: list[str]


def _form_score(form: str) -> float:
    """WWLWW → число от 0 до 1. Последние матчи весят больше."""
    if not form or form == "—":
        return 0.5
    weights = [1.0, 0.85, 0.7, 0.55, 0.4]
    total_weight = 0.0
    score = 0.0
    for i, ch in enumerate(form[:5]):
        w = weights[i] if i < len(weights) else 0.3
        total_weight += w
        if ch == "W":
            score += w
    return score / total_weight if total_weight > 0 else 0.5


def _h2h_score(h2h_matches: list[dict], team1_name: str) -> tuple[float, float]:
    """Считает H2H в пользу team1 vs team2."""
    if not h2h_matches:
        return 0.5, 0.5
    t1_wins = 0
    t2_wins = 0
    for m in h2h_matches[:10]:
        score = m.get("score", "0:0")
        try:
            s1, s2 = map(int, score.split(":"))
        except Exception:
            continue
        name1 = m.get("team1", "").lower()
        is_t1 = team1_name.lower() in name1 or name1 in team1_name.lower()
        if is_t1:
            if s1 > s2:
                t1_wins += 1
            else:
                t2_wins += 1
        else:
            if s2 > s1:
                t1_wins += 1
            else:
                t2_wins += 1
    total = t1_wins + t2_wins
    if total == 0:
        return 0.5, 0.5
    return t1_wins / total, t2_wins / total


def _rating_score(rating1: float | None, rating2: float | None) -> tuple[float, float]:
    """ELO-формула: вероятность победы по разнице рейтингов."""
    if rating1 is None and rating2 is None:
        return 0.5, 0.5
    r1 = rating1 if rating1 is not None else 1500.0
    r2 = rating2 if rating2 is not None else 1500.0
    p1 = 1.0 / (1.0 + 10 ** ((r2 - r1) / 400.0))
    return p1, 1.0 - p1


def _news_adjustment(events: list) -> tuple[float, list[str]]:
    """
    Считает суммарный сдвиг вероятности из NewsEvent-объектов или словарей.
    Возвращает (adjustment_float, reasoning_lines).
    """
    if not events:
        return 0.0, []

    total = 0.0
    notes = []
    for ev in events[:5]:  # не более 5 событий
        impact = ev.impact if hasattr(ev, "impact") else ev.get("impact", 0.0)
        etype = ev.event_type if hasattr(ev, "event_type") else ev.get("event_type", "")
        summary = ev.summary if hasattr(ev, "summary") else ev.get("summary", etype)
        total += float(impact or 0.0)

        sign = "📈" if impact > 0 else "📉"
        notes.append(f"{sign} {summary or etype} ({impact:+.2f})")

    # Ограничиваем суммарный сдвиг: не более ±0.25 на команду
    total = max(-0.25, min(0.25, total))
    return total, notes


def predict(
    team1: str,
    team2: str,
    team1_form: str,
    team2_form: str,
    team1_rating: float | None,
    team2_rating: float | None,
    h2h_matches: list[dict],
    team1_odds: float | None = None,
    team2_odds: float | None = None,
    team1_events: list | None = None,   # список NewsEvent или dict
    team2_events: list | None = None,
) -> Prediction:
    reasoning = []

    # --- Форма (40%) ---
    f1 = _form_score(team1_form)
    f2 = _form_score(team2_form)
    reasoning.append(f"Форма: {team1} {team1_form or '—'} / {team2} {team2_form or '—'}")

    # --- Рейтинг (30%) ---
    r1, r2 = _rating_score(team1_rating, team2_rating)
    if team1_rating and team2_rating:
        reasoning.append(f"Рейтинг: {team1} {team1_rating:.0f} / {team2} {team2_rating:.0f}")

    # --- H2H (30%) ---
    h1, h2 = _h2h_score(h2h_matches, team1)
    if h2h_matches:
        t1w = sum(1 for m in h2h_matches[:10] if _team_won(m, team1))
        t2w = len(h2h_matches[:10]) - t1w
        reasoning.append(f"H2H (посл. {len(h2h_matches[:10])}): {team1} {t1w}W / {team2} {t2w}W")
    else:
        reasoning.append("H2H: нет данных о встречах")

    # --- Если есть кэфы — добавляем как отдельный фактор ---
    if team1_odds and team2_odds:
        imp1 = 1 / team1_odds
        imp2 = 1 / team2_odds
        total_imp = imp1 + imp2
        odds_p1 = imp1 / total_imp
        odds_p2 = imp2 / total_imp
        raw1 = f1 * 0.32 + r1 * 0.24 + h1 * 0.24 + odds_p1 * 0.20
        raw2 = f2 * 0.32 + r2 * 0.24 + h2 * 0.24 + odds_p2 * 0.20
        reasoning.append(f"Кэфы: {team1} {team1_odds:.2f} / {team2} {team2_odds:.2f}")
    else:
        raw1 = f1 * 0.40 + r1 * 0.30 + h1 * 0.30
        raw2 = f2 * 0.40 + r2 * 0.30 + h2 * 0.30

    # --- Новостные события (Gemini / keywords) ---
    adj1, notes1 = _news_adjustment(team1_events or [])
    adj2, notes2 = _news_adjustment(team2_events or [])

    if notes1:
        reasoning.append(f"📰 Новости {team1}:")
        reasoning.extend(f"  {n}" for n in notes1)
    if notes2:
        reasoning.append(f"📰 Новости {team2}:")
        reasoning.extend(f"  {n}" for n in notes2)

    # Применяем сдвиг пропорционально текущим raw-значениям
    total_raw = raw1 + raw2 if (raw1 + raw2) > 0 else 1.0
    raw1 += adj1 * total_raw * 0.5   # масштабируем чтобы не доминировало
    raw2 += adj2 * total_raw * 0.5
    raw1 = max(0.01, raw1)
    raw2 = max(0.01, raw2)

    total = raw1 + raw2
    p1 = raw1 / total if total > 0 else 0.5
    p2 = raw2 / total if total > 0 else 0.5

    diff = abs(p1 - p2)
    if diff < 0.08:
        confidence = "низкая"
    elif diff < 0.18:
        confidence = "средняя"
    else:
        confidence = "высокая"

    winner = team1 if p1 >= p2 else team2

    return Prediction(
        winner=winner,
        team1=team1,
        team2=team2,
        team1_prob=round(p1, 3),
        team2_prob=round(p2, 3),
        confidence=confidence,
        reasoning=reasoning,
    )


def _team_won(match: dict, team_name: str) -> bool:
    name1 = match.get("team1", "").lower()
    is_t1 = team_name.lower() in name1 or name1 in team_name.lower()
    score = match.get("score", "0:0")
    try:
        s1, s2 = map(int, score.split(":"))
    except Exception:
        return False
    return (s1 > s2) if is_t1 else (s2 > s1)
