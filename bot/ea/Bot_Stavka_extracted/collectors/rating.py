"""
Расчёт рейтинга команд на основе завершённых матчей.
ELO-подобная система: побеждаешь сильную команду — много очков,
проигрываешь слабой — много теряешь.
"""
import logging
from collections import defaultdict

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Match, Team

logger = logging.getLogger(__name__)

DEFAULT_RATING = 1500.0
K_FACTOR = 32.0  # как сильно меняется рейтинг за матч


def _expected(rating_a: float, rating_b: float) -> float:
    """Вероятность что A выиграет по ELO."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _normalize(name: str) -> str:
    return name.lower().strip()


async def recalculate_ratings(db: AsyncSession, game: str) -> int:
    """Пересчитать рейтинги для всех команд по завершённым матчам."""
    # Берём матчи в хронологическом порядке
    result = await db.execute(
        select(Match).where(
            and_(
                Match.game == game,
                Match.status == "finished",
                Match.score_team1.isnot(None),
                Match.score_team2.isnot(None),
            )
        ).order_by(Match.scheduled_at)
    )
    matches = result.scalars().all()
    if not matches:
        return 0

    ratings: dict[str, float] = defaultdict(lambda: DEFAULT_RATING)
    wins: dict[str, int] = defaultdict(int)
    losses: dict[str, int] = defaultdict(int)

    for m in matches:
        t1_key = _normalize(m.team1_name)
        t2_key = _normalize(m.team2_name)
        r1 = ratings[t1_key]
        r2 = ratings[t2_key]

        s1, s2 = m.score_team1 or 0, m.score_team2 or 0
        if s1 == s2:
            continue

        actual1 = 1.0 if s1 > s2 else 0.0
        actual2 = 1.0 - actual1
        exp1 = _expected(r1, r2)
        exp2 = 1.0 - exp1

        ratings[t1_key] = r1 + K_FACTOR * (actual1 - exp1)
        ratings[t2_key] = r2 + K_FACTOR * (actual2 - exp2)

        if actual1 > actual2:
            wins[t1_key] += 1
            losses[t2_key] += 1
        else:
            wins[t2_key] += 1
            losses[t1_key] += 1

    # Сохраняем в БД (или обновляем существующие записи Team)
    saved = 0
    for name_key, rating in ratings.items():
        # Ищем команду
        result = await db.execute(
            select(Team).where(
                and_(Team.normalized_name == name_key, Team.game == game)
            )
        )
        team = result.scalar_one_or_none()

        if team is None:
            # Достаём оригинальное название из последнего матча
            r2 = await db.execute(
                select(Match).where(
                    and_(
                        Match.game == game,
                        Match.team1_name.ilike(name_key),
                    )
                ).limit(1)
            )
            sample = r2.scalar_one_or_none()
            display_name = sample.team1_name if sample else name_key
            team = Team(
                source="calculated",
                game=game,
                name=display_name,
                normalized_name=name_key,
                rating=round(rating, 1),
                wins=wins[name_key],
                losses=losses[name_key],
            )
            db.add(team)
        else:
            team.rating = round(rating, 1)
            team.wins = wins[name_key]
            team.losses = losses[name_key]
        saved += 1

    await db.commit()
    logger.info("Rating: recalculated %d teams for %s", saved, game)
    return saved
