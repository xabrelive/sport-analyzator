-- ML Database Schema: игроки, матчи, сеты, коэффициенты, рейтинги, фичи, сигналы.
-- Запускается: psql -d pingwin_ml -f 02_ml_schema.sql

-- =============================================================================
-- 1. Игроки (нормализованные, связь с внешними id из BetsAPI)
-- =============================================================================
CREATE TABLE IF NOT EXISTS players (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(64) UNIQUE NOT NULL,
    name TEXT NOT NULL,
    country VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_players_external_id ON players(external_id);

-- =============================================================================
-- 2. Лиги (справочник из main DB)
-- =============================================================================
CREATE TABLE IF NOT EXISTS leagues (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- 3. Матчи
-- =============================================================================
CREATE TABLE IF NOT EXISTS matches (
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
    duration_minutes INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_matches_external_id ON matches(external_id);
CREATE INDEX IF NOT EXISTS ix_matches_start_time ON matches(start_time);
CREATE INDEX IF NOT EXISTS ix_matches_league ON matches(league_id);
CREATE INDEX IF NOT EXISTS ix_matches_players ON matches(player1_id, player2_id);

-- =============================================================================
-- 4. Сеты матча
-- =============================================================================
CREATE TABLE IF NOT EXISTS match_sets (
    id SERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    set_number INT NOT NULL,
    score_p1 INT,
    score_p2 INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(match_id, set_number)
);

CREATE INDEX IF NOT EXISTS ix_match_sets_match_id ON match_sets(match_id);

-- =============================================================================
-- 5. Прематч-коэффициенты
-- =============================================================================
CREATE TABLE IF NOT EXISTS odds (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    bookmaker VARCHAR(50) DEFAULT 'betsapi',
    odds_p1 FLOAT,
    odds_p2 FLOAT,
    snapshot_type VARCHAR(20) DEFAULT 'opening',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_odds_match_id ON odds(match_id);
CREATE INDEX IF NOT EXISTS ix_odds_created_at ON odds(created_at);

-- =============================================================================
-- 6. Live-коэффициенты
-- =============================================================================
CREATE TABLE IF NOT EXISTS odds_live (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    odds_p1 FLOAT,
    odds_p2 FLOAT,
    set_number INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_odds_live_match_id ON odds_live(match_id);

-- =============================================================================
-- 7. События матча (для live-коррекции)
-- =============================================================================
CREATE TABLE IF NOT EXISTS match_events (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    set_number INT,
    score_p1 INT,
    score_p2 INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_match_events_match_id ON match_events(match_id);

-- =============================================================================
-- 8. Elo / рейтинги игроков (снимок на момент матча)
-- =============================================================================
CREATE TABLE IF NOT EXISTS player_ratings (
    id SERIAL PRIMARY KEY,
    player_id INT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    rating FLOAT NOT NULL DEFAULT 1500.0,
    matches_played INT NOT NULL DEFAULT 0,
    last_match_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(player_id)
);

CREATE INDEX IF NOT EXISTS ix_player_ratings_player_id ON player_ratings(player_id);

-- =============================================================================
-- 9. Фичи матча (feature snapshot перед началом)
-- =============================================================================
CREATE TABLE IF NOT EXISTS match_features (
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

-- =============================================================================
-- 10. Сигналы (результат Value Detector + Signal Filter)
-- =============================================================================
CREATE TABLE IF NOT EXISTS signals (
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

CREATE INDEX IF NOT EXISTS ix_signals_match_id ON signals(match_id);
CREATE INDEX IF NOT EXISTS ix_signals_created_at ON signals(created_at);

-- =============================================================================
-- 11. Подозрительные матчи (аномалии, возможный договорняк)
-- =============================================================================
CREATE TABLE IF NOT EXISTS suspicious_matches (
    id SERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    score FLOAT NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_suspicious_matches_match_id ON suspicious_matches(match_id);
