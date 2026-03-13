-- player_daily_stats: форма внутри дня (TT — спорт формы внутри дня).
CREATE TABLE IF NOT EXISTS player_daily_stats (
    player_id INT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    matches_played INT NOT NULL DEFAULT 0,
    wins INT NOT NULL DEFAULT 0,
    losses INT NOT NULL DEFAULT 0,
    sets_won INT NOT NULL DEFAULT 0,
    sets_lost INT NOT NULL DEFAULT 0,
    points_won INT NOT NULL DEFAULT 0,
    points_lost INT NOT NULL DEFAULT 0,
    minutes_played INT NOT NULL DEFAULT 0,
    fatigue_index FLOAT NOT NULL DEFAULT 0,
    momentum FLOAT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, date)
);

CREATE INDEX IF NOT EXISTS ix_player_daily_stats_player_date ON player_daily_stats(player_id, date);
