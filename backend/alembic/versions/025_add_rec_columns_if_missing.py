"""Ensure confidence_pct and free_channel_sent_at exist (fix when 024 was stamped without applying)."""
from alembic import op

revision = "025_rec_cols_if_missing"
down_revision = "024_rec_confidence_free"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'match_recommendations' AND column_name = 'confidence_pct'
          ) THEN
            ALTER TABLE match_recommendations ADD COLUMN confidence_pct NUMERIC(5, 2);
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'match_recommendations' AND column_name = 'free_channel_sent_at'
          ) THEN
            ALTER TABLE match_recommendations ADD COLUMN free_channel_sent_at TIMESTAMP WITH TIME ZONE;
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_column("match_recommendations", "free_channel_sent_at")
    op.drop_column("match_recommendations", "confidence_pct")
