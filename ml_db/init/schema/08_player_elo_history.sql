-- player_elo_history: история Elo для elo_recent (30 дней) и elo_volatility (std last 20).
CREATE TABLE IF NOT EXISTS player_elo_history (
    id BIGSERIAL PRIMARY KEY,
    player_id INT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    elo_before FLOAT NOT NULL,
    elo_after FLOAT NOT NULL,
    match_date TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(player_id, match_id)
);

CREATE INDEX IF NOT EXISTS ix_player_elo_history_player_date ON player_elo_history(player_id, match_date DESC);
