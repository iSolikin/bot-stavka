import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram Bot
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = [
        int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ]

    # Telegram User Account (Telethon)
    TG_API_ID: int = int(os.getenv("TG_API_ID", "0"))
    TG_API_HASH: str = os.getenv("TG_API_HASH", "")
    TG_PHONE: str = os.getenv("TG_PHONE", "")

    # База данных — DATABASE_URL или по умолчанию SQLite
    @property
    def DATABASE_URL(self) -> str:
        url = os.getenv("DATABASE_URL")
        if url:
            return url
        return "sqlite+aiosqlite:///./bot.db"

    # Redis (опционально)
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # OpenDota
    OPENDOTA_API_KEY: str = os.getenv("OPENDOTA_API_KEY", "")
    OPENDOTA_BASE_URL: str = "https://api.opendota.com/api"

    # The Odds API (https://the-odds-api.com — бесплатно 500 запросов/месяц)
    ODDS_API_KEY: str = os.getenv("ODDS_API_KEY", "")
    ODDS_API_BASE: str = "https://api.the-odds-api.com/v4"

    # Виртуальный банк и value-беттинг
    INITIAL_BANK: float = float(os.getenv("INITIAL_BANK", "10000"))
    KELLY_FRACTION: float = float(os.getenv("KELLY_FRACTION", "0.25"))   # дробный Келли (1/4)
    MIN_EDGE: float = float(os.getenv("MIN_EDGE", "0.03"))               # мин. перевес 3%
    MAX_STAKE_PCT: float = float(os.getenv("MAX_STAKE_PCT", "0.05"))     # макс 5% банка на ставку
    MIN_STAKE: float = float(os.getenv("MIN_STAKE", "10"))
    FLAT_STAKE: float = float(os.getenv("FLAT_STAKE", "100"))            # фолбэк когда кэфов нет

    # FACEIT API (https://developers.faceit.com — бесплатно)
    FACEIT_API_KEY: str = os.getenv("FACEIT_API_KEY", "")

    # Gemini Flash (оставляем для совместимости, не используется)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # Groq — бесплатно 14400 req/day — https://console.groq.com
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    @property
    def ADMIN_ID(self) -> int | None:
        return self.ADMIN_IDS[0] if self.ADMIN_IDS else None

    # Настройки
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Кэш (секунды)
    CACHE_TTL_REPORT: int = 900       # 15 минут
    CACHE_TTL_MATCHES: int = 7200     # 2 часа

    # Планировщик
    SCHEDULE_MATCHES_INTERVAL_HOURS: int = 2
    SCHEDULE_STATS_INTERVAL_HOURS: int = 6
    SCHEDULE_RATINGS_INTERVAL_HOURS: int = 24
    SCHEDULE_TG_INTERVAL_SECONDS: int = 60


config = Config()
