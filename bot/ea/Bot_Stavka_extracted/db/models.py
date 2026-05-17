from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Внешний ID из источника (opendota team_id, hltv id и т.д.)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32))          # opendota / hltv / liquipedia
    game: Mapped[str] = mapped_column(String(16))            # dota2 / cs2
    name: Mapped[str] = mapped_column(String(128))
    # Нормализованный ключ для объединения из разных источников
    normalized_name: Mapped[str] = mapped_column(String(128), index=True)
    tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    players: Mapped[list["Player"]] = relationship("Player", back_populates="team")

    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_team_external_source"),
    )

    def __repr__(self) -> str:
        return f"<Team {self.name} [{self.game}]>"


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
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)   # HLTV rating / OpenDota rank
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team: Mapped["Team | None"] = relationship("Team", back_populates="players")

    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_player_external_source"),
    )

    def __repr__(self) -> str:
        return f"<Player {self.nickname} [{self.game}]>"


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    game: Mapped[str] = mapped_column(String(16))
    team1_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    team2_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    team1_name: Mapped[str] = mapped_column(String(128))     # дублируем имя на случай отсутствия в teams
    team2_name: Mapped[str] = mapped_column(String(128))
    tournament: Mapped[str | None] = mapped_column(String(256), nullable=True)
    match_format: Mapped[str | None] = mapped_column(String(16), nullable=True)   # bo1 / bo3 / bo5
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="upcoming")  # upcoming / live / finished
    score_team1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_team2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    match_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
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

    def __repr__(self) -> str:
        return f"<Patch {self.game} {self.version}>"


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_username: Mapped[str] = mapped_column(String(128), index=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Упомянутые команды/игроки (через запятую)
    mentioned_teams: Mapped[str | None] = mapped_column(Text, nullable=True)
    mentioned_players: Mapped[str | None] = mapped_column(Text, nullable=True)
    game: Mapped[str | None] = mapped_column(String(16), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("channel_username", "message_id", name="uq_tg_channel_message"),
    )


class TelegramChannel(Base):
    """Список каналов для мониторинга."""
    __tablename__ = "telegram_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), unique=True)
    game: Mapped[str | None] = mapped_column(String(16), nullable=True)   # dota2 / cs2 / both
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
    """Подписка пользователя на команду — получает уведомление за час до матча."""
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # Нормализованное название команды (navi, vitality, og и т.д.)
    team_key: Mapped[str] = mapped_column(String(128), index=True)
    # Оригинальное название как ввёл пользователь
    team_display: Mapped[str] = mapped_column(String(128))
    game: Mapped[str] = mapped_column(String(16))   # cs2 / dota2
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
