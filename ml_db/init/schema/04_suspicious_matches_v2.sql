-- Suspicious matches v2: расширенные колонки для детекции договорных.
ALTER TABLE suspicious_matches ADD COLUMN IF NOT EXISTS odds_shift FLOAT;
ALTER TABLE suspicious_matches ADD COLUMN IF NOT EXISTS comeback_flag BOOLEAN DEFAULT FALSE;
ALTER TABLE suspicious_matches ADD COLUMN IF NOT EXISTS model_error FLOAT;
