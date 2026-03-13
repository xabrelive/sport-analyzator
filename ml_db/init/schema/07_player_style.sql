-- player_style: tempo, aggression, comeback, close_match (улучшает set prediction).
CREATE TABLE IF NOT EXISTS player_style (
    player_id INT PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
    tempo_index FLOAT NOT NULL DEFAULT 0,
    aggression_index FLOAT NOT NULL DEFAULT 0,
    comeback_index FLOAT NOT NULL DEFAULT 0,
    close_match_index FLOAT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
