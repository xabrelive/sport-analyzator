"""Application configuration. All options can be overridden via .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database (PostgreSQL — рассчитан на миллионы строк и сотни/тысячи записей в день)
    database_url: str = "postgresql://pingwin:pingwin@localhost:11002/pingwin"
    database_url_async: str | None = None

    # Auth
    secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Verification codes
    verification_code_length: int = 6
    verification_code_expire_minutes_telegram: int = 10  # код из бота (регистрация, привязка)
    verification_code_expire_minutes_email: int = 120  # 2 часа — код из письма

    # Frontend
    frontend_url: str = "http://localhost:11000"
    frontend_public_url: str = ""

    # CORS
    cors_extra_origins: str = ""

    # API
    api_v1_prefix: str = "/api/v1"
    debug: bool = False

    # BetsAPI (спорт: настольный теннис)
    betsapi_token: str = ""
    betsapi_table_tennis_sport_id: int = 92  # стандартный sport_id для настольного тенниса в BetsAPI
    betsapi_table_tennis_line_interval_sec: int = 300  # опрос линии (список матчей), секунды
    betsapi_table_tennis_odds_interval_sec: int = 300   # опрос коэффициентов по матчам без кф, секунды
    betsapi_table_tennis_live_interval_sec: int = 8     # базовый опрос лайв-событий (inplay), секунды
    betsapi_table_tennis_live_interval_forecast_sec: int = 4  # матчи с прогнозом: обновление счёта чаще
    betsapi_table_tennis_live_interval_other_sec: int = 12  # матчи без прогноза: обновление счёта реже
    betsapi_table_tennis_result_check_interval_sec: int = 1800  # период фоновой проверки результатов (1ч/3ч), секунды
    betsapi_table_tennis_archive_sync_interval_sec: int = 300  # синхронизация результатов из архива (today/yesterday)
    betsapi_table_tennis_cancel_forecast_recheck_interval_sec: int = 120  # перепроверка cancelled матчей с прогнозом
    betsapi_table_tennis_max_pages: int = 20
    betsapi_table_tennis_cancel_missing_horizon_minutes: int = 90  # помечаем cancelled только для ближних матчей
    # Задержка перед расчётом прематч‑прогноза (минуты) после появления матча в линии
    betsapi_table_tennis_forecast_delay_minutes: int = 5
    # Минимальный коэффициент на исход прогноза (для выбранной стороны), ниже — прогноз не даём
    betsapi_table_tennis_min_odds_for_forecast: float = 1.4

    # Очередь и воркеры линии (масштабирование при росте объёма данных)
    line_queue_maxsize: int = 32  # макс. батчей в очереди (при переполнении продюсер ждёт)
    line_worker_count: int = 3    # число воркеров, обрабатывающих очередь (увеличить при росте нагрузки)
    line_sse_interval_sec: int = 5  # интервал отправки данных линии по SSE (обновление на лету)

    # SMTP (отправка кодов на почту)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False  # True для порта 465 (Mail.ru и др.)

    # Telegram Bot
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""

    @property
    def async_database_url(self) -> str:
        if self.database_url_async:
            return self.database_url_async
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url

    @property
    def frontend_base_url(self) -> str:
        return (self.frontend_public_url or self.frontend_url or "").rstrip("/")


settings = Settings()
