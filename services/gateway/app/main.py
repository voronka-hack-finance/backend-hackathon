from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.gateway.app.config import settings
from services.gateway.app.constants import OPENAPI_TAGS
from services.gateway.app.openapi_descriptions import APP_DESCRIPTION
from services.gateway.app.routers import (
    accounts,
    analytics,
    auth,
    categories,
    chats,
    files,
    goals,
    groups,
    limits,
    notifications,
    system,
    transactions,
)
from services.gateway.app.rpc import transaction_query_params

# Backward compatibility for tests importing from main.
_transaction_query_params = transaction_query_params

app = FastAPI(
    title="Family Budget API Gateway",
    description=APP_DESCRIPTION,
    version="0.2.0",
    openapi_tags=OPENAPI_TAGS,
)

_cors_origins = settings.cors_origin_list()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(auth.router)
app.include_router(files.router)
app.include_router(files.imports_router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(goals.router)
app.include_router(limits.router)
app.include_router(categories.router)
app.include_router(notifications.router)
app.include_router(analytics.router)
app.include_router(groups.router)
app.include_router(chats.router)
