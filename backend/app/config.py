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
    # Пул соединений: backend запускает 12+ фоновых задач (BetsAPI, прогнозы, ML sync и т.д.),
    # API-запросы конкурируют за соединения. При pool_size=10 запросы могут ждать 30+ сек.
    db_pool_size: int = 75
    db_pool_max_overflow: int = 75
    db_pool_recycle_sec: int = 300  # переподключение каждые 5 мин (избежать stale connections)
    # ML-база (Elo, фичи, модели, сигналы, подозрительные матчи)
    database_url_ml: str = "postgresql://pingwin:pingwin@localhost:11002/pingwin_ml"

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
    # Окно публикации прогноза: 1–3 часа до матча (Stage 2). Не пересчитываем после.
    betsapi_table_tennis_forecast_min_minutes_before: int = 60   # мин. минут до начала
    betsapi_table_tennis_forecast_max_minutes_before: int = 180  # макс. минут до начала
    # Минимальный коэффициент на исход прогноза (для выбранной стороны), ниже — прогноз не даём
    # Цель — не играть откровенный 1.10–1.30, а держаться в районе 1.6+.
    betsapi_table_tennis_min_odds_for_forecast: float = 1.6
    # V2 loops and KPI targets
    betsapi_table_tennis_v2_features_interval_sec: int = 300
    betsapi_table_tennis_v2_forecast_interval_sec: int = 60
    betsapi_table_tennis_early_scan_interval_sec: int = 600  # Stage 1: раз в 10 мин
    betsapi_table_tennis_v2_result_priority_interval_sec: int = 20
    betsapi_table_tennis_v2_kpi_guard_interval_sec: int = 60
    betsapi_table_tennis_v2_forecast_batch_size: int = 400
    betsapi_table_tennis_v2_target_hit_rate: float = 85.0
    betsapi_table_tennis_v2_target_picks_per_day: int = 300
    betsapi_table_tennis_v2_min_confidence_floor: float = 68.0
    betsapi_table_tennis_v2_min_confidence_ceiling: float = 88.0
    betsapi_table_tennis_v2_base_min_confidence: float = 74.0
    betsapi_table_tennis_v2_min_edge_floor: float = 2.0
    betsapi_table_tennis_v2_min_edge_ceiling: float = 8.0
    betsapi_table_tennis_v2_base_min_edge: float = 3.0
    table_tennis_match_sets_to_win: int = 3
    # ML pipeline: синхронизация main→ML и переобучение, интервал в секундах (0 = отключено)
    ml_sync_interval_sec: int = 600  # 10 мин: подтяжка данных + retrain
    ml_model_dir: str = "/tmp/pingwin_ml_models"
    ml_use_gpu: bool = True  # ML_USE_GPU=false — принудительно CPU (Docker без --gpus)
    ml_retrain_min_new_matches: int = 500  # 500+ для стабильной модели (меньше шума)
    ml_sync_days_back: int = 0  # 0 = весь архив, иначе N дней назад
    ml_sync_batch_size: int = 15000  # батч синхронизации main→ML (больше = быстрее)
    ml_backfill_workers: int = 6  # параллельных воркеров для backfill фичей

    # Разделение API и воркеров: при run_background_workers=false контейнер только API (быстрый, масштабируемый).
    # Воркеры (BetsAPI, прогнозы, ML sync) — в отдельном tt_workers контейнере.
    run_background_workers: bool = True  # false = API-only (для масштабирования 100-300 пользователей)
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
    telegram_signals_free_chat_id: str = ""
    telegram_signals_vip_chat_id: str = ""
    telegram_signals_vip_public_url: str = ""
    telegram_channels_loop_interval_sec: int = 60
    telegram_urgent_lead_minutes: int = 30
    telegram_free_window_start_hour: int = 9
    telegram_free_window_end_hour: int = 19
    telegram_free_daily_posts: int = 3
    telegram_free_min_lead_minutes: int = 60
    telegram_vip_hourly_min: int = 3
    telegram_vip_hourly_max: int = 4
    vip_access_check_interval_sec: int = 600
    notifications_batch_interval_minutes: int = 30
    notifications_loop_interval_sec: int = 60

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
