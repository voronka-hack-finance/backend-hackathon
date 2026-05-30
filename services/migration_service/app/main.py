import logging
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from services.migration_service.app.bootstrap import run_bootstrap
from services.migration_service.app.config import settings
from services.migration_service.app.reset import reset_application_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def main() -> None:
    engine = _wait_for_postgres()
    _apply_migrations(engine)
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


def _apply_migrations(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                create table if not exists schema_migrations (
                  version text primary key,
                  applied_at timestamptz not null default now()
                )
                """
            )
        )

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        sql = path.read_text(encoding="utf-8")
        with engine.begin() as conn:
            already_applied = conn.scalar(
                text("select 1 from schema_migrations where version = :version"),
                {"version": version},
            )
            if already_applied:
                continue
            conn.exec_driver_sql(sql)
            conn.execute(text("insert into schema_migrations(version) values (:version)"), {"version": version})


if __name__ == "__main__":
    main()
