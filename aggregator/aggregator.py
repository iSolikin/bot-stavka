"""
Агрегатор: объединяет данные об одной команде/игроке из разных источников.
Нормализует названия, считает производные метрики.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from db.models import Match, Patch, Player, Team, TelegramMessage

logger = logging.getLogger(__name__)

# Таблица нормализации названий команд
TEAM_NORMALIZATION: dict[str, str] = {
    "natus vincere": "navi",
    "na`vi": "navi",
    "na'vi": "navi",
    "navi": "navi",
    "team vitality": "vitality",
    "faze clan": "faze",
    "g2 esports": "g2",
    "team spirit": "spirit",
    "team liquid": "liquid",
    "mousesports": "mouz",
    "team secret": "secret",
    "tundra esports": "tundra",
    "gaimin gladiators": "gaimin",
    "betboom team": "betboom",
    "bb team": "betboom",
}


def normalize_team_name(name: str) -> str:
    """Привести название команды к единому ключу."""
    key = name.lower().strip()
    return TEAM_NORMALIZATION.get(key, key)


@dataclass
class TeamReport:
    name: str
    game: str
    sources: list[str] = field(default_factory=list)
    rating: float | None = None
    wins: int = 0
    losses: int = 0
    recent_matches: list[dict] = field(default_factory=list)   # последние 10 матчей
    head_to_head: dict[str, dict] = field(default_factory=dict)  # h2h vs конкретных команд
    players: list[dict] = field(default_factory=list)
    last_patch: dict | None = None
    telegram_mentions: list[dict] = field(default_factory=list)
    form: str = ""   # например "WWLWW" — последние 5 матчей


@dataclass
class PlayerReport:
    nickname: str
    game: str
    real_name: str | None = None
    country: str | None = None
    team_name: str | None = None
    rating: float | None = None
    sources: list[str] = field(default_factory=list)
    recent_matches: list[dict] = field(default_factory=list)
    telegram_mentions: list[dict] = field(default_factory=list)


@dataclass
class MatchReport:
    team1: str
    team2: str
    game: str
    tournament: str | None
    match_format: str | None
    scheduled_at: datetime | None
    team1_stats: TeamReport | None = None
    team2_stats: TeamReport | None = None
    head_to_head: list[dict] = field(default_factory=list)
    last_patch: dict | None = None


class Aggregator:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_team_report(self, team_name: str, game: str) -> TeamReport | None:
        """Собрать полный отчёт по команде из всех источников."""
        normalized = normalize_team_name(team_name)

        # Ищем команду во всех источниках
        result = await self.db.execute(
            select(Team).where(
                and_(
                    Team.game == game,
                    or_(
                        Team.normalized_name == normalized,
                        Team.normalized_name.ilike(f"%{normalized}%"),
                    ),
                )
            )
        )
        teams = result.scalars().all()

        report = TeamReport(name=team_name, game=game)

        if not teams:
            # Команды нет в таблице teams — но матчи могут быть.
            # Строим отчёт только из matches (без рейтинга/состава).
            logger.debug("Team not in Teams table, fallback to match history: %s [%s]", team_name, game)
            name_patterns = [normalized, team_name.lower()]
        else:
            # Агрегируем данные из всех источников
            for team in teams:
                report.sources.append(team.source)
                if team.rating and (report.rating is None or team.rating > report.rating):
                    report.rating = team.rating
                report.wins = max(report.wins, team.wins)
                report.losses = max(report.losses, team.losses)

            # Собираем все варианты названий команды для поиска в матчах
            name_patterns: list[str] = [normalized]
            for team in teams:
                low = team.name.lower()
                if low not in name_patterns:
                    name_patterns.append(low)
                if team.tag:
                    tag_low = team.tag.lower()
                    if tag_low not in name_patterns:
                        name_patterns.append(tag_low)

        # Последние матчи
        report.recent_matches = await self._get_recent_matches(name_patterns, game, limit=10)

        # Форма команды (последние 5)
        report.form = self._calc_form(report.recent_matches, normalized)

        # Head-to-head с топ-соперниками
        report.head_to_head = await self._get_head_to_head(name_patterns, game)

        # Если нет формы ни из матчей — возвращаем None только для /team команды
        # Для предиктов используем даже пустой отчёт (50/50)

        # Игроки
        report.players = await self._get_players(teams[0].id if teams else None)

        # Последний патч
        report.last_patch = await self._get_last_patch(game)

        # Упоминания в Telegram (последние 7 дней)
        report.telegram_mentions = await self._get_telegram_mentions(normalized)

        return report

    async def get_match_report(self, team1_name: str, team2_name: str, game: str) -> MatchReport:
        """Собрать отчёт по конкретному матчу."""
        # Ищем матч в БД
        norm1 = normalize_team_name(team1_name)
        norm2 = normalize_team_name(team2_name)

        result = await self.db.execute(
            select(Match).where(
                and_(
                    Match.game == game,
                    Match.status.in_(["upcoming", "live"]),
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
            ).order_by(Match.scheduled_at).limit(1)
        )
        match = result.scalar_one_or_none()

        report = MatchReport(
            team1=team1_name,
            team2=team2_name,
            game=game,
            tournament=match.tournament if match else None,
            match_format=match.match_format if match else None,
            scheduled_at=match.scheduled_at if match else None,
        )

        # Отчёты по каждой команде
        report.team1_stats = await self.get_team_report(team1_name, game)
        report.team2_stats = await self.get_team_report(team2_name, game)

        # H2H между этими командами
        report.head_to_head = await self._get_h2h_between(norm1, norm2, game)

        # Последний патч
        report.last_patch = await self._get_last_patch(game)

        return report

    async def get_player_report(self, nickname: str, game: str | None = None) -> PlayerReport | None:
        """Собрать отчёт по игроку."""
        query = select(Player).where(Player.nickname.ilike(f"%{nickname}%"))
        if game:
            query = query.where(Player.game == game)

        result = await self.db.execute(query)
        players = result.scalars().all()

        if not players:
            logger.warning("Player not found: %s", nickname)
            return None

        # Берём наиболее подходящего (точное совпадение приоритетнее)
        player = next(
            (p for p in players if p.nickname.lower() == nickname.lower()),
            players[0],
        )

        report = PlayerReport(
            nickname=player.nickname,
            game=player.game,
            real_name=player.real_name,
            country=player.country,
            rating=player.rating,
            sources=[player.source],
        )

        # Название команды и последние матчи через неё
        if player.team_id:
            team_result = await self.db.execute(
                select(Team).where(Team.id == player.team_id)
            )
            team = team_result.scalar_one_or_none()
            if team:
                report.team_name = team.name
                name_patterns = [team.normalized_name, team.name.lower()]
                if team.tag:
                    name_patterns.append(team.tag.lower())
                report.recent_matches = await self._get_recent_matches(
                    name_patterns, player.game, limit=5
                )

        # Упоминания в Telegram
        report.telegram_mentions = await self._get_telegram_mentions(
            player.nickname.lower()
        )

        return report

    async def get_upcoming_matches(self, game: str, hours: int = 48) -> list[dict]:
        """Получить предстоящие и текущие live-матчи на N часов вперёд."""
        now = datetime.utcnow()
        until = now + timedelta(hours=hours)
        from_time = now - timedelta(hours=3)  # включаем live-матчи идущие прямо сейчас

        result = await self.db.execute(
            select(Match).where(
                and_(
                    Match.game == game,
                    Match.status.in_(["upcoming", "live"]),
                    Match.scheduled_at >= from_time,
                    Match.scheduled_at <= until,
                )
            ).order_by(Match.scheduled_at)
        )
        matches = result.scalars().all()

        return [
            {
                "team1": m.team1_name,
                "team2": m.team2_name,
                "tournament": m.tournament,
                "match_format": m.match_format,
                "scheduled_at": m.scheduled_at,
                "match_url": m.match_url,
                "source": m.source,
                "status": m.status,
            }
            for m in matches
        ]

    # --- Вспомогательные методы ---

    async def _get_recent_matches(self, name_patterns: list[str], game: str, limit: int = 10) -> list[dict]:
        pattern_conditions = [
            or_(
                Match.team1_name.ilike(f"%{pat}%"),
                Match.team2_name.ilike(f"%{pat}%"),
            )
            for pat in name_patterns
        ]
        result = await self.db.execute(
            select(Match).where(
                and_(
                    Match.game == game,
                    Match.status == "finished",
                    or_(*pattern_conditions),
                )
            ).order_by(Match.scheduled_at.desc()).limit(50)  # берём больше для агрегации
        )
        matches = result.scalars().all()

        # Агрегируем карты/игры одной серии в один матч
        # Ключ: (пара команд сортированная, дата по дням)
        series: dict[tuple, dict] = {}
        for m in matches:
            key_teams = tuple(sorted([m.team1_name.lower(), m.team2_name.lower()]))
            key_date = m.scheduled_at.date() if m.scheduled_at else None
            key = (key_teams, key_date)

            s1 = m.score_team1 or 0
            s2 = m.score_team2 or 0

            if key not in series:
                series[key] = {
                    "team1": m.team1_name,
                    "team2": m.team2_name,
                    "score1": s1,
                    "score2": s2,
                    "tournament": m.tournament,
                    "date": m.scheduled_at,
                }
            else:
                # Суммируем счёт (обычная команда1 в первом матче = team1 во всей серии)
                entry = series[key]
                if entry["team1"].lower() == m.team1_name.lower():
                    entry["score1"] += s1
                    entry["score2"] += s2
                else:
                    entry["score1"] += s2
                    entry["score2"] += s1

        # Формируем итоговый список, сортируем по дате (свежие первые)
        raw = sorted(series.values(), key=lambda x: x["date"] or datetime.min, reverse=True)
        return [
            {
                "team1": r["team1"],
                "team2": r["team2"],
                "score": f"{r['score1']}:{r['score2']}",
                "tournament": r["tournament"],
                "date": r["date"],
            }
            for r in raw[:limit]
        ]

    def _calc_form(self, recent_matches: list[dict], normalized_name: str) -> str:
        """Вычислить форму команды: W/L за последние 5 матчей."""
        form = []
        for m in recent_matches[:5]:
            team1_norm = normalize_team_name(m["team1"])
            is_team1 = (
                team1_norm == normalized_name
                or normalized_name in m["team1"].lower()
            )

            score = m.get("score", "0:0")
            try:
                s1, s2 = map(int, score.split(":"))
            except Exception:
                form.append("?")
                continue

            if is_team1:
                form.append("W" if s1 > s2 else "L")
            else:
                form.append("W" if s2 > s1 else "L")

        return "".join(form) if form else "—"

    async def _get_head_to_head(self, name_patterns: list[str], game: str) -> dict[str, dict]:
        """H2H статистика против всех соперников."""
        pattern_conditions = [
            or_(
                Match.team1_name.ilike(f"%{pat}%"),
                Match.team2_name.ilike(f"%{pat}%"),
            )
            for pat in name_patterns
        ]
        result = await self.db.execute(
            select(Match).where(
                and_(
                    Match.game == game,
                    Match.status == "finished",
                    or_(*pattern_conditions),
                )
            )
        )
        matches = result.scalars().all()

        # Главный нормализованный ключ — первый в списке
        primary_norm = name_patterns[0]

        h2h: dict[str, dict] = {}
        for m in matches:
            team1_norm = normalize_team_name(m.team1_name)
            is_team1 = (
                team1_norm == primary_norm
                or primary_norm in m.team1_name.lower()
            )
            opponent = m.team2_name if is_team1 else m.team1_name
            opp_key = normalize_team_name(opponent)

            if opp_key not in h2h:
                h2h[opp_key] = {"wins": 0, "losses": 0, "opponent": opponent}

            try:
                s1, s2 = m.score_team1 or 0, m.score_team2 or 0
            except Exception:
                continue

            if is_team1:
                if s1 > s2:
                    h2h[opp_key]["wins"] += 1
                else:
                    h2h[opp_key]["losses"] += 1
            else:
                if s2 > s1:
                    h2h[opp_key]["wins"] += 1
                else:
                    h2h[opp_key]["losses"] += 1

        return h2h

    async def _get_h2h_between(self, norm1: str, norm2: str, game: str) -> list[dict]:
        """H2H между двумя конкретными командами."""
        result = await self.db.execute(
            select(Match).where(
                and_(
                    Match.game == game,
                    Match.status == "finished",
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
            ).order_by(Match.scheduled_at.desc()).limit(10)
        )
        matches = result.scalars().all()

        return [
            {
                "team1": m.team1_name,
                "team2": m.team2_name,
                "score": f"{m.score_team1}:{m.score_team2}",
                "tournament": m.tournament,
                "date": m.scheduled_at,
            }
            for m in matches
        ]

    async def _get_players(self, team_id: int | None) -> list[dict]:
        if not team_id:
            return []
        result = await self.db.execute(
            select(Player).where(Player.team_id == team_id)
        )
        players = result.scalars().all()
        return [
            {"nickname": p.nickname, "real_name": p.real_name, "country": p.country, "rating": p.rating}
            for p in players
        ]

    async def _get_last_patch(self, game: str) -> dict | None:
        result = await self.db.execute(
            select(Patch).where(Patch.game == game).order_by(Patch.released_at.desc()).limit(1)
        )
        patch = result.scalar_one_or_none()
        if not patch:
            return None
        return {
            "version": patch.version,
            "released_at": patch.released_at,
            "url": patch.url,
            "summary": patch.summary,
        }

    async def _get_telegram_mentions(self, normalized_name: str) -> list[dict]:
        since = datetime.utcnow() - timedelta(days=7)
        result = await self.db.execute(
            select(TelegramMessage).where(
                and_(
                    TelegramMessage.posted_at >= since,
                    TelegramMessage.mentioned_teams.ilike(f"%{normalized_name}%"),
                )
            ).order_by(TelegramMessage.posted_at.desc()).limit(5)
        )
        messages = result.scalars().all()
        return [
            {
                "channel": m.channel_username,
                "text": (m.text or "")[:200],
                "posted_at": m.posted_at,
            }
            for m in messages
        ]
