import logging
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from services.migration_service.app.bootstrap import run_bootstrap
from services.migration_service.app.config import settings
from services.migration_service.app.reset import reset_application_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MIGRATION_SERVICE_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = MIGRATION_SERVICE_DIR / "alembic.ini"
BASELINE_REVISION = "0001_initial_schema"


def main() -> None:
    engine = _wait_for_postgres()
    _upgrade_schema(engine)
    reset_application_data(engine)
    run_bootstrap(engine)


def _wait_for_postgres():
    engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
    deadline = time.monotonic() + 90
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("select 1"))
            return engine
        except OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def _upgrade_schema(engine) -> None:
    alembic_config = _alembic_config()
    if _needs_legacy_bridge(engine):
        logger.info("Legacy schema_migrations detected; stamping Alembic baseline before upgrade")
        command.stamp(alembic_config, BASELINE_REVISION)
    command.upgrade(alembic_config, "head")
    _drop_legacy_schema_migrations(engine)


def _alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATION_SERVICE_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def _needs_legacy_bridge(engine) -> bool:
    with engine.begin() as conn:
        has_legacy = conn.scalar(
            text("select to_regclass('public.schema_migrations') is not null")
        )
        if not has_legacy:
            return False
        legacy_count = conn.scalar(text("select count(*) from schema_migrations")) or 0
        if legacy_count == 0:
            return False
        has_alembic = conn.scalar(text("select to_regclass('public.alembic_version') is not null"))
        if not has_alembic:
            return True
        alembic_count = conn.scalar(text("select count(*) from alembic_version")) or 0
        return alembic_count == 0


def _drop_legacy_schema_migrations(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("drop table if exists schema_migrations"))


if __name__ == "__main__":
    main()
