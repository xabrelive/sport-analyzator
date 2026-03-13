-- Добавить duration_minutes в matches (для минут игры, из main DB finished_at - starts_at).
ALTER TABLE matches ADD COLUMN IF NOT EXISTS duration_minutes INT;
