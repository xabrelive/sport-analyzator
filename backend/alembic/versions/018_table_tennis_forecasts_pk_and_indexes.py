"""Add surrogate PK and indexes for table_tennis_forecasts.

Revision ID: 018
Revises: 017
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Добавляем surrogate PK (id BIGSERIAL) и переносим primary key с event_id на id.
    # Используем raw SQL, т.к. меняем существующий primary key.
    op.execute(
        """
        ALTER TABLE table_tennis_forecasts
        ADD COLUMN IF NOT EXISTS id BIGSERIAL;
        """
    )
    # Сбрасываем старый PK по event_id (имя по умолчанию).
    op.execute(
        """
        ALTER TABLE table_tennis_forecasts
        DROP CONSTRAINT IF EXISTS table_tennis_forecasts_pkey;
        """
    )
    # Новый PK по surrogate колонке.
    op.execute(
        """
        ALTER TABLE table_tennis_forecasts
        ADD CONSTRAINT table_tennis_forecasts_pkey PRIMARY KEY (id);
        """
    )

    # 2) Индекс по (event_id, channel) для быстрых выборок по событию и каналу.
    op.create_index(
        "ix_tt_forecasts_event_channel",
        "table_tennis_forecasts",
        ["event_id", "channel"],
    )


def downgrade() -> None:
    # Откатываем индекс и surrogate PK (оставляя таблицу в рабочем состоянии).
    op.drop_index("ix_tt_forecasts_event_channel", table_name="table_tennis_forecasts")
    op.execute(
        """
        ALTER TABLE table_tennis_forecasts
        DROP CONSTRAINT IF EXISTS table_tennis_forecasts_pkey;
        """
    )
    op.execute(
        """
        ALTER TABLE table_tennis_forecasts
        DROP COLUMN IF EXISTS id;
        """
    )
    # Возвращаем primary key на event_id (как было изначально).
    op.execute(
        """
        ALTER TABLE table_tennis_forecasts
        ADD CONSTRAINT table_tennis_forecasts_pkey PRIMARY KEY (event_id);
        """
    )

