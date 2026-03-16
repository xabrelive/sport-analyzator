CREATE DATABASE IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS ml.players (
  player_id String,
  player_name String,
  updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (player_id);

CREATE TABLE IF NOT EXISTS ml.leagues (
  league_id String,
  league_name String,
  updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (league_id);

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
ORDER BY (start_time, match_id);

CREATE TABLE IF NOT EXISTS ml.match_sets (
  match_id String,
  set_number UInt8,
  score_p1 Int16,
  score_p2 Int16,
  created_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (match_id, set_number);

CREATE TABLE IF NOT EXISTS ml.player_elo_history (
  player_id String,
  match_id String,
  match_time DateTime,
  elo_before Float64,
  elo_after Float64,
  created_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(match_time)
ORDER BY (player_id, match_time, match_id);

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
ORDER BY (player_id, match_time, match_id);

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
ORDER BY (player_id, date);

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
  std_points_last10_diff Float64,
  market_margin Float64,
  target_match UInt8,
  target_set1 UInt8,
  created_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(start_time)
ORDER BY (start_time, match_id);

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
ORDER BY (run_id);

CREATE TABLE IF NOT EXISTS ml.model_metrics (
  run_id String,
  target String,
  split String,
  metric_name String,
  metric_value Float64,
  created_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (run_id, target, split, metric_name);

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
ORDER BY (created_at, event_id, market);

CREATE TABLE IF NOT EXISTS ml.job_state (
  job_name String,
  cursor_value String,
  updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (job_name);

