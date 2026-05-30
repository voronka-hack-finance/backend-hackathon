from __future__ import annotations

from fastapi import APIRouter

from services.gateway.app.dependencies import check_gateway_ready
from services.gateway.app.openapi_descriptions import HEALTH, READY
from services.gateway.app.schemas import HealthResponse

router = APIRouter(tags=["System"])


@router.get(
    "/health",
    summary="Проверка живости gateway",
    description=HEALTH,
    response_model=HealthResponse,
)
@router.get(
    "/api/v1/health",
    summary="Проверка живости gateway (версионированный путь)",
    description=HEALTH,
    response_model=HealthResponse,
)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    summary="Проверка готовности gateway",
    description=READY,
    response_model=HealthResponse,
)
def ready() -> HealthResponse:
    check_gateway_ready()
    return HealthResponse(status="ready")
