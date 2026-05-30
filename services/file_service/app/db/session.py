from common.db import build_engine, build_session_factory

from services.file_service.app.config import settings

engine = build_engine(settings.database_url)
SessionLocal = build_session_factory(settings.database_url)
