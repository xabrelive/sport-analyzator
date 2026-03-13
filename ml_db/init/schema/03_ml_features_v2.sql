-- ML Features v2: tempo, streak, density, dominance, volatility, odds extended.
-- Запускать после 02_ml_schema.sql

ALTER TABLE match_features ADD COLUMN IF NOT EXISTS avg_sets_per_match_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS sets_over35_rate_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS streak_score FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS minutes_since_last_match_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS dominance_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS std_points_diff_last10_p1 FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS std_points_diff_last10_p2 FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS log_odds_ratio FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS implied_prob_p1 FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS implied_prob_p2 FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS market_margin FLOAT;
-- v3: momentum, set1_strength, comeback
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS momentum_today_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS set1_strength_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS comeback_rate_diff FLOAT;
