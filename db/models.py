from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, JSON
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    game: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(String(128), index=True)
    tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Рейтинги (CS2 специфично)
    hltv_rating: Mapped[float | None] = mapped_column(Float, nullable=True)  # HLTV рейтинг
    valve_rating: Mapped[float | None] = mapped_column(Float, nullable=True)  # Valve рейтинг
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)  # Основной рейтинг (усреднённый)

    # История рейтингов (JSON: [{"date": "2026-05-18", "rating": 1.23, "source": "hltv"}, ...])
    rating_history: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Статистика
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    win_rate_last_10: Mapped[float | None] = mapped_column(Float, nullable=True)  # Винрейт последних 10 матчей

    # Карты
    best_map: Mapped[str | None] = mapped_column(String(32), nullable=True)  # Лучшая карта
    worst_map: Mapped[str | None] = mapped_column(String(32), nullable=True)  # Худшая карта
    map_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Статистика по картам

    # Недавние матчи (JSON: ["W", "W", "L", "W", ...] - последние 10)
    recent_form: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "WWLWL" - форма

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_stats_update: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Последнее обновление статистики

    players: Mapped[list["Player"]] = relationship("Player", back_populates="team")

    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_team_external_source"),
    )

    def __repr__(self) -> str:
        return f"<Team {self.name} [{self.game}] HLTV:{self.hltv_rating} Valve:{self.valve_rating}>"


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    game: Mapped[str] = mapped_column(String(16))
    nickname: Mapped[str] = mapped_column(String(128), index=True)
    real_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)

    # Рейтинги
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)  # HLTV rating 2.0 (K/D ratio)
    rating_history: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # История рейтингов

    # Статистика CS2
    headshot_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)  # HS%
    avg_adr: Mapped[float | None] = mapped_column(Float, nullable=True)  # Average damage per round
    first_kill_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # First kill %
    clutch_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # 1vX success rate

    # Карты
    best_map: Mapped[str | None] = mapped_column(String(32), nullable=True)
    worst_map: Mapped[str | None] = mapped_column(String(32), nullable=True)
    map_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Позиции/роли (для CS2: rifler, awper, support и т.д.)
    positions: Mapped[str | None] = mapped_column(String(128), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_stats_update: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    team: Mapped["Team | None"] = relationship("Team", back_populates="players")

    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_player_external_source"),
    )

    def __repr__(self) -> str:
        return f"<Player {self.nickname} [{self.game}] Rating:{self.rating}>"


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    game: Mapped[str] = mapped_column(String(16))
    team1_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    team2_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    team1_name: Mapped[str] = mapped_column(String(128))
    team2_name: Mapped[str] = mapped_column(String(128))
    tournament: Mapped[str | None] = mapped_column(String(256), nullable=True)
    match_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="upcoming")
    score_team1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_team2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    match_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tier: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_match_external_source"),
    )

    def __repr__(self) -> str:
        return f"<Match {self.team1_name} vs {self.team2_name} [{self.game}]>"


class Patch(Base):
    __tablename__ = "patches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[str] = mapped_column(String(32))
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("game", "version", name="uq_patch_game_version"),
    )


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_username: Mapped[str] = mapped_column(String(128), index=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    mentioned_teams: Mapped[str | None] = mapped_column(Text, nullable=True)
    mentioned_players: Mapped[str | None] = mapped_column(Text, nullable=True)
    game: Mapped[str | None] = mapped_column(String(16), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("channel_username", "message_id", name="uq_tg_channel_message"),
    )


class TelegramChannel(Base):
    __tablename__ = "telegram_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), unique=True)
    game: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subscriptions: Mapped[list["Subscription"]] = relationship("Subscription", back_populates="user")

    def __repr__(self) -> str:
        return f"<User {self.telegram_id} @{self.username}>"


class Subscription(Base):
    """Подписка пользователя на команду — уведомление за час до матча."""
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    team_key: Mapped[str] = mapped_column(String(128), index=True)   # нормализованное имя
    team_display: Mapped[str] = mapped_column(String(128))            # оригинальное имя
    game: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="subscriptions")

    __table_args__ = (
        UniqueConstraint("user_id", "team_key", "game", name="uq_sub_user_team_game"),
    )


class MatchNotification(Base):
    """Лог отправленных уведомлений — чтобы не слать дважды."""
    __tablename__ = "match_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("match_id", "user_id", name="uq_notif_match_user"),
    )


class NewsEvent(Base):
    """Структурированное событие, извлечённое из новости (Gemini Flash или keywords)."""
    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Источник
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel_username: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Кого касается
    team_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    player_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    game: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    # Тип события
    # injury / absence / roster_add / roster_remove / bootcamp /
    # form_peak / form_poor / win_streak / loss_streak / disqualified / other
    event_type: Mapped[str] = mapped_column(String(32), default="other")

    # Влияние на вероятность победы команды: -1.0 (очень плохо) … +1.0 (очень хорошо)
    impact: Mapped[float] = mapped_column(Float, default=0.0)

    # Краткое описание
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Кто обработал: "gemini" / "keywords"
    processed_by: Mapped[str] = mapped_column(String(32), default="keywords")

    # Срок действия (через 7 дней событие устаревает)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MatchDetailStats(Base):
    """
    Детальная статистика одной игры (карты).
    Собирается из OpenDota (Dota2) и HLTV (CS2).
    Используется для предсказания маркетов (тоталы, форы, и т.д.)
    """
    __tablename__ = "match_detail_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Привязка
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"), nullable=True, index=True)
    external_match_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32))  # opendota / hltv
    game: Mapped[str] = mapped_column(String(16), index=True)

    # Команды
    team1_name: Mapped[str] = mapped_column(String(128), index=True)
    team2_name: Mapped[str] = mapped_column(String(128), index=True)
    winner: Mapped[str | None] = mapped_column(String(8), nullable=True)  # team1 / team2

    # === Dota 2 ===
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_kills: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team1_kills: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team2_kills: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team1_towers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team2_towers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_towers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_roshans: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_blood_team: Mapped[str | None] = mapped_column(String(8), nullable=True)   # team1/team2
    first_tower_team: Mapped[str | None] = mapped_column(String(8), nullable=True)
    had_megacreeps: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # === CS2 ===
    total_rounds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team1_rounds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team2_rounds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    map_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Мета
    match_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    tournament: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("external_match_id", "source", name="uq_detail_stats_ext"),
    )


class VirtualBet(Base):
    """Виртуальная ставка, сделанная ботом автоматически на основе предикта."""
    __tablename__ = "virtual_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Матч
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"), nullable=True)
    team1_name: Mapped[str] = mapped_column(String(128))
    team2_name: Mapped[str] = mapped_column(String(128))
    game: Mapped[str] = mapped_column(String(16))
    tournament: Mapped[str | None] = mapped_column(String(256), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Ставка
    bet_on: Mapped[str] = mapped_column(String(8))          # "team1" | "team2"
    bet_team_name: Mapped[str] = mapped_column(String(128)) # имя команды на которую ставим
    pred_prob: Mapped[float] = mapped_column(Float)         # вероятность от предиктора (0-1)
    confidence: Mapped[str] = mapped_column(String(16))     # низкая / средняя / высокая
    odds: Mapped[float] = mapped_column(Float)              # коэффициент (бук или 1/prob)
    stake: Mapped[float] = mapped_column(Float, default=100.0)  # сумма ставки

    # Результат
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/won/lost/void
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)  # + выигрыш / - проигрыш
    actual_score: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "2:1"

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("match_id", name="uq_vbet_match"),
    )
