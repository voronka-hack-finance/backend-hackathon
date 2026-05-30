from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.finance_service.app.config import settings


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
