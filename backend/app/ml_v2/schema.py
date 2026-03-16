"""DDL bootstrap for ML v2 ClickHouse schema."""
from __future__ import annotations

from app.ml_v2.ch_client import get_ch_client


DDL: list[str] = [
    "CREATE DATABASE IF NOT EXISTS ml",
    """
    CREATE TABLE IF NOT EXISTS ml.players (
      player_id String,
      player_name String,
      updated_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(updated_at)
    ORDER BY (player_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.leagues (
      league_id String,
      league_name String,
      updated_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(updated_at)
    ORDER BY (league_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.matches (
      match_id String,
      start_time DateTime,
      league_id String,
      player1_id String,
      player2_id String,
      score_sets_p1 Int16,
      score_sets_p2 Int16,
      odds_p1 Float64,
      odds_p2 Float64,
      created_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(created_at)
    PARTITION BY toYYYYMM(start_time)
    ORDER BY (start_time, match_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.match_sets (
      match_id String,
      set_number UInt8,
      score_p1 Int16,
      score_p2 Int16,
      created_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(created_at)
    PARTITION BY toYYYYMM(created_at)
    ORDER BY (match_id, set_number)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.player_elo_history (
      player_id String,
      match_id String,
      match_time DateTime,
      elo_before Float64,
      elo_after Float64,
      created_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(created_at)
    PARTITION BY toYYYYMM(match_time)
    ORDER BY (player_id, match_time, match_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.player_match_stats (
      player_id String,
      match_id String,
      match_time DateTime,
      league_id String,
      win UInt8,
      set1_win UInt8,
      sets_won Int16,
      sets_lost Int16,
      points_won Int32,
      points_lost Int32,
      duration_minutes Int32,
      created_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(created_at)
    PARTITION BY toYYYYMM(match_time)
    ORDER BY (player_id, match_time, match_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.player_daily_stats (
      player_id String,
      date Date,
      matches_today UInt16,
      sets_today UInt16,
      minutes_today UInt32,
      wins_today UInt16,
      losses_today UInt16,
      created_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(created_at)
    PARTITION BY toYYYYMM(date)
    ORDER BY (player_id, date)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.match_features (
      match_id String,
      start_time DateTime,
      league_id String,
      player1_id String,
      player2_id String,
      elo_diff Float64,
      elo_trend_diff Float64,
      elo_volatility_diff Float64,
      form_diff Float64,
      winrate_10_diff Float64,
      winrate_20_diff Float64,
      sets_ratio_20_diff Float64,
      points_ratio_20_diff Float64,
      dominance_diff Float64,
      dominance_last_50_diff Float64,
      fatigue_diff Float64,
      fatigue_ratio Float64,
      matches_24h_diff Float64,
      sets_24h_diff Float64,
      minutes_24h_diff Float64,
      momentum_today_diff Float64,
      streak_score Float64,
      recent_improvement_diff Float64,
      style_clash Float64,
      h2h_diff Float64,
      h2h_count Float64,
      comeback_rate_diff Float64,
      set1_strength_diff Float64,
      elo_x_fatigue Float64,
      std_points_last20_diff Float64,
      points_ratio_last_30_diff Float64,
      sets_ratio_last_30_diff Float64,
      avg_sets_per_match_diff Float64,
      avg_points_per_set_diff Float64,
      match_duration_proxy_diff Float64,
      tempo_diff Float64,
      fatigue_index_diff Float64,
      temporal_strength_diff Float64,
      latent_strength_diff Float64,
      league_upset_rate Float64,
      league_winrate_variance Float64,
      league_dominance_variance Float64,
      matches_played_before Float64,
      p1_exp_bucket Float64,
      p2_exp_bucket Float64,
      experience_bucket_diff Float64,
      experience_mismatch Float64,
      elo_x_experience Float64,
      market_margin Float64,
      target_match UInt8,
      target_set1 UInt8,
      created_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(created_at)
    PARTITION BY toYYYYMM(start_time)
    ORDER BY (start_time, match_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.model_runs (
      run_id String,
      model_name String,
      model_version String,
      started_at DateTime,
      finished_at DateTime,
      status String,
      params_json String,
      metrics_json String,
      created_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(created_at)
    ORDER BY (run_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.model_metrics (
      run_id String,
      target String,
      split String,
      metric_name String,
      metric_value Float64,
      created_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(created_at)
    ORDER BY (run_id, target, split, metric_name)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.predictions (
      event_id String,
      created_at DateTime,
      market String,
      p_home Float64,
      p_away Float64,
      confidence Float64,
      model_version String
    ) ENGINE = ReplacingMergeTree(created_at)
    PARTITION BY toYYYYMM(created_at)
    ORDER BY (created_at, event_id, market)
    """,
    """
    CREATE TABLE IF NOT EXISTS ml.job_state (
      job_name String,
      cursor_value String,
      updated_at DateTime DEFAULT now()
    ) ENGINE = ReplacingMergeTree(updated_at)
    ORDER BY (job_name)
    """,
]


def ensure_schema() -> None:
    client = get_ch_client()
    for ddl in DDL:
        client.command(ddl)
    # Online schema evolution for existing clusters.
    for col_ddl in (
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS std_points_last20_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS points_ratio_last_30_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS sets_ratio_last_30_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS avg_sets_per_match_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS avg_points_per_set_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS match_duration_proxy_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS tempo_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS fatigue_index_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS temporal_strength_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS latent_strength_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_upset_rate Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_winrate_variance Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_dominance_variance Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS matches_played_before Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS p1_exp_bucket Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS p2_exp_bucket Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS experience_bucket_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS experience_mismatch Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS elo_x_experience Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS elo_trend_30_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS elo_peak_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS elo_drop_10_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS elo_gain_10_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS elo_recent_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS winrate_3_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS winrate_5_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS winrate_30_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS winrate_50_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS sets_ratio_10_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS sets_ratio_50_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS points_ratio_10_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS points_ratio_50_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS dominance_last_10_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS dominance_last_20_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS fatigue_pressure_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS matches_3h_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS matches_6h_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS matches_12h_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS strength_trend_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS matches_7d_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS rest_hours_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS rest_days_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS long_match_ratio_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS momentum_last3_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS momentum_last5_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS win_streak_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS loss_streak_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS aggressive_ratio_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS defensive_ratio_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS fast_match_ratio_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS long_rally_ratio_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS hour_strength_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS morning_strength_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS evening_strength_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS weekend_strength_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS h2h_winrate Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS h2h_last_result Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS h2h_last3_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS h2h_last5_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS h2h_recent_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS h2h_dominance Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS reverse_sweep_rate_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS choke_rate_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS std_sets_last20_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS variance_winrate_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS consistency_score_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS table_bias Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_match_count Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS experience_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS volatility_combo_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS form_x_fatigue_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS momentum_x_rest_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS h2h_x_form Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS fatigue_ratio_log Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS experience_ratio Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS elo_confidence_gap Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS style_momentum_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS temporal_form_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_upset_x_margin Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_bias_x_margin Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS elo_decay_7_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS elo_decay_30_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS elo_momentum_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS matches_48h_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS matches_72h_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_rating Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS market_prob_p1 Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS market_prob_p2 Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS market_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS closing_line Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS matches_3d_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS points_24h_diff Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_strength Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_avg_sets Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_variance Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_match_volume Float64",
        "ALTER TABLE ml.match_features ADD COLUMN IF NOT EXISTS league_id_encoded Float64",
    ):
        client.command(col_ddl)

