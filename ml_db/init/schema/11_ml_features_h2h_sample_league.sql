-- hours_since_last_h2h: повторная встреча < 24h — очень сильный сигнал (Tier A).
-- sample_size: объём истории (для фильтрации при обучении: только матчи с достаточными данными).
-- league_upset_rate: доля побед андердога по Elo в лиге (Tier A, стабильность лиги).

ALTER TABLE match_features ADD COLUMN IF NOT EXISTS hours_since_last_h2h FLOAT;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS sample_size INT DEFAULT 0;
ALTER TABLE match_features ADD COLUMN IF NOT EXISTS league_upset_rate FLOAT;
