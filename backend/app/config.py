"""Application configuration."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql://sport:sport@localhost:11002/sport_analyzator"
    database_url_async: str | None = None

    # Redis
    redis_url: str = "redis://localhost:11003/0"

    # Auth
    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    frontend_url: str = "http://localhost:11000"  # for email verification link

    # API
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    admin_secret: str = ""  # X-Admin-Key для выдачи подписок по user_id

    # Providers
    sportradar_api_key: str = ""
    sportmonks_api_key: str = ""
    the_odds_api_key: str = ""
    # BetsAPI — настольный теннис (и др.): https://betsapi.com, токен и sport_id
    betsapi_token: str = ""
    betsapi_table_tennis_sport_id: int = 92
    # Ранее лимит на кол-во матчей для event/odds; сейчас: лайв — все, линия — один раз (не используется)
    betsapi_max_events_for_odds: int = 50

    # Telegram (for signal engine)
    telegram_bot_token: str = ""
    telegram_signals_chat_id: str = ""

    # Value / Probability
    value_ev_threshold: float = 0.05
    min_odds: float = 1.01
    max_odds: float = 50.0

    # Интервалы опроса внешних API (BetsAPI, The Odds API, Sportradar)
    live_poll_interval_seconds: int = 3   # 1 запрос/цикл → раз в 3 сек ≈ 1200/час, счёт по сетам в реальном времени
    live_odds_poll_interval_seconds: int = 30  # inplay + event/odds по каждому — раз в 30 сек, актуальные коэффициенты
    prematch_poll_interval_seconds: int = 600  # линия+лайв полный цикл (view+odds) — раз в 5–10 мин

    # Флаг для остановки всех периодических запросов к внешним API (игры, обновления, коэффициенты).
    # По умолчанию выключено, чтобы не опрашивать поставщиков, пока не включим явно через .env.
    enable_scheduled_collectors: bool = False

    @property
    def async_database_url(self) -> str:
        if self.database_url_async:
            return self.database_url_async
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url


settings = Settings()
