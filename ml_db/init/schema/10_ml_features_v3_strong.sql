-- ML Features v3: сильные фичи для модели.
-- dominance_last_50, fatigue_ratio, elo_volatility, odds_shift, minutes_to_match, etc.

ALTER TABLE match_features ADD COLUMN IF NOT EXISTS dominance_last_50_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS fatigue_index_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS fatigue_ratio FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS minutes_to_match FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS odds_shift_p1 FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS odds_shift_p2 FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS elo_volatility_p1 FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS elo_volatility_p2 FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS elo_volatility_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS daily_performance_trend_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS dominance_trend_diff FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS style_clash FLOAT;
