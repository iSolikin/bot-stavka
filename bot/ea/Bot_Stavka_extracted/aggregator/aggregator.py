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
    # NaVi
    "natus vincere": "navi",
    "na`vi": "navi",
    "na'vi": "navi",
    "navi": "navi",
    # CS2
    "team vitality": "vitality",
    "faze clan": "faze",
    "g2 esports": "g2",
    "team spirit": "spirit",
    "team liquid": "liquid",
    "mousesports": "mouz",
    "heroic": "heroic",
    "ence": "ence",
    "astralis": "astralis",
    "ninjas in pyjamas": "nip",
    "nip": "nip",
    "fnatic": "fnatic",
    "cloud9": "c9",
    "cloud 9": "c9",
    "complexity gaming": "col",
    "complexity": "col",
    "og": "og",
    "9 pandas": "9pandas",
    "9pandas": "9pandas",
    "eternal fire": "ef",
    # Dota2
    "team secret": "secret",
    "tundra esports": "tundra",
    "gaimin gladiators": "gaimin",
    "betboom team": "betboom",
    "bb team": "betboom",
    "evil geniuses": "eg",
    "eg": "eg",
    "team aster": "aster",
    "virtus.pro": "vp",
    "virtuspro": "vp",
    "vp": "vp",
    "psg.lgd": "lgd",
    "lgd gaming": "lgd",
    "lgd": "lgd",
    "team xtreme": "tx",
    "azure ray": "azure ray",
    "nouns esports": "nouns",
    "shopify rebellion": "sr",
    "aurora": "aurora",
    "entity": "entity",
    "beastcoast": "beastcoast",
    "talon esports": "talon",
    "execration": "execration",
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
    recent_matches: list[dict] = field(default_factory=list)
    head_to_head: dict[str, dict] = field(default_factory=dict)
    players: list[dict] = field(default_factory=list)
    last_patch: dict | None = None
    telegram_mentions: list[dict] = field(default_factory=list)
    form: str = ""


@dataclass
class PlayerReport:
    nickname: str
    real_name: str | None
    country: str | None
    game: str
    team_name: str | None
    rating: float | None
    sources: list[str] = field(default_factory=list)
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
                        Team.name.ilike(f"%{team_name}%"),
                    ),
                )
            )
        )
        teams = result.scalars().all()

        # Если команда не зарегистрирована — всё равно собираем данные из матчей
        # (на случай если есть в matches.team1_name но нет в teams)
        report = TeamReport(name=team_name, game=game)

        # Агрегируем данные из всех источников
        for team in teams:
            report.sources.append(team.source)
            if team.rating and (report.rating is None or team.rating > report.rating):
                report.rating = team.rating
            report.wins = max(report.wins, team.wins)
            report.losses = max(report.losses, team.losses)

        # Используем имя из БД для поиска матчей если команда найдена,
        # иначе сам team_name
        search_name = teams[0].name.lower() if teams else team_name.lower()

        # Последние матчи — ищем по реальному имени команды
        report.recent_matches = await self._get_recent_matches(search_name, game, limit=10)

        # Форма команды (последние 5)
        report.form = self._calc_form(report.recent_matches, search_name)

        # Head-to-head с топ-соперниками
        report.head_to_head = await self._get_head_to_head(search_name, game)

        # Если ничего не нашли — возвращаем None
        if not teams and not report.recent_matches:
            logger.warning("Team not found: %s [%s]", team_name, game)
            return None

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
                    Match.status == "upcoming",
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

    async def get_upcoming_matches(self, game: str, hours: int = 48) -> list[dict]:
        """Получить предстоящие матчи на N часов вперёд."""
        now = datetime.utcnow()
        until = now + timedelta(hours=hours)

        result = await self.db.execute(
            select(Match).where(
                and_(
                    Match.game == game,
                    Match.status == "upcoming",
                    Match.scheduled_at >= now,
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
            }
            for m in matches
        ]

    # --- Вспомогательные методы ---

    async def _get_recent_matches(self, normalized_name: str, game: str, limit: int = 10) -> list[dict]:
        result = await self.db.execute(
            select(Match).where(
                and_(
                    Match.game == game,
                    Match.status == "finished",
                    or_(
                        Match.team1_name.ilike(f"%{normalized_name}%"),
                        Match.team2_name.ilike(f"%{normalized_name}%"),
                    ),
                )
            ).order_by(Match.scheduled_at.desc()).limit(limit)
        )
        matches = result.scalars().all()

        return [
            {
                "team1": m.team1_name,
                "team2": m.team2_name,
                "score": f"{m.score_team1}:{m.score_team2}",
                "tournament": m.tournament,
                "date": m.scheduled_at,
                "winner": m.winner_team_id,
            }
            for m in matches
        ]

    async def get_player_report(self, nickname: str, game: str | None = None) -> "PlayerReport | None":
        """Собрать отчёт по игроку."""
        query = select(Player).where(Player.nickname.ilike(f"%{nickname}%"))
        if game:
            query = query.where(Player.game == game)
        result = await self.db.execute(query.limit(1))
        player = result.scalar_one_or_none()

        if not player:
            return None

        team_name: str | None = None
        if player.team_id:
            team_result = await self.db.execute(select(Team).where(Team.id == player.team_id))
            team = team_result.scalar_one_or_none()
            team_name = team.name if team else None

        mentions = await self._get_telegram_mentions(nickname.lower())

        return PlayerReport(
            nickname=player.nickname,
            real_name=player.real_name,
            country=player.country,
            game=player.game,
            team_name=team_name,
            rating=player.rating,
            sources=[player.source],
            telegram_mentions=mentions,
        )

    def _calc_form(self, recent_matches: list[dict], team_name_lower: str) -> str:
        """Вычислить форму команды: W/L за последние 5 матчей."""
        form = []
        tn = team_name_lower.lower().strip()
        for m in recent_matches[:5]:
            t1l = m["team1"].lower()
            # Точная проверка - либо равно, либо одно содержит другое
            is_team1 = (t1l == tn) or (tn in t1l) or (t1l in tn)

            score = m.get("score", "0:0")
            try:
                s1, s2 = map(int, score.split(":"))
            except Exception:
                form.append("?")
                continue

            if s1 == s2:
                form.append("?")
                continue

            if is_team1:
                form.append("W" if s1 > s2 else "L")
            else:
                form.append("W" if s2 > s1 else "L")

        return "".join(form) if form else "—"

    async def _get_head_to_head(self, normalized_name: str, game: str) -> dict[str, dict]:
        """H2H статистика против всех соперников."""
        result = await self.db.execute(
            select(Match).where(
                and_(
                    Match.game == game,
                    Match.status == "finished",
                    or_(
                        Match.team1_name.ilike(f"%{normalized_name}%"),
                        Match.team2_name.ilike(f"%{normalized_name}%"),
                    ),
                )
            )
        )
        matches = result.scalars().all()

        h2h: dict[str, dict] = {}
        for m in matches:
            team1_lower = m.team1_name.lower()
            is_team1 = normalized_name in team1_lower
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
