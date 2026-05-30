# Production backlog

Date: 2026-05-30 (updated)  
Status: Living document  
Scope: remaining gaps after cleanup pass (README visuals excluded by policy)

---

## Resolved in latest pass

| Item | Resolution |
|------|------------|
| Handler logic in `main.py` | All worker services use `MESSAGE_HANDLERS` + `create_worker_app` / `worker_lifespan` |
| `auth.scopes` in envelope | `build_envelope`, `require_user`, gateway `current_user` |
| Cross-file dedupe | Migration `050_transaction_dedupe.sql` + `on_conflict_do_nothing` on `uq_transactions_user_dedupe_key` |
| Group budget N+1 | `analytics.member_budget.batch` with fallback |
| Parser `supports` / `validate_header` | Implemented in `family_budget_excel_v1.py`, used on upload |
| Chat recommendations ephemeral | Generated items persisted to `agent_recommendations` |
| Chat message roles | `user` / `assistant` / `system` via payload |
| Analytics expense fallback `id` | Uses `regular_expenses.id` instead of `null` |
| CORS `*` hardcoded | `CORS_ORIGINS` env on gateway |
| Gateway dead JWT config | Removed from gateway settings (verify stays in access-service) |
| `@app.on_event` deprecation | Replaced with FastAPI `lifespan` on all worker services |
| `refresh_sessions` FK/index | Already in models + migrations |
| Account HTTP CRUD vs plan | Plan public API is `GET /api/v1/accounts` only; mutations via import/internal RPC |
| `requirements.txt` | Removed; `pyproject.toml` only |
| scheduler in gateway `depends_on` | Present in `docker-compose.yml` |
| Redis in compose | `redis` service + `depends_on` + `REDIS_*` env on runtime services and gateway |
| Redis idempotency | `MessageIdempotencyGuard` + worker skip on duplicate `message_id`; `/ready` checks Redis |
| `aio-pika` async bus | `libs/common/common/messaging.py` on aio-pika; sync `request`/`publish` via `_run_sync` |
| Full handler file split | `handlers.py` + `runtime.py` for chat, analytics, group, notification, scheduler |
| Negative JWT / bus publish / idempotency tests | `tests/test_security.py`, `test_messaging_publish.py`, `test_message_idempotency.py` |
| Gateway `/ready` Redis | `check_gateway_ready()` calls `check_redis()` |
| Firebase + device tokens | `libs/common/common/firebase_config.py`, `notification-service` env, `GET/POST /api/v1/notifications/devices` |

---

## Still open (intentionally excluded or backlog)

| Item | Notes |
|------|--------|
| README diagrams | SVG placeholders — user asked not to change README |
| Firebase in production | Credentials via `infra/.env` or `infra/secrets/`; disable with `FIREBASE_ENABLED=false` if needed |
| Docker smoke in CI | `RUN_DOCKER_SMOKE=1` + compose stack; optional pipeline step |

---

## Related docs

- [backend-plan.md](backend-plan.md)
- [audit-report.md](audit-report.md)
