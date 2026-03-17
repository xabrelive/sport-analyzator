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
    db_pool_size: int = 20
    db_pool_max_overflow: int = 20
    db_pool_recycle_sec: int = 300  # переподключение каждые 5 мин (избежать stale connections)
    # ML-база (Elo, фичи, модели, сигналы, подозрительные матчи)
    database_url_ml: str = "postgresql://pingwin:pingwin@localhost:11002/pingwin_ml"
    # ML engine selector: v1 (legacy postgres ML) | v2 (clickhouse-first)
    ml_engine: str = "v2"
    # ClickHouse for ML v2
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 11003
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "ml"

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
    # Целевой момент публикации прогноза: за ~1 час до матча.
    # Окно расчёта ML-прогнозов: от window_min до target минут до старта. Так матчи «менее чем через час» тоже получают прогноз.
    betsapi_table_tennis_forecast_target_minutes_before: int = 60
    betsapi_table_tennis_forecast_tolerance_minutes: int = 5
    betsapi_table_tennis_forecast_window_min_minutes_before: int = 1  # нижняя граница окна ML
    betsapi_table_tennis_forecast_ml_max_minutes_before: int = 60  # ML: прогнозы только за 1 ч и менее до старта
    # Legacy-совместимость (если используются в .env старые ключи окна)
    betsapi_table_tennis_forecast_min_minutes_before: int = 60
    betsapi_table_tennis_forecast_max_minutes_before: int = 180
    # Минимальный коэффициент на исход прогноза (для выбранной стороны), ниже — прогноз не даём
    # Цель — не играть откровенный 1.10–1.30, а держаться в районе 1.5+.
    betsapi_table_tennis_min_odds_for_forecast: float = 1.5
    # No-ML прогнозы: окно по минутам до старта. Прогнозы за 2 ч и менее до начала.
    betsapi_table_tennis_no_ml_forecast_min_minutes_ahead: int = 1  # не считаем матчи раньше 1 мин
    betsapi_table_tennis_no_ml_forecast_max_hours_ahead: int = 2  # 2 ч = 120 мин — верхняя граница окна
    # Лиги, для которых инвертируем выбор no_ML: рассчитали П1 — выдаём П2 и наоборот (через запятую, подстрока в league_name).
    betsapi_table_tennis_no_ml_invert_pick_league_names: str = "Czech Liga Pro,TT cup,ТТ cup,Setka Cup,Сетка Кап"
    # Лиги, для которых no_ML прогноз не выдаём (низкий % угадывания); через запятую, подстрока в league_name.
    betsapi_table_tennis_no_ml_exclude_league_names: str = ""
    # no_ML quality controls (усиление/ослабление без правок кода)
    betsapi_table_tennis_no_ml_confidence_threshold_set: float = 0.65
    betsapi_table_tennis_no_ml_confidence_threshold_match: float = 0.65
    betsapi_table_tennis_no_ml_min_matches_for_recommendation: int = 2
    betsapi_table_tennis_no_ml_min_matches_for_match_recommendation: int = 4
    betsapi_table_tennis_no_ml_min_confidence_margin: float = 0.03
    # V2 loops and KPI targets
    betsapi_table_tennis_v2_features_interval_sec: int = 300
    betsapi_table_tennis_v2_forecast_interval_sec: int = 60  # ML-прогнозы: интервал цикла (сек). 60 = раз в минуту
    betsapi_table_tennis_nn_forecast_interval_sec: int = 60  # NN-прогнозы: интервал цикла (сек). 60 = раз в минуту
    betsapi_table_tennis_no_ml_forecast_interval_sec: int = 60  # no_ML прогнозы: интервал цикла (сек). 60 = раз в минуту
    betsapi_table_tennis_early_scan_interval_sec: int = 600  # Stage 1: раз в 10 мин
    betsapi_table_tennis_v2_result_priority_interval_sec: int = 20
    betsapi_table_tennis_v2_kpi_guard_interval_sec: int = 60
    betsapi_table_tennis_v2_forecast_batch_size: int = 400
    betsapi_table_tennis_v2_target_hit_rate: float = 85.0
    betsapi_table_tennis_v2_target_picks_per_day: int = 300
    betsapi_table_tennis_v2_min_confidence_floor: float = 55.0
    betsapi_table_tennis_v2_min_confidence_ceiling: float = 88.0
    betsapi_table_tennis_v2_base_min_confidence: float = 60.0  # кандидаты с P >= 60%
    betsapi_table_tennis_v2_min_edge_floor: float = 0.0
    betsapi_table_tennis_v2_min_edge_ceiling: float = 8.0
    betsapi_table_tennis_v2_base_min_edge: float = 0.0
    # Игрок в приоритете: модель не использует линию (коэф) для предсказания, только силу/форму игроков.
    ml_v2_disable_market_features: bool = True
    # Paid ML: quality-first профиль (меньше сигналов, выше средний коэффициент/уверенность).
    betsapi_table_tennis_v2_preferred_min_odds: float = 1.75
    betsapi_table_tennis_v2_allow_soft_fallback: bool = False
    betsapi_table_tennis_v2_allow_hard_confidence_fallback: bool = False  # quality-first: fallback только при явном включении
    betsapi_table_tennis_v2_min_confidence_to_publish: float = 60.0  # публикуем если P >= 60%
    betsapi_table_tennis_nn_min_confidence_to_publish: float = 62.0  # NN: публикуем только уверенные сигналы
    betsapi_table_tennis_nn_min_match_confidence_pct: float = 66.0  # NN: минимум уверенности по исходу матча
    betsapi_table_tennis_nn_min_set1_confidence_pct: float = 67.0  # NN: минимум уверенности по 1-му сету
    betsapi_table_tennis_nn_allow_hard_confidence_fallback: bool = False  # false = не публиковать NN "любой ценой", только строгие сигналы
    # NN thresholds (отдельно от ML paid), чтобы NN-канал не зажимался quality-фильтрами ML.
    betsapi_table_tennis_nn_confidence_filter_min_pct: float = 62.0
    betsapi_table_tennis_nn_preferred_min_odds: float = 1.6
    betsapi_table_tennis_v2_prioritize_quality_over_volume: bool = True
    # Доп. порог в селекторе: только кандидаты с P >= этого %.
    betsapi_table_tennis_v2_confidence_filter_min_pct: float = 65.0
    # ML: исключить лиги из публикации (через запятую, подстрока в league_name).
    betsapi_table_tennis_v2_exclude_league_names: str = ""
    # Если коэффициент на выбранную сторону < этого порога — для ML переворачиваем сторону (дом/гость) и текст.
    betsapi_table_tennis_v2_invert_low_odds_threshold: float = 1.5
    table_tennis_match_sets_to_win: int = 3
    # ML pipeline: синхронизация main→ML и переобучение, интервал в секундах (0 = отключено)
    ml_sync_interval_sec: int = 600  # 10 мин: подтяжка данных + retrain
    ml_sync_standalone: bool = False  # true = цикл подтяжки не запускать в tt_workers/backend (запускать отдельным процессом ml_sync)
    ml_model_dir: str = "/tmp/pingwin_ml_models"
    ml_use_gpu: bool = True  # ML_USE_GPU=false — принудительно CPU (Docker без --gpus)
    ml_retrain_min_new_matches: int = 500  # 500+ для стабильной модели (меньше шума)
    ml_retrain_interval_sec: int = 1800  # 30 мин: плановый retrain
    ml_sync_days_back: int = 0  # 0 = весь архив, иначе N дней назад
    ml_sync_batch_size: int = 15000  # батч синхронизации main→ML (больше = быстрее)
    ml_backfill_workers: int = 6  # параллельных воркеров для backfill фичей
    # ML v2 feature catch-up: сколько "missing" батчей делать за один цикл ml_sync_loop.
    ml_v2_missing_backfill_passes_per_cycle: int = 4
    # Размер одного батча missing backfill в v2.
    ml_v2_missing_backfill_limit: int = 25000
    # Размер порции авто-refresh исторических фич при смене feature schema.
    ml_v2_refresh_backfill_limit: int = 20000
    # Размер порции автозаполнения ml.player_daily_stats из ml.player_match_stats.
    ml_v2_player_daily_backfill_limit: int = 50000
    # Временной сплит датасета: 2016 warmup, 2017–2022 train, 2023–2024 val.
    ml_train_year_start: int = 2017
    ml_train_year_end: int = 2022
    ml_train_limit: int = 0  # 0 = безлимит (все матчи за годы); иначе макс. строк для match/set1
    ml_train_set_limit: int = 0  # 0 = безлимит (все сеты за годы); иначе макс. строк для set/p_point
    ml_train_min_sample_size: int = 0  # 0 = все матчи; 20+ = только с достаточной историей
    ml_val_year_start: int = 2023
    ml_val_year_end: int = 2024
    ml_val_limit: int = 100_000  # макс. строк для валидации (2023–2024)
    ml_warmup_year_end: int = 2016
    # Фильтр по коэффициентам при обучении (0 = выкл): 1.4–3.0 — не только фавориты
    ml_train_odds_min: float = 0.0
    ml_train_odds_max: float = 999.0
    # Ансамбль: P_final = ml_ensemble_elo_weight * P_elo + (1 - ml_ensemble_elo_weight) * P_ml
    ml_ensemble_elo_weight: float = 0.35
    # LightGBM: early stopping (0 = выкл). Последние 10% данных — validation.
    ml_lgb_early_stopping_rounds: int = 500
    ml_v2_lgb_min_child_samples: int = 20
    ml_v2_lgb_learning_rate: float = 0.02
    ml_v2_lgb_num_leaves: int = 128
    # target_match: больше листьев и меньше min_child — сильнее сигнал (corr 0.24); при переобучении — усилить reg.
    ml_v2_lgb_num_leaves_match: int = 150
    ml_v2_lgb_min_child_match: int = 20
    ml_v2_lgb_reg_alpha_match: float = 0.3
    ml_v2_lgb_reg_lambda_match: float = 1.0
    # target_set1: без ограничений val logloss взлетает до 13+ (best_iteration=1), сильнее регуляризация.
    ml_v2_lgb_num_leaves_set1: int = 96
    ml_v2_lgb_min_child_set1: int = 30
    ml_v2_lgb_reg_alpha_set1: float = 0.7
    ml_v2_lgb_reg_lambda_set1: float = 1.8
    ml_v2_feature_clip_quantile: float = 0.01  # клип фичей по квантилям (0.01/0.99), меньше — больше сигнала
    ml_v2_top_k_features: int = 0  # топ-K фичей по |corr| (0 = все). При 50 меньше шума, но test logloss чуть выше.
    ml_v2_split_by_year: bool = True  # train 2016–2023, val 2024, test 2025+
    # v2 inference/eval ensemble: p_final = (1-w)*p_ml + w*p_elo
    ml_v2_ensemble_elo_weight: float = 0.3
    # v2 train quality filters: suppress cold-start noise in training set.
    ml_v2_train_min_matches_played_before: int = 10
    ml_v2_train_require_h2h: bool = False  # False = больше данных; True = только матчи с личной встречей
    ml_v2_train_max_league_upset_rate: float = 0.45  # лиги с upset rate > — исключаем из train (chaos leagues)
    ml_v2_use_experience_regimes: bool = True  # True = обучать 4 модели (rookie/low/mid/pro); инференс всегда использует bucket-модели при наличии файлов
    ml_v2_experience_regime_min_train: int = 500  # минимум строк в bucket для обучения отдельной модели
    ml_v2_enable_nn: bool = True  # обучать и использовать NN-модели (MLP) как отдельный канал "nn"
    ml_v2_nn_hidden_layers: str = "128,64"
    ml_v2_nn_learning_rate: float = 0.001
    ml_v2_nn_alpha: float = 0.0001
    ml_v2_nn_batch_size: int = 256
    ml_v2_nn_max_iter: int = 120
    # Guard against time-of-day leakage: disable clock-derived features in v2 model.
    ml_v2_disable_clock_features: bool = True

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
    # Отдельные боты для каждого канала (если заданы, перекрывают общий telegram_bot_token)
    telegram_signals_free_bot_token: str = ""
    telegram_signals_vip_bot_token: str = ""
    telegram_signals_no_ml_bot_token: str = ""
    telegram_signals_no_ml_chat_id: str = ""
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
    # Новые прогнозы доставляем максимально быстро (обычно <= 20 сек).
    notifications_loop_interval_sec: int = 20
    # 0 = не отправлять сразу после расчёта, а дождаться batch-окна ниже.
    notifications_immediate_after_forecast_sec: int = 0
    notifications_new_forecast_batch_minutes: int = 10

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
