"""Запуск Alembic миграций (используется API и tt_workers)."""
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def run_migrations() -> None:
    try:
        from alembic import command
        from alembic.config import Config

        alembic_ini = BACKEND_ROOT / "alembic.ini"
        if not alembic_ini.is_file():
            return
        config = Config(str(alembic_ini))
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        command.upgrade(config, "head")
    except Exception:
        raise
