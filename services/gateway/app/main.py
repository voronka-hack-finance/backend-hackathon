from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from services.gateway.app.config import settings
from services.gateway.app.constants import OPENAPI_TAGS
from services.gateway.app.openapi_descriptions import APP_DESCRIPTION
from services.gateway.app.routers import (
    accounts,
    analytics,
    auth,
    categories,
    chats,
    debts,
    files,
    financial_health,
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
    docs_url=None,
    redoc_url=None,
)

_cors_origins = settings.cors_origin_list()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _swagger_openapi_url(request: Request) -> str:
    """Same-origin spec URL avoids CORS and wrong-port fetches (e.g. :8080 vs :8081)."""
    base = str(request.base_url).rstrip("/")
    if base.startswith(("http://", "https://")):
        return "/openapi.json"
    return f"{settings.public_base_url.rstrip('/')}/openapi.json"


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    schema["servers"] = [{"url": "/", "description": "Текущий хост gateway (тот же, что у /docs)"}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.get("/docs", include_in_schema=False)
async def swagger_ui(request: Request):
    return get_swagger_ui_html(
        openapi_url=_swagger_openapi_url(request),
        title=f"{app.title} — Swagger UI",
        swagger_ui_parameters={"tryItOutEnabled": True},
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_ui(request: Request):
    return get_redoc_html(
        openapi_url=_swagger_openapi_url(request),
        title=f"{app.title} — ReDoc",
    )


app.include_router(system.router)
app.include_router(auth.router)
app.include_router(files.router)
app.include_router(files.imports_router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(goals.router)
app.include_router(debts.router)
app.include_router(limits.router)
app.include_router(categories.router)
app.include_router(notifications.router)
app.include_router(analytics.router)
app.include_router(financial_health.router)
app.include_router(groups.router)
app.include_router(chats.router)
