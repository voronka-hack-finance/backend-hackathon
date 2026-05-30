# Project Audit Report

Date: 2026-05-30
Status: Complete
Scope: Full project audit against `docs/backend-plan.md`, `docs/backend-er-diagram.md`, `docs/backend-architecture-levels.md`

---

## Executive Summary

Project has solid architectural docs and gateway is nearly complete. Most backend services have all documented RabbitMQ handlers implemented. Main gaps: missing account CRUD routes in gateway, ghost `auth_service`/`transaction_service` directories, Firebase integration stubbed, several cross-cutting code quality issues.

**Stats:**
- 🔴 Critical: **5**
- 🟡 High: **8**
- 🟡 Medium: **14**
- ⚪ Low: **10**

---

## Table of Contents

1. [Architecture Violations](#1-architecture-violations)
2. [Gateway (api-gateway-service)](#2-gateway-api-gateway-service)
3. [Access Service](#3-access-service)
4. [File Service](#4-file-service)
5. [Finance Service](#5-finance-service)
6. [Scheduler Service](#6-scheduler-service)
7. [Notification Service](#7-notification-service)
8. [Analytics Service](#8-analytics-service)
9. [Group Service](#9-group-service)
10. [Chat Service](#10-chat-service)
11. [Migration Service](#11-migration-service)
12. [Create-Bucket Service](#12-create-bucket-service)
13. [Shared Library (libs/common)](#13-shared-library-libscommon)
14. [Infrastructure (Docker, Config)](#14-infrastructure-docker-config)
15. [Tests](#15-tests)
16. [Full Issue Index](#16-full-issue-index)

---

## 1. Architecture Violations

> [!CAUTION]
> These are leftover artifacts from earlier naming/architecture that should be cleaned up.

### 1.1 🔴 `auth_service` ghost directory

`services/auth_service/` contains only `__pycache__` directories with compiled `.pyc` files — all source `.py` files deleted. Docs explicitly state auth-service was renamed to access-service. This directory is dead weight and confuses developers.

**Action:** Delete entire `services/auth_service/` directory.

### 1.2 🟡 `transaction_service` ghost directory

`services/transaction_service/` exists but contains **zero source code** — only empty `__pycache__` directories. This is a scaffold leftover. Docs say finance-service owns transactions, which it does correctly.

**Action:** Delete entire `services/transaction_service/` directory.

### 1.3 🟡 Import flow architecture deviation

Docs say file-service should call `accounts.resolve_by_card` via RabbitMQ to finance-service as a separate step. In reality, file-service calls `transactions.bulk_create` and finance-service internally calls `_resolve_account()` during bulk_create processing.

**Impact:** End result is correct — accounts are resolved and transactions imported. But the integration pattern differs from docs. Architecture diagram in `backend-architecture-levels.md` shows separate `accounts.resolve_by_card` call that doesn't exist.

---

## 2. Gateway (api-gateway-service)

**Location:** [services/gateway/](file:///d:/Work/Projects/project-hackathon-28-30/services/gateway)

### ✅ What's Correct

- All documented auth/files/finance/notifications/analytics/groups/chat endpoints present
- JWT verification via `auth.verify_token` RPC to access-service ✅
- RabbitMQ request-reply with `correlation_id`, `reply_to`, timeout ✅
- Hides internal details from public responses ✅
- `GET /health` ✅, `GET /ready` (checks RabbitMQ) ✅
- All message type names match docs spec exactly ✅

### 🔴 Missing Account CRUD Endpoints

Only `GET /api/v1/accounts` exists. Missing:
- `POST /api/v1/accounts`
- `GET /api/v1/accounts/{account_id}`
- `PATCH /api/v1/accounts/{account_id}`
- `DELETE /api/v1/accounts/{account_id}`

> [!IMPORTANT]
> `AccountCreateRequest` and `AccountUpdateRequest` schemas exist in `schemas.py` (lines 181-197) but are **never imported or used** in `main.py`. Dead code.

### Other Gateway Issues

| # | Severity | Issue |
|---|----------|-------|
| 1 | 🟡 MEDIUM | `schemas.py` uses forward reference `PaginationResponse` before definition — works via `from __future__ import annotations` but fragile |
| 2 | 🟡 MEDIUM | Empty directories `app/api/` and `app/clients/` — dead structure |
| 3 | ⚪ LOW | Config has `jwt_secret`/`jwt_issuer` but gateway never uses them (verification goes through RPC) — dead config |
| 4 | ⚪ LOW | CORS `allow_origins=["*"]` — restrict for production |
| 5 | ⚪ LOW | Duplicate health route `/api/v1/health` not in docs spec |
| 6 | 🟡 MEDIUM | `scheduler-service` missing from gateway `depends_on` in docker-compose |

---

## 3. Access Service

**Location:** [services/access_service/](file:///d:/Work/Projects/project-hackathon-28-30/services/access_service)

### ✅ What's Correct

- All 9 documented message handlers present ✅
- Password hashing: PBKDF2-SHA256 with 390k iterations, 16-byte random salt ✅
- Timing-safe password comparison via `hmac.compare_digest` ✅
- `GET /health` ✅, `GET /ready` (checks DB + RabbitMQ) ✅
- No plain passwords stored ✅

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 MEDIUM | `db.query()` legacy API | Line 178 uses SQLAlchemy 1.x `Session.query()` while rest of code uses 2.0-style `select()`. Deprecated, inconsistent. |
| 2 | 🟡 MEDIUM | `HTTPException` in RabbitMQ worker | `decode_access_token` raises `HTTPException` (web framework exception) inside RabbitMQ worker thread. Fragile coupling. Should use domain exception. |
| 3 | 🟡 MEDIUM | Refresh token not rotated | `handle_refresh` returns new access token but same refresh token stays valid. If compromised, attacker keeps access until expiry. |
| 4 | 🟡 MEDIUM | No FK on `refresh_sessions.user_id` | No `ForeignKey("users.id")` in model. No DB referential integrity. |
| 5 | 🟡 MEDIUM | No index on `refresh_token_hash` | Every login/logout/refresh queries by hash. Performance issue at scale. |
| 6 | 🟡 MEDIUM | Deprecated `on_event("startup"/"shutdown")` | Should use FastAPI `lifespan` context manager. |
| 7 | ⚪ LOW | `handle_logout` doesn't verify token ownership | Any user can revoke any refresh token if they know its value. Low risk (tokens are random). |

---

## 4. File Service

**Location:** [services/file_service/](file:///d:/Work/Projects/project-hackathon-28-30/services/file_service)

### ✅ What's Correct

- All 11 documented message handlers registered ✅ (including events)
- Sheet filtering: `re.compile(r"^(Р|Д)_\d{2}\.\d{2}$")` matches `Р_MM.YY` and `Д_MM.YY` ✅
- Money as `Decimal(str(value))` with `MONEY_QUANT = Decimal("0.01")` ✅
- Human-readable error messages in Russian ✅
- File dedup: `UniqueConstraint("user_id", "sha256")` on uploaded_files ✅
- MinIO storage with local filesystem fallback ✅
- `dedupe_key` generated: SHA256 of `sheet_name|row_number|operation_at|operation_amount|description` ✅

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 HIGH | Parser doesn't implement `supports()` method | Docs specify `supports(file_metadata, workbook_metadata) -> bool`. Actual code has `inspect()` and `source_type` attribute instead. |
| 2 | 🟡 HIGH | No standalone `validate_header()` | Docs specify separate method. Header validation is inlined in `parse()` (lines 153-166). |
| 3 | 🟡 HIGH | Cross-file deduplication broken | `dedupe_key` computed and stored but **not used for deduplication**. DB constraint is on `(user_id, source_file_id, source_sheet, source_row_number)` — same transaction from different files would be inserted twice. |
| 4 | 🟡 MEDIUM | `_send_transactions` return value unused | Returns `inserted` count but caller `process_import_job()` ignores it. |

---

## 5. Finance Service

**Location:** [services/finance_service/](file:///d:/Work/Projects/project-hackathon-28-30/services/finance_service)

### ✅ What's Correct

All documented handlers present + extras:

**All doc-specified:**
- `transactions.list/get/create/update/delete/bulk_create/sum_by_scope` ✅
- `accounts.list/get/create/update/delete/resolve_by_card` ✅
- `goals.list/get/create/update/delete` ✅
- `limits.list/get/create/update/delete` ✅
- `categories.list/get/create/update/delete` ✅

**Schema match:**
- ACCOUNTS: **perfect match** with ER diagram ✅
- TRANSACTIONS: all documented columns present ✅ (plus 6 extra columns for import tracking)

**Extras not in docs** (bonus features):
- `finance.balance_before_period`
- `finance.income_expected_candidates`
- `finance.expense_pattern_candidates`
- `limits.due_warnings`

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🔴 CRITICAL | `_parse_date` crash on None | Line 302-303: `_parse_date(payload.get("period_start"))` called without None guard in `income_expected_candidates` handler. Will crash with `ValueError: Invalid isoformat string: 'None'`. |
| 2 | 🟡 MEDIUM | Inconsistent DB setup | Uses `create_engine` and `sessionmaker` directly instead of `common.db.build_engine/build_session_factory`. May miss shared pool settings. |
| 3 | 🟡 MEDIUM | Deprecated `on_event` pattern | Should use FastAPI `lifespan` context manager. |
| 4 | ⚪ LOW | Transaction model has 6 extra columns not in ER diagram | `source_sheet`, `source_row_number`, `card_mask`, `bonus_amount`, `investment_rounding_amount`, `rounded_operation_amount`. Not harmful but undocumented. |

---

## 6. Scheduler Service

**Location:** [services/scheduler_service/](file:///d:/Work/Projects/project-hackathon-28-30/services/scheduler_service)

### ✅ What's Correct

All documented handlers present:
- `reminders.plan_regular_expenses` ✅
- `reminders.plan_limit_warning` ✅
- `reminders.due.scan` ✅
- `notifications.schedule` ✅
- Uses `MessageBus.request()` for RPC to analytics + finance ✅
- Uses `bus.publish()` to notification-service ✅
- `GET /health` ✅, `GET /ready` ✅

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 MEDIUM | SQL string interpolation | Line 158-166: `handle_due_scan` uses `{filters}` in SQL. Not injectable (hardcoded string) but fragile pattern. |
| 2 | ⚪ LOW | Extra handler alias | `reminders.limit_warnings.plan` — undocumented alias. |
| 3 | 🟡 MEDIUM | Calls undocumented analytics message | `analytics.regular_expenses.due_for_reminders` — works but not in docs spec. |
| 4 | 🟡 MEDIUM | Deprecated `on_event` pattern | |

---

## 7. Notification Service

**Location:** [services/notification_service/](file:///d:/Work/Projects/project-hackathon-28-30/services/notification_service)

### ✅ What's Correct

All 4 documented handlers present:
- `notifications.permission.set` ✅
- `notifications.devices.save` ✅
- `notifications.test.send` ✅
- `notifications.send` ✅
- `GET /health` ✅, `GET /ready` ✅

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🔴 CRITICAL | Firebase push completely stubbed | No `firebase_admin` import or FCM calls. Push notifications just record status without actually sending. |
| 2 | 🟡 HIGH | `device_id` never populated in deliveries | Migration defines `device_id FK→notification_devices` but code never sets it. Column always NULL. |
| 3 | 🟡 MEDIUM | Deprecated `on_event` pattern | |

---

## 8. Analytics Service

**Location:** [services/analytics_service/](file:///d:/Work/Projects/project-hackathon-28-30/services/analytics_service)

### ✅ What's Correct

All documented handlers present + extras:
- `analytics.regular_expenses.detect` ✅
- `analytics.available_balance.get` ✅
- `analytics.expected_incomes.list` ✅
- `analytics.expected_expenses.list` ✅
- `analytics.member_budget.get` ✅
- Schema matches migration ✅
- `GET /health` ✅, `GET /ready` ✅

**Extra undocumented handler:** `analytics.regular_expenses.due_for_reminders` (used by scheduler).

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 MEDIUM | `_expected_expense_rows` fallback returns `null as id` | Line 351-370: inconsistent with expected_expenses table structure. |
| 2 | 🟡 MEDIUM | `handle_member_budget` is alias for `handle_available_balance` | Same return shape — may need distinct format for family budget display. |
| 3 | 🟡 MEDIUM | Deprecated `on_event` pattern | |

---

## 9. Group Service

**Location:** [services/group_service/](file:///d:/Work/Projects/project-hackathon-28-30/services/group_service)

### ✅ What's Correct

All documented handlers present:
- `groups.list/create/get/update/delete` ✅
- `groups.family_budget.get` ✅
- `group_members.list/create/update/delete` ✅
- `group_invitations.list/create/update/delete/accept/decline` ✅
- Uses `MessageBus.request()` to analytics-service for per-member budget ✅
- Schema matches migration ✅

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 HIGH | N+1 RPC problem in budget endpoint | `handle_groups_budget_get` (lines 215-231) iterates members, makes RPC call per member. Slow for large groups. |
| 2 | 🟡 MEDIUM | `_require_group_owner` checks `created_by_user_id` only | Doesn't check `family_members` role. If ownership transferred, check would be wrong. |
| 3 | ⚪ LOW | Extra alias `groups.budget.get` | Undocumented. |
| 4 | 🟡 MEDIUM | Deprecated `on_event` pattern | |

---

## 10. Chat Service

**Location:** [services/chat_service/](file:///d:/Work/Projects/project-hackathon-28-30/services/chat_service)

### ✅ What's Correct

All documented handlers present:
- `chat.recommendations.initial.get` ✅
- `chats.list/create/get/update/delete` ✅
- `chat_messages.list/create` ✅
- Uses `MessageBus.request()` to analytics + finance for recommendation context ✅
- Schema matches migration (CHATS, CHAT_MESSAGES, AGENT_RECOMMENDATIONS) ✅

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 MEDIUM | Recommendations not persisted | `handle_recommendations` generates hardcoded fallback recommendations when none in DB. Never written to `agent_recommendations` table — ephemeral only. |
| 2 | ⚪ LOW | `handle_messages_create` always sets `role='user'` | No way to create assistant/system messages via this handler. |
| 3 | ⚪ LOW | `handle_chats_delete` doesn't verify chat exists before delete | Silently succeeds on non-existent chat. |
| 4 | 🟡 MEDIUM | Deprecated `on_event` pattern | |

---

## 11. Migration Service

**Location:** [services/migration_service/](file:///d:/Work/Projects/project-hackathon-28-30/services/migration_service)

### ✅ What's Correct

- Waits for PostgreSQL (90s deadline) ✅
- Applies sorted `.sql` migrations ✅
- Creates `schema_migrations` tracking table ✅
- Idempotent (re-running safe) ✅
- All tables from ER diagram present in migrations ✅
- `agent_recommendations` table exists in `030_expanded_plan.sql` ✅

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 MEDIUM | No `/health` or `/ready` endpoints | One-shot service with no HTTP server. Docs say "all services" but this is a startup job. Architecture decision: exempt in docs or add lightweight HTTP. |
| 2 | ⚪ LOW | `schema_migrations` created in both SQL and Python | Redundant but harmless (`IF NOT EXISTS`). |

---

## 12. Create-Bucket Service

**Location:** [services/create_bucket_service/](file:///d:/Work/Projects/project-hackathon-28-30/services/create_bucket_service)

### ✅ What's Correct

- Waits for MinIO ✅
- Creates required buckets ✅
- Applies bucket policies (`private` and `readonly`) ✅
- Records state in `bucket_bootstrap_runs` table ✅
- Error path records `"failed"` status ✅

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 MEDIUM | No `/health` or `/ready` endpoints | Same as migration-service — one-shot job. |

---

## 13. Shared Library (libs/common)

**Location:** [libs/common/](file:///d:/Work/Projects/project-hackathon-28-30/libs/common)

### ✅ What's Correct

Message envelope (`build_envelope()`) has most fields:
- `message_id` (uuid4) ✅
- `correlation_id` ✅
- `reply_to` (conditional) ✅
- `type` ✅
- `source` ✅
- `user.id` and `user.email` via `UserContext.as_metadata()` ✅
- `created_at` ✅

Request-reply via `MessageBus.request()` with correlation_id, reply_to, timeout ✅

Retry/dead-letter queues in `MessageWorker`:
- `.retry` queue with TTL + dead-letter back to main queue ✅
- `.dead` queue for exhausted retries ✅
- Configurable `max_retries` (default 3) and `retry_delay_ms` (default 1000) ✅

### Issues

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 HIGH | `auth.scopes` missing from envelope | Docs specify optional `auth.scopes` field. No support in `UserContext` or envelope. |
| 2 | 🟡 MEDIUM | Uses `pika` (synchronous) not `aio-pika` (async) | Each `request()` creates blocking connection. Not ideal for async FastAPI services. Works but suboptimal. |
| 3 | ⚪ LOW | `Page.items` typed as bare `list` | Loses generic type info for consumers. |

---

## 14. Infrastructure (Docker, Config)

### docker-compose.yml

All documented services present ✅. Healthchecks on infrastructure ✅. Correct dependency ordering (migration before app services) ✅.

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 MEDIUM | `scheduler-service` missing from gateway `depends_on` | Gateway depends on access, file, finance, analytics, notification, group, chat — but NOT scheduler. |
| 2 | 🟡 MEDIUM | No service depends on `redis:service_healthy` | Redis healthcheck exists but nothing waits on it. |
| 3 | ⚠️ | `create-bucket-service` depends on `postgres` | Does it need postgres? (Yes — records state in `bucket_bootstrap_runs`.) |
| 4 | ⚠️ | `JWT_SECRET: dev-secret-change-me` hardcoded in YAML anchor | Acceptable for dev but should be in `.env`. |

### Dockerfile.service

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | ⚠️ | Default CMD is gateway-specific | Every compose service overrides with `command:`. Minor. |
| 2 | ⚠️ | No `.dockerignore` | Build context includes `.venv`, `__pycache__`, `tests/`. Bloats image. |

### Dependencies (pyproject.toml / requirements.txt)

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | 🟡 MEDIUM | `pytest` in runtime requirements.txt | Test deps in production image. Should be dev-only. |
| 2 | ⚠️ | `pika` (sync) instead of `aio-pika` (async) | Works but blocking. See libs/common section. |

### infra/.env.example

| Missing Variable | Needed By |
|-----------------|-----------|
| `RABBITMQ_URL` | All services |
| `RABBITMQ_HOST` / `RABBITMQ_PORT` | All services |
| `REDIS_HOST` / `REDIS_PORT` | Optional services |
| `MINIO_SECURE` | file-service |

### README.md

| # | Severity | Issue |
|---|----------|-------|
| 1 | 🟡 MEDIUM | Outdated — mentions `auth-service` and `transaction-service` but actual services are `access-service` and `finance-service` |
| 2 | ⚠️ | Does not list all 11 services or link to `docs/` |

---

## 15. Tests

**Location:** [tests/](file:///d:/Work/Projects/project-hackathon-28-30/tests) — 10 test files

### Test Assessment

| File | Status | Notes |
|------|--------|-------|
| `test_analytics_boundaries.py` | ⚠️ | Reads source file strings — brittle if refactored |
| `test_create_bucket_policy.py` | ✅ | Clean, uses FakeMinio mock |
| `test_family_budget_parser.py` | ✅ | Comprehensive — real workbook + edge cases |
| `test_finance_reference_validation.py` | ✅ | Clean, uses FakeSession |
| `test_gateway_openapi.py` | ✅ | Most thorough — validates all OpenAPI paths |
| `test_integration_rabbitmq_import.py` | ✅ | Full smoke test, properly skipped unless `RUN_DOCKER_SMOKE=1` |
| `test_messaging_retry.py` | ✅ | Tests retry queue TTL, retry counting, dead letter routing |
| `test_scheduler_boundaries.py` | ⚠️ | Same brittle source-reading pattern |
| `test_security.py` | ⚠️ | Only 1 test, no negative cases (expired/invalid JWT) |
| `test_transaction_filters.py` | ✅ | Tests SQL filter compilation |

### Test Coverage Gaps

| # | Missing Test Area |
|---|------------------|
| 1 | No tests for `common.db` module |
| 2 | No tests for `common.http` module (`require_internal_user_id`) |
| 3 | No tests for `common.pagination` module |
| 4 | No negative JWT security tests (expired, wrong secret, wrong issuer) |
| 5 | No tests for `MessageBus.publish()` fire-and-forget path |
| 6 | No tests for `MessageWorker._handle_message()` dispatch logic |
| 7 | No `conftest.py` — no shared fixtures |
| 8 | `tests/fixtures/` directory is empty — parser test uses repo-root xlsx instead |

---

## 16. Full Issue Index

### 🔴 Critical (5)

| # | Service | Issue |
|---|---------|-------|
| C1 | auth_service | Ghost directory — only `__pycache__`, no source files. Delete. |
| C2 | notification | Firebase push completely stubbed — no actual FCM integration |
| C3 | finance | `_parse_date` crash on None in `income_expected_candidates` handler |
| C4 | gateway | Missing Account CRUD endpoints (POST/GET/PATCH/DELETE for `/api/v1/accounts/`) |
| C5 | file-service | Cross-file deduplication broken — `dedupe_key` exists but not enforced at DB level |

### 🟡 High (8)

| # | Service | Issue |
|---|---------|-------|
| H1 | transaction_service | Ghost directory — empty scaffold, delete |
| H2 | libs/common | `auth.scopes` missing from message envelope |
| H3 | file-service | Parser missing `supports()` method per docs interface |
| H4 | file-service | Parser missing standalone `validate_header()` method per docs interface |
| H5 | notification | `device_id` never populated in `notification_deliveries` |
| H6 | group-service | N+1 RPC problem in family budget endpoint — 1 RPC per member |
| H7 | access-service | Refresh token not rotated on refresh |
| H8 | README.md | Outdated — mentions deleted service names |

### 🟡 Medium (14)

| # | Service | Issue |
|---|---------|-------|
| M1 | access-service | `db.query()` legacy API mixed with 2.0 style |
| M2 | access-service | `HTTPException` raised in RabbitMQ worker context |
| M3 | access-service | No FK on `refresh_sessions.user_id` |
| M4 | access-service | No index on `refresh_token_hash` |
| M5 | ALL services | Deprecated `@app.on_event("startup"/"shutdown")` — use `lifespan` |
| M6 | libs/common | Uses `pika` (sync) instead of `aio-pika` (async) |
| M7 | docker-compose | `scheduler-service` missing from gateway `depends_on` |
| M8 | docker-compose | No service depends on `redis:service_healthy` |
| M9 | scheduler | SQL string interpolation pattern (fragile) |
| M10 | scheduler | Calls undocumented `analytics.regular_expenses.due_for_reminders` |
| M11 | analytics | `_expected_expense_rows` returns `null as id` |
| M12 | analytics | `handle_member_budget` is just alias for `handle_available_balance` |
| M13 | chat-service | Recommendations not persisted to DB — ephemeral only |
| M14 | requirements.txt | `pytest` in runtime dependencies |

### ⚪ Low (10)

| # | Service | Issue |
|---|---------|-------|
| L1 | gateway | Dead config values `jwt_secret`/`jwt_issuer` never used |
| L2 | gateway | Empty `app/api/` and `app/clients/` directories |
| L3 | gateway | Duplicate `/api/v1/health` route not in docs |
| L4 | gateway | CORS `allow_origins=["*"]` |
| L5 | gateway | `AccountCreateRequest`/`AccountUpdateRequest` schemas defined but unused |
| L6 | access | `handle_logout` doesn't verify token belongs to requesting user |
| L7 | finance | Transaction model has 6 extra columns not in ER diagram |
| L8 | chat | `handle_messages_create` always sets `role='user'` |
| L9 | libs/common | `Page.items` typed as bare `list` — loses type info |
| L10 | .env.example | Missing RABBITMQ_URL, REDIS_HOST/PORT variables |

---

## Recommended Priority

1. **Delete ghost directories** (`auth_service`, `transaction_service`) — quick cleanup
2. **Fix `_parse_date` crash** in finance-service — runtime error
3. **Add missing account CRUD routes** to gateway — feature gap
4. **Fix cross-file deduplication** — add unique constraint on `(user_id, dedupe_key)` or similar
5. **Integrate Firebase** in notification-service — core feature stubbed
6. **Populate `device_id`** in notification deliveries
7. **Fix N+1 RPC** in group-service budget — batch member budget requests
8. **Add `auth.scopes`** to message envelope
9. **Implement parser interface** (`supports()`, `validate_header()`) per docs
10. **Update README** to match current architecture

---

## Related Documents

- [backend-plan.md](file:///d:/Work/Projects/project-hackathon-28-30/docs/backend-plan.md)
- [backend-er-diagram.md](file:///d:/Work/Projects/project-hackathon-28-30/docs/backend-er-diagram.md)
- [backend-architecture-levels.md](file:///d:/Work/Projects/project-hackathon-28-30/docs/backend-architecture-levels.md)
