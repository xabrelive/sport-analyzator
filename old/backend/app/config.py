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
    # Публичный URL для ссылок в сообщениях (TG, email). Если задан — в ссылках используется он вместо frontend_url (например https://pingwin.pro).
    frontend_public_url: str = ""

    # API
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    admin_secret: str = ""  # X-Admin-Key для выдачи подписок по user_id
    # Доп. CORS origins (через запятую), например http://192.168.31.130:3000 для доступа по LAN
    cors_extra_origins: str = ""

    # Providers
    sportradar_api_key: str = ""
    sportmonks_api_key: str = ""
    the_odds_api_key: str = ""
    # BetsAPI — настольный теннис (и др.): https://betsapi.com, токен и sport_id
    betsapi_token: str = ""
    betsapi_table_tennis_sport_id: int = 92
    # Ранее лимит на кол-во матчей для запросов коэффициентов; сейчас: лайв — все, линия — один раз (не используется)
    betsapi_max_events_for_odds: int = 50

    # Telegram (for signal engine and per-user delivery)
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""  # для ссылки привязки: t.me/{username}?start=link_XXX
    # Каналы рассылки: бесплатный и платный (ID чата/канала или @username)
    telegram_signals_chat_id: str = ""           # бесплатные сигналы (3–4 в сутки, кф ≤2, уверенность ~100%)
    telegram_signals_paid_chat_id: str = ""      # платные сигналы
    # Бесплатный канал: пока не отправляем (free_channel_enabled=False). При True — до 3–4 в сутки.
    free_channel_enabled: bool = False
    free_channel_max_per_day: int = 4
    free_channel_min_confidence_pct: float = 98.0   # уверенность близкая к 100%
    free_channel_max_odds: float = 2.0               # кф до 2
    free_channel_min_minutes_before_start: int = 60  # до начала матча не менее 60 мин
    free_channel_window_start_hour_msk: int = 9      # окно рассылки МСК: с 9:00
    free_channel_window_end_hour_msk: int = 21      # по 21:00
    free_channel_min_interval_minutes: int = 60     # минимум 1 час между сообщениями
    # Платный канал: 1–3 раза в час, один прогноз с макс. вероятностью захода (по спорту); экспресс — позже
    paid_channel_max_per_hour: int = 3
    paid_channel_min_interval_minutes: int = 20    # минимум ~20 мин между сообщениями (чтобы не больше 3/час)

    # Email (SMTP для рассылки сигналов и писем; если не задано — только логирование)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    # Value / Probability
    value_ev_threshold: float = 0.05
    min_odds: float = 1.01
    max_odds: float = 50.0

    # Интервалы опроса внешних API (BetsAPI, The Odds API, Sportradar)
    # Лайв каждые 4 с — более частое обновление счёта, при этом остаётся запас по лимиту 3600/час (учитывая линию, disappeared и архив).
    live_poll_interval_seconds: int = 4
    live_odds_poll_interval_seconds: int = 30  # The Odds API (если задан ключ)
    prematch_poll_interval_seconds: int = 180  # Линия: upcoming + view + odds. Каждые 3 мин — кф подгружаются чаще.

    # Лимит запросов BetsAPI: 3600/час — распределяем между линией, лайвом, архивом, disappeared
    betsapi_rate_limit_per_hour: int = 3600
    # За один цикл линии — макс. запросов v4 bet365/prematch за один проход. По всем остальным кф доберёт backfill через 2 мин.
    # Ставим 400, чтобы кф появлялись сразу у большинства и матчи не пропускались.
    betsapi_line_max_odds_requests_per_run: int = 400

    # Догрузка кф линии: матчи без line OddsSnapshot (scheduled/pending_odds). Раз в N сек, batch за один запуск.
    line_odds_backfill_interval_seconds: int = 60  # раз в минуту — чтобы кф появлялись сразу после открытия линии
    line_odds_backfill_batch_size: int = 150  # матчей за один запуск

    # Авто-загрузка архива BetsAPI: раз в 2 часа, за текущий и предыдущий день
    betsapi_history_auto_interval_seconds: int = 7200  # 2 часа
    betsapi_history_auto_days: int = 2  # сегодня + вчера
    betsapi_history_delay_seconds: float = 2.0         # пауза между страницами day/page при автозагрузке
    # Авто-backfill рекомендаций для активных матчей (чтобы stats/таблицы не отставали).
    recommendations_backfill_interval_seconds: int = 60
    recommendations_backfill_active_limit: int = 300
    # Рекомендации: учитывать только матчи за последние N дней (приоритет свежей формы).
    recommendation_lookback_days: int = 180
    # При достаточном кол-ве матчей за последние N дней — использовать это окно (неделя/месяц).
    recommendation_prefer_recent_days: int | None = 30
    # Минимум матчей в лиге у каждого игрока, чтобы использовать статистику по лиге; иначе — по всем лигам.
    recommendation_min_matches_in_league: int = 3
    # Backpressure для ручной/авто загрузки архива: не даём history забить очередь normalize
    # Для больших ручных прогонов история может стартовать при уже большой очереди normalize.
    # Низкий порог полностью "замораживает" загрузку на часы.
    betsapi_history_normalize_queue_max_depth: int = 10000
    betsapi_history_backpressure_sleep_seconds: float = 0.5

    # Догрузка результатов при сбоях: матчи без результата, старт > 2ч назад; не более 3 попыток (2ч, 7ч, 24ч от начала)
    result_backfill_interval_seconds: int = 120  # раз в 2 минуты проверять и догружать
    result_backfill_batch_size: int = 10  # макс. матчей за один запуск

    # Матч пропал из inplay без результата: повторные запросы через 15 мин, 1 ч, 2 ч (в секундах)
    disappeared_retry_delays_seconds: tuple[int, ...] = (15 * 60, 60 * 60, 2 * 60 * 60)
    disappeared_retry_max_attempts: int = 3

    # Биллинг (YooKassa)
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_webhook_secret: str = ""  # опционально для проверки подписи
    billing_return_url: str = ""  # куда вернуть после оплаты (frontend URL)
    billing_success_path: str = "/pricing?paid=1"
    enable_demo_grant: bool = False  # если True — POST /me/subscriptions выдаёт подписку без оплаты (для тестов)

    # Флаги для управления плановыми задачами
    enable_scheduled_collectors: bool = False          # включить live/full/odds
    enable_betsapi_history_auto: bool = False          # включить автоматическую загрузку архива (только за сегодня)

    @property
    def async_database_url(self) -> str:
        if self.database_url_async:
            return self.database_url_async
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url


settings = Settings()
