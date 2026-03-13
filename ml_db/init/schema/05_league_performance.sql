-- League performance: ROI, upset_rate для фильтрации лиг.
CREATE TABLE IF NOT EXISTS league_performance (
    league_id VARCHAR(64) PRIMARY KEY,
    matches INT NOT NULL DEFAULT 0,
    wins INT NOT NULL DEFAULT 0,
    losses INT NOT NULL DEFAULT 0,
    stake_total FLOAT NOT NULL DEFAULT 0,
    profit_total FLOAT NOT NULL DEFAULT 0,
    roi_pct FLOAT NOT NULL DEFAULT 0,
    avg_ev FLOAT,
    avg_odds FLOAT,
    upset_rate FLOAT NOT NULL DEFAULT 0,
    underdog_wins INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_league_performance_roi ON league_performance(roi_pct);
CREATE INDEX IF NOT EXISTS ix_league_performance_matches ON league_performance(matches);
