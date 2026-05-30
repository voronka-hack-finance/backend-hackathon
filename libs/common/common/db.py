from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True, future=True)


def build_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=build_engine(database_url),
        expire_on_commit=False,
    )


def session_dependency(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
