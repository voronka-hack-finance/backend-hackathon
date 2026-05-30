from common.messaging import MessageWorker, check_rabbitmq
from common.service_app import create_worker_app
from sqlalchemy import select

from services.access_service.app.config import settings
from services.access_service.app.db import SessionLocal
from services.access_service.app.handlers import MESSAGE_HANDLERS
from services.access_service.app.models import User

SERVICE_NAME = "access-service"
QUEUE_NAME = "access-service"

worker = MessageWorker(
    rabbitmq_url=settings.rabbitmq_url,
    queue_name=QUEUE_NAME,
    service_name=SERVICE_NAME,
    handlers={},
)


def _ready() -> None:
    with SessionLocal() as db:
        db.execute(select(User.id).limit(1))
    check_rabbitmq(settings.rabbitmq_url)


app = create_worker_app(title=SERVICE_NAME, worker=worker, handlers=MESSAGE_HANDLERS, ready_check=_ready)
