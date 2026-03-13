-- Миграция pingwin_ml к новой схеме (external_id VARCHAR, league_id VARCHAR)
BEGIN;
DROP TABLE IF EXISTS suspicious_matches CASCADE;
DROP TABLE IF EXISTS signals CASCADE;
DROP TABLE IF EXISTS match_features CASCADE;
DROP TABLE IF EXISTS player_ratings CASCADE;
DROP TABLE IF EXISTS match_events CASCADE;
DROP TABLE IF EXISTS odds_live CASCADE;
DROP TABLE IF EXISTS odds CASCADE;
DROP TABLE IF EXISTS match_sets CASCADE;
DROP TABLE IF EXISTS matches CASCADE;
DROP TABLE IF EXISTS players CASCADE;

CREATE TABLE players (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(64) UNIQUE NOT NULL,
    name TEXT NOT NULL,
    country VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_players_external_id ON players(external_id);

CREATE TABLE matches (
    id BIGSERIAL PRIMARY KEY,
    external_id VARCHAR(64) UNIQUE NOT NULL,
    league_id VARCHAR(64) NOT NULL,
    league_name VARCHAR(255),
    player1_id INT REFERENCES players(id),
    player2_id INT REFERENCES players(id),
    start_time TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    score_sets_p1 INT,
    score_sets_p2 INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_matches_external_id ON matches(external_id);
CREATE INDEX ix_matches_start_time ON matches(start_time);
CREATE INDEX ix_matches_league ON matches(league_id);
CREATE INDEX ix_matches_players ON matches(player1_id, player2_id);

CREATE TABLE match_sets (
    id SERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    set_number INT NOT NULL,
    score_p1 INT,
    score_p2 INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(match_id, set_number)
);
CREATE INDEX ix_match_sets_match_id ON match_sets(match_id);

CREATE TABLE odds (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    bookmaker VARCHAR(50) DEFAULT 'betsapi',
    odds_p1 FLOAT,
    odds_p2 FLOAT,
    snapshot_type VARCHAR(20) DEFAULT 'opening',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_odds_match_id ON odds(match_id);

CREATE TABLE odds_live (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    odds_p1 FLOAT,
    odds_p2 FLOAT,
    set_number INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_odds_live_match_id ON odds_live(match_id);

CREATE TABLE match_events (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    set_number INT,
    score_p1 INT,
    score_p2 INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_match_events_match_id ON match_events(match_id);

CREATE TABLE player_ratings (
    id SERIAL PRIMARY KEY,
    player_id INT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    rating FLOAT NOT NULL DEFAULT 1500.0,
    matches_played INT NOT NULL DEFAULT 0,
    last_match_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(player_id)
);
CREATE INDEX ix_player_ratings_player_id ON player_ratings(player_id);

CREATE TABLE match_features (
    match_id BIGINT PRIMARY KEY REFERENCES matches(id) ON DELETE CASCADE,
    elo_p1 FLOAT,
    elo_p2 FLOAT,
    elo_diff FLOAT,
    form_p1 FLOAT,
    form_p2 FLOAT,
    form_diff FLOAT,
    fatigue_p1 FLOAT,
    fatigue_p2 FLOAT,
    fatigue_diff FLOAT,
    h2h_count INT DEFAULT 0,
    h2h_p1_wr FLOAT,
    h2h_diff FLOAT,
    winrate_10_p1 FLOAT,
    winrate_10_p2 FLOAT,
    winrate_10_diff FLOAT,
    odds_p1 FLOAT,
    odds_p2 FLOAT,
    odds_diff FLOAT,
    league_id VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE signals (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    bet_type VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    odds FLOAT NOT NULL,
    probability FLOAT NOT NULL,
    expected_value FLOAT NOT NULL,
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_signals_match_id ON signals(match_id);

CREATE TABLE suspicious_matches (
    id SERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    score FLOAT NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_suspicious_matches_match_id ON suspicious_matches(match_id);

COMMIT;
