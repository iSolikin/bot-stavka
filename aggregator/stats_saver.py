"""
Сохранение собранной статистики в БД.
Принимает данные от коллекторов и обновляет таблицы teams/players.
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from db.models import Team, Player
from aggregator.aggregator import normalize_team_name

logger = logging.getLogger(__name__)


async def save_cs2_team_ratings(
    db: AsyncSession,
    hltv_rankings: list[dict],
    valve_rankings: Optional[list[dict]] = None
) -> int:
    """
    Сохранить рейтинги CS2 команд (HLTV и Valve) в БД.

    Args:
        db: AsyncSession
        hltv_rankings: список dict с полями {rank, name, hltv_rating, ...}
        valve_rankings: список dict с полями {rank, name, valve_rating, ...}

    Returns:
        Количество обновленных команд
    """
    updated_count = 0
    now = datetime.utcnow()

    # Создаём lookup таблицы
    valve_map = {}
    if valve_rankings:
        for team_data in valve_rankings:
            normalized = normalize_team_name(team_data.get("name", ""))
            valve_map[normalized] = team_data.get("valve_rating")

    # Обрабатываем HLTV рейтинги (основной источник)
    for team_data in hltv_rankings:
        team_name = team_data.get("name", "").strip()
        if not team_name:
            continue

        normalized = normalize_team_name(team_name)
        hltv_rating = team_data.get("hltv_rating")
        valve_rating = valve_map.get(normalized)
        rank = team_data.get("rank")

        # Ищем или создаём команду
        result = await db.execute(
            select(Team).where(
                and_(
                    Team.game == "cs2",
                    Team.normalized_name == normalized,
                )
            )
        )
        team = result.scalar_one_or_none()

        if not team:
            # Создаём новую команду
            team = Team(
                external_id=f"hltv_{rank}" if rank else None,
                source="hltv",
                game="cs2",
                name=team_name,
                normalized_name=normalized,
                hltv_rating=hltv_rating,
                valve_rating=valve_rating,
            )
            db.add(team)
            updated_count += 1
            logger.debug(f"Created new team: {team_name}")
        else:
            # Обновляем существующую команду
            old_hltv = team.hltv_rating
            old_valve = team.valve_rating

            team.hltv_rating = hltv_rating
            if valve_rating:
                team.valve_rating = valve_rating

            # Вычисляем усреднённый рейтинг
            ratings = [r for r in [team.hltv_rating, team.valve_rating] if r]
            if ratings:
                team.rating = sum(ratings) / len(ratings)

            # Обновляем историю рейтингов (JSON)
            if team.rating_history is None:
                team.rating_history = []

            history_entry = {
                "date": now.isoformat(),
                "hltv": team.hltv_rating,
                "valve": team.valve_rating,
                "avg": team.rating,
            }

            # Храним только последние 100 записей
            team.rating_history.append(history_entry)
            if len(team.rating_history) > 100:
                team.rating_history = team.rating_history[-100:]

            team.last_stats_update = now
            updated_count += 1

            if old_hltv != hltv_rating or old_valve != valve_rating:
                logger.debug(
                    f"Updated {team_name}: HLTV {old_hltv} → {hltv_rating}, "
                    f"Valve {old_valve} → {valve_rating}"
                )

    await db.commit()
    logger.info(f"Saved/updated {updated_count} CS2 team ratings")
    return updated_count


async def save_cs2_player_ratings(
    db: AsyncSession,
    player_ratings: list[dict]
) -> int:
    """
    Сохранить рейтинги CS2 игроков в БД.

    Args:
        db: AsyncSession
        player_ratings: список dict с полями {name, player_id, rating, team, ...}

    Returns:
        Количество обновленных игроков
    """
    updated_count = 0
    now = datetime.utcnow()

    for player_data in player_ratings:
        nickname = player_data.get("name", "").strip()
        if not nickname:
            continue

        player_id = player_data.get("player_id")
        rating = player_data.get("rating")
        team_name = player_data.get("team")
        country = player_data.get("country")
        maps_played = player_data.get("maps_played")

        # Ищем или создаём игрока
        result = await db.execute(
            select(Player).where(
                Player.nickname.ilike(nickname)
            )
        )
        player = result.scalar_one_or_none()

        if not player:
            # Создаём нового игрока
            player = Player(
                external_id=str(player_id) if player_id else None,
                source="hltv",
                game="cs2",
                nickname=nickname,
                rating=rating,
                country=country,
            )
            db.add(player)
            updated_count += 1
            logger.debug(f"Created new player: {nickname}")
        else:
            # Обновляем существующего игрока
            old_rating = player.rating

            player.rating = rating
            player.country = country

            # Обновляем историю рейтингов
            if player.rating_history is None:
                player.rating_history = []

            history_entry = {
                "date": now.isoformat(),
                "rating": rating,
                "maps": maps_played,
            }

            player.rating_history.append(history_entry)
            if len(player.rating_history) > 100:
                player.rating_history = player.rating_history[-100:]

            player.last_stats_update = now
            updated_count += 1

            if old_rating != rating:
                logger.debug(f"Updated {nickname}: Rating {old_rating} → {rating}")

    await db.commit()
    logger.info(f"Saved/updated {updated_count} CS2 player ratings")
    return updated_count


async def save_cs2_team_details(
    db: AsyncSession,
    team_name: str,
    details: dict
) -> bool:
    """
    Сохранить детальную информацию о команде (состав, недавние матчи, карты).

    Args:
        db: AsyncSession
        team_name: Название команды
        details: dict с полями {players, recent_matches, best_map, worst_map, ...}

    Returns:
        True если успешно, False иначе
    """
    normalized = normalize_team_name(team_name)

    result = await db.execute(
        select(Team).where(
            and_(
                Team.game == "cs2",
                Team.normalized_name == normalized,
            )
        )
    )
    team = result.scalar_one_or_none()

    if not team:
        logger.warning(f"Team not found for details: {team_name}")
        return False

    # Обновляем поля из деталей
    if "best_map" in details:
        team.best_map = details["best_map"]
    if "worst_map" in details:
        team.worst_map = details["worst_map"]
    if "map_stats" in details:
        team.map_stats = details["map_stats"]
    if "recent_form" in details:
        team.recent_form = details["recent_form"]
    if "win_rate_last_10" in details:
        team.win_rate_last_10 = details["win_rate_last_10"]

    team.last_stats_update = datetime.utcnow()
    await db.commit()

    logger.info(f"Updated team details for {team_name}")
    return True
