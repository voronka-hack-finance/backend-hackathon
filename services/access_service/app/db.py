from common.db import build_session_factory

from services.access_service.app.config import settings

SessionLocal = build_session_factory(settings.database_url)
