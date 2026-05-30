from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import HEALTH_SCORE_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.rpc import rpc_call
from services.gateway.app.schemas import (
    FinancialHealthHistoryPageResponse,
    FinancialHealthProfileResponse,
    FinancialHealthScoreResponse,
)

router = APIRouter(prefix="/api/v1/health", tags=["Financial Health"])

PROFILE_DESCRIPTION = (
    "Returns a full financial and credit health profile for the authenticated user. "
    "The service calculates the profile from transaction, account, goal, limit, and analytics RPC data, "
    "caches the monthly snapshot, and reports data gaps for metrics that are not fully available in the MVP."
)
SCORE_DESCRIPTION = (
    "Returns the compact monthly health score: financial health score, status label, credit load index, "
    "credit zone, top risk drivers, and known data gaps. Use refresh=true to force recalculation."
)
HISTORY_DESCRIPTION = (
    "Returns previously calculated monthly health snapshots for the authenticated user. "
    "The endpoint is paginated and reads only cached snapshots produced by profile or score calculation."
)


@router.get(
    "/profile",
    summary="Financial health profile",
    description=PROFILE_DESCRIPTION,
    response_model=FinancialHealthProfileResponse,
    responses=PROTECTED_RESPONSES,
)
def health_profile(
    user: UserContext = Depends(current_user),
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$", description="Calendar month in YYYY-MM format. Defaults to current UTC month."),
    refresh: bool = Query(default=False, description="Force recalculation instead of returning a cached monthly snapshot."),
) -> dict:
    return rpc_call(HEALTH_SCORE_QUEUE, "health.profile.get", {"period": period, "refresh": refresh}, user=user)


@router.get(
    "/score",
    summary="Financial health score",
    description=SCORE_DESCRIPTION,
    response_model=FinancialHealthScoreResponse,
    responses=PROTECTED_RESPONSES,
)
def health_score(
    user: UserContext = Depends(current_user),
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$", description="Calendar month in YYYY-MM format. Defaults to current UTC month."),
    refresh: bool = Query(default=False, description="Force recalculation instead of returning a cached monthly snapshot."),
) -> dict:
    return rpc_call(HEALTH_SCORE_QUEUE, "health.score.get", {"period": period, "refresh": refresh}, user=user)


@router.get(
    "/history",
    summary="Financial health history",
    description=HISTORY_DESCRIPTION,
    response_model=FinancialHealthHistoryPageResponse,
    responses=PROTECTED_RESPONSES,
)
def health_history(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Page number."),
    page_size: int = Query(default=12, ge=1, le=500, description="Page size."),
) -> dict:
    return rpc_call(HEALTH_SCORE_QUEUE, "health.history.list", {"page": page, "page_size": page_size}, user=user)
