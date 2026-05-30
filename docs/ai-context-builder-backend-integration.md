# AI Context Builder — Backend Integration Audit

> **Repository:** `backend-hackathon` (Family Budget Backend)  
> **Audit date:** 2026-05-30  
> **Scope:** HTTP API surface for AI Context Builder Service (`ai-workflow`)  
> **Method:** Full codebase scan — routes, schemas, models, migrations, tests. No invented endpoints.

---

## 1. Executive Summary

Backend — **Python 3.12 / FastAPI** microservice stack. Единственная публичная HTTP-точка входа — **`gateway`** (`services/gateway/app/main.py`). Все business-операции идут через RabbitMQ RPC в worker-сервисы; OpenAPI генерируется runtime на `/docs` и `/openapi.json` (статического swagger-файла нет). GraphQL отсутствует.

**Что уже можно использовать Context Builder'ом (через user JWT):**

| Data need | Backend endpoint | Status |
|-----------|------------------|--------|
| Transactions (period) | `GET /api/v1/transactions` | ✅ Ready |
| Previous period transactions | Same endpoint, other dates | ✅ Ready |
| Goals | `GET /api/v1/goals` | ✅ Partial (separate from user_context) |
| Accounts / balance | `GET /api/v1/accounts` | ✅ Partial (computed `current_balance`) |
| Expected income | `GET /api/v1/analytics/expected-incomes` | ✅ Partial (proxy for stable income) |
| Available balance snapshot | `GET /api/v1/analytics/available-balance` | ✅ Optional enrichment |

**Критические пробелы (P0):**

1. **Нет service-to-service auth** — только Bearer JWT конкретного пользователя; нет API key / service token / impersonation endpoint.
2. **Нет `GET /users/{userId}/...` path-style API** — user определяется исключительно из JWT (`current_user`), не из URL/body.
3. **Нет единого `user_context` / financial profile endpoint** — данные размазаны по accounts, goals, analytics.
4. **Нет category profiles** (`categoryGroup`, `canOptimize`, `protectedByDefault`) — только user-defined `account_categories` и bank `category_name` на транзакциях.

**P1:** merchant/description filter на transactions; category profiles mapping; pagination loop для больших периодов.

**P2:** debts entity; cached financial analysis result endpoint; `salary_day`, `current_savings` fields.

Sample JSON: [`docs/ai-integration-samples/`](ai-integration-samples/).

---

## 2. Architecture Diagram

```mermaid
flowchart LR
    subgraph ai_workflow["ai-workflow"]
        WF[Workflow Orchestrator]
        IP[Intent Parser]
        CB[Context Builder Service]
        AS[Analytics Service]
    end

    subgraph backend["backend-hackathon (Docker Compose)"]
        GW[gateway :8081]
        RMQ[(RabbitMQ)]
        ACC[access-service]
        FIN[finance-service]
        ANA[analytics-service]
        PG[(PostgreSQL)]
    end

    WF --> IP
    IP --> CB
    CB -->|"HTTP Bearer JWT\n(GET /api/v1/*)"| GW
    CB -->|normalize DTO| AS
    GW --> RMQ
    RMQ --> ACC
    RMQ --> FIN
    RMQ --> ANA
    FIN --> PG
    ANA --> PG
    ACC --> PG
```

**Internal Docker network (compose service names):**

| Service | Hostname | Port (internal) | Host port |
|---------|----------|-----------------|-----------|
| gateway | `gateway` | 8000 | **8081** |
| access-service | `access-service` | 8000 | — |
| finance-service | `finance-service` | 8000 | — |
| analytics-service | `analytics-service` | 8000 | — |

Context Builder из `ai-workflow` контейнера должен обращаться к `http://gateway:8000` (internal) или `http://localhost:8081` (dev host).

---

## 3. Endpoint Catalog

### 3.1 Summary Table (Context Builder relevant)

| # | Method | Path | Auth | User ID | Batch | Context Builder use |
|---|--------|------|------|---------|-------|---------------------|
| 1 | GET | `/api/v1/transactions` | Bearer JWT | from JWT | per-user | **transactions**, **previous_period** |
| 2 | GET | `/api/v1/accounts` | Bearer JWT | from JWT | per-user | **user_context.current_balance** (aggregate) |
| 3 | GET | `/api/v1/goals` | Bearer JWT | from JWT | per-user | **goals**, **user_context.goal_*** |
| 4 | GET | `/api/v1/categories` | Bearer JWT | from JWT | per-user | ⚠️ NOT category profiles (different schema) |
| 5 | GET | `/api/v1/analytics/available-balance` | Bearer JWT | from JWT | per-user | optional balance enrichment |
| 6 | GET | `/api/v1/analytics/expected-incomes` | Bearer JWT | from JWT | per-user | **stable_monthly_income** proxy |
| 7 | GET | `/api/v1/analytics/expected-expenses` | Bearer JWT | from JWT | per-user | optional enrichment |
| 8 | GET | `/api/v1/chats/recommendations` | Bearer JWT | from JWT | per-user | optional prior AI hints (`agent_recommendations`) |
| — | — | `/api/v1/users/{id}/financial-context` | — | — | — | **MISSING ENDPOINT** |
| — | — | `/api/v1/category-profiles` | — | — | — | **MISSING ENDPOINT** |
| — | — | `/api/v1/debts` | — | — | — | **MISSING ENDPOINT** (no DB table) |

### 3.2 GET `/api/v1/transactions`

```text
- HTTP method + path: GET /api/v1/transactions
- Auth: Bearer JWT (Authorization: Bearer <access_token>)
- Path params: none
- Query params:
    date_from          date (YYYY-MM-DD)  inclusive start, filters operation_at >= start-of-day UTC
    date_to            date (YYYY-MM-DD)  inclusive end,   filters operation_at <= end-of-day UTC
    categories         string[]           bank category_name IN (...)
    mcc                string[]           mcc IN (...)
    type               income | expense   transaction direction
    status             string             exact match on bank status
    has_cashback       boolean            true = non-zero cashback
    card_last4         string[]           card last 4 digits
    account_id         UUID               linked account
    category_id        UUID               user-defined account_categories.id
    page               int (default 1)
    page_size          int (default 50, max 500)
- Request body: none
- Response: 200 TransactionsPageResponse { items[], pagination }
- Status codes: 200, 401, 422 (invalid type), 502, 504
- Pagination: offset via page/page_size; must iterate pages for full period
- User identifier: implicit from JWT (PostgreSQL UUID string)
- Rate limits: none configured
- Timeout: gateway RPC default 30s (RPC_TIMEOUT_SECONDS)
- Batch: single-user only (JWT-scoped)
- Sort: operation_at DESC, source_row_number DESC
```

**Example response:** [`ai-integration-samples/transactions.sample.json`](ai-integration-samples/transactions.sample.json)

**Internal only (RabbitMQ, not HTTP):** `transactions.get`, `transactions.create`, `transactions.update`, `transactions.delete`, `transactions.bulk_create`, `transactions.sum_by_scope`

### 3.3 GET `/api/v1/accounts`

```text
- Method + path: GET /api/v1/accounts
- Auth: Bearer JWT
- Query: page (default 1), page_size (default 50, max 500)
- Response: 200 AccountsPageResponse
- Status: 200, 401, 502, 504
- Computed field: current_balance = initial_balance + SUM(transactions.operation_amount) per account
```

**Use for Context Builder:** aggregate `SUM(current_balance)` → `user_context.current_balance`.

**Internal only:** full accounts CRUD via RabbitMQ (`accounts.create/update/delete/get`).

### 3.4 GET `/api/v1/goals`

```text
- Method + path: GET /api/v1/goals
- Auth: Bearer JWT
- Query: page, page_size
- Response: 200 GoalsPageResponse
- Status: 200, 401, 404 (single get), 502, 504
- Soft delete: status = "deleted"
- Default status: "active"
```

Also: `GET/POST/PATCH/DELETE /api/v1/goals/{goal_id}`.

**Example:** [`ai-integration-samples/goals.sample.json`](ai-integration-samples/goals.sample.json)

### 3.5 GET `/api/v1/categories`

```text
- Method + path: GET /api/v1/categories
- Auth: Bearer JWT
- Response: user-defined AccountCategory records (NOT bank category profiles)
- Fields: id, account_id, name, description, icon_key, is_archived
- Missing vs Context Builder reference: categoryGroup, canOptimize, protectedByDefault, isRequiredExpense
```

**MISSING ENDPOINT for AI category profiles** — data partially exists in:
- `transactions.category_name` (bank import text, distinct values queryable only via transactions list)
- `account_categories` table (user labels, not bank taxonomy)

### 3.6 GET `/api/v1/analytics/available-balance`

```text
- Method + path: GET /api/v1/analytics/available-balance
- Auth: Bearer JWT
- Query: period_start (date, inclusive), period_end (date, inclusive)
- Defaults: both default to today if omitted
- Response: actual_balance, expected_income_total, expected_expense_total, available_amount, currency
- Side effect: INSERT into available_funds_snapshots (cache table, no GET endpoint for history)
```

Formula: `available_amount = actual_balance + expected_income_total - expected_expense_total`

`actual_balance` at period start = sum(account.initial_balance) + sum(transactions before period_start).

### 3.7 GET `/api/v1/analytics/expected-incomes`

```text
- Method + path: GET /api/v1/analytics/expected-incomes
- Auth: Bearer JWT
- Query: page, page_size
- Response: stored expected_incomes OR derived from income transaction patterns (finance.income_expected_candidates)
- Fields: source_pattern, expected_amount, currency, expected_at, confidence
```

Proxy for `stable_monthly_income`: take largest recurring `expected_amount` or average of salary-pattern rows.

### 3.8 GET `/api/v1/analytics/expected-expenses`

```text
- Method + path: GET /api/v1/analytics/expected-expenses
- Auth: Bearer JWT
- Response: stored expected_expenses OR active regular_expenses
```

### 3.9 GET `/api/v1/chats/recommendations` (optional enrichment)

```text
- Method + path: GET /api/v1/chats/recommendations
- Auth: Bearer JWT
- Response: persisted agent_recommendations OR derived static suggestions
- Not a structured financial analysis cache — free-text title/content
```

**MISSING:** dedicated `existing_financial_analysis_result` endpoint. Closest: `agent_recommendations` table + `available_funds_snapshots` (write-only cache).

### 3.10 MISSING: User Financial Context

**MISSING ENDPOINT** — no single API. Data exists across:

| Field (Context Builder) | Backend source | Status |
|-------------------------|----------------|--------|
| current_balance | `accounts.current_balance` (computed) | derivable |
| stable_monthly_income | `expected_incomes` / income tx patterns | derivable |
| current_savings | — | **GAP** |
| has_debt | — | **GAP** (no debts table) |
| monthly_debt_payment | — | **GAP** |
| debt_amount | — | **GAP** |
| financial_goal | `savings_goals.title` | via goals API |
| goal_amount | `savings_goals.target_amount` | via goals API |
| goal_deadline_months | `savings_goals.target_date` | compute client-side |
| salary_day | — | **GAP** |

### 3.11 MISSING: Debts

**MISSING ENDPOINT** — entity does not exist in DB/models/migrations.

### 3.12 MISSING: Category Profiles

**MISSING ENDPOINT** — no `category_group`, `can_optimize`, `protected_by_default` in schema.

### 3.13 Internal RabbitMQ handlers (not exposed via gateway HTTP)

Relevant for future internal integration (not for Context Builder HTTP client today):

| Queue | message_type | Purpose |
|-------|--------------|---------|
| finance-service | `finance.balance_before_period` | Balance before date |
| finance-service | `finance.income_expected_candidates` | Derived income patterns |
| finance-service | `finance.expense_pattern_candidates` | Merchant patterns |
| finance-service | `transactions.sum_by_scope` | Income/expense totals with filters |
| access-service | `users.get` | User by UUID (requires envelope user) |

---

## 4. DTO Catalog

### 4.1 Transactions

**ORM:** `services/finance_service/app/models.py` → `Transaction`  
**Table:** `transactions` (migration `020_transaction_service.sql`)  
**API DTO:** `TransactionResponse` in `services/gateway/app/schemas.py`  
**Pagination wrapper:** `TransactionsPageResponse`

#### Full field list

| Field | Type | Nullable | Enum / notes |
|-------|------|----------|--------------|
| id | UUID | no | PK |
| user_id | UUID | yes in DTO | owner |
| account_id | UUID | yes | FK accounts |
| category_id | UUID | yes | FK account_categories (user label) |
| import_id | UUID | no | |
| source_file_id | UUID | no | |
| source_sheet | string | no | e.g. `Р_05.26` |
| source_row_number | int | no | |
| type | string | no | **`income` \| `expense`** |
| operation_at | datetime ISO | no | timestamptz, UTC in filters |
| payment_at | datetime ISO | yes | |
| card_mask | string | yes | e.g. `*8336` |
| card_last4 | string(4) | yes | filterable |
| status | string | yes | free text from bank |
| operation_amount | **string** (decimal) | no | signed decimal string |
| operation_currency | string | yes | |
| payment_amount | string | yes | |
| payment_currency | string | yes | |
| cashback_amount | string | yes | |
| category_name | string | yes | **bank category** (import) |
| mcc | string | yes | |
| description | string | yes | **merchant/counterparty text** |
| bonus_amount | string | yes | includes cashback |
| investment_rounding_amount | string | yes | rounding to savings |
| rounded_operation_amount | string | yes | |
| dedupe_key | string | no | |
| raw_payload | object | no | all 15 Excel columns |
| created_at | datetime ISO | no | |
| updated_at | datetime ISO | no | |

#### Direction encoding

| Aspect | Backend behavior |
|--------|------------------|
| Direction field | `type`: `"income"` or `"expense"` |
| Sign of `operation_amount` | **Signed:** expenses negative (`-1294.00`), income positive (`85000.00`) — preserved from Excel |
| Sheet prefix | `Р_*` → expense, `Д_*` → income (parser) |
| Filter | query `type=income` or `type=expense` |
| Context Builder `IN/OUT` | map: income→IN, expense→OUT; or use `type` directly |

#### Date format

- API: ISO 8601 datetime with timezone, e.g. `2026-05-10T18:25:00+00:00`
- Period filters: **date only** `YYYY-MM-DD` on query string
- Filter field: `operation_at` (not `payment_at`)

#### Pagination response shape

```json
{
  "items": [ /* TransactionResponse[] */ ],
  "pagination": { "page": 1, "page_size": 50, "total": 127 }
}
```

Empty list: `"items": []`, `"total": 0` — never null.

#### Mapping: Backend → TransactionNormalized

| Backend field | Type | Nullable | → Normalized | Notes |
|---------------|------|----------|--------------|-------|
| id | UUID string | no | transaction_id | |
| operation_at | datetime | no | operation_datetime | |
| payment_at | datetime | yes | payment_date | date part |
| card_last4 | string | yes | card_id | **GAP:** no separate card entity; use last4 or account_id |
| account_id | UUID | yes | account_id | |
| status | string | yes | status | |
| operation_amount | string | no | operation_amount | parse to number; keep sign |
| operation_currency | string | yes | operation_currency | |
| payment_amount | string | yes | payment_amount | |
| payment_currency | string | yes | payment_currency | |
| cashback_amount | string | yes | cashback | |
| category_name | string | yes | category | bank category |
| mcc | string | yes | mcc | |
| description | string | yes | description, merchant | same field for merchant |
| — | — | — | counterparty | **GAP:** no separate field; use description |
| bonus_amount | string | yes | bonuses | |
| investment_rounding_amount | string | yes | rounding_to_savings | |
| rounded_operation_amount | string | yes | rounded_operation_amount | |
| type | income/expense | no | direction | map to `income`/`expense` |
| — | — | — | ambiguous | **GAP:** not in backend |

Reference DTO mapping:

| Reference field | Backend equivalent |
|-----------------|-------------------|
| id | id |
| sum | operation_amount (number, signed) |
| currency | operation_currency |
| type OUT/IN | type expense/income |
| merchantName | description |
| bankCategory | category_name |
| mccCode | mcc |
| date | operation_at |
| ambiguous | **GAP** |

### 4.2 User Financial Context

**No dedicated DTO.** Composite reference:

```json
{
  "currentSavings": 45000,
  "stableMonthlyIncome": 85000,
  "hasDebt": false,
  "monthlyDebtPayment": null,
  "debtAmount": null,
  "financialGoal": null,
  "goalAmount": null,
  "goalDeadlineMonths": null,
  "salaryDay": 5,
  "currentBalance": 52000
}
```

#### Mapping: Sources → UserFinancialContextNormalized

| Normalized field | Backend source | Status |
|------------------|----------------|--------|
| current_savings | — | **GAP** |
| stable_monthly_income | analytics expected-incomes / income tx | derivable |
| has_debt | — | **GAP** |
| monthly_debt_payment | — | **GAP** |
| debt_amount | — | **GAP** |
| financial_goal | savings_goals.title | via GET /goals |
| goal_amount | savings_goals.target_amount | via GET /goals |
| goal_deadline_months | from savings_goals.target_date | compute |
| salary_day | — | **GAP** |
| current_balance | SUM(accounts.current_balance) | via GET /accounts |

**Storage locations:**
- `users` — email, display_name only (`access_service`)
- `accounts` — initial_balance, computed current_balance
- `savings_goals` — goals
- `expected_incomes`, `regular_expenses` — analytics patterns
- No `financial_context` table

### 4.3 Category Profiles

**Reference DTO (Context Builder):**

```json
{
  "category": "Фастфуд",
  "categoryGroup": "food_outside",
  "canOptimize": true,
  "protectedByDefault": false,
  "isRequiredExpense": false
}
```

**Backend actual — `CategoryResponse` (user categories, NOT profiles):**

| Field | Type | Nullable |
|-------|------|----------|
| id | UUID | no |
| account_id | UUID | yes |
| created_by_user_id | UUID | no |
| name | string | no |
| description | string | yes |
| icon_key | string | yes |
| is_archived | bool | no |

**Mapping gap:**

| Reference field | Backend | Status |
|-----------------|---------|--------|
| category | category_name (tx) or categories.name | partial |
| categoryGroup | — | **GAP** |
| canOptimize | — | **GAP** |
| protectedByDefault | — | **GAP** |
| isRequiredExpense | — | **GAP** |

Allowed `category_group` values (Context Builder) — **not in backend**:  
`essential_fixed`, `essential_variable`, `health`, `transport`, `food_outside`, `shopping_lifestyle`, `entertainment`, `education_development`, `travel`, `financial_special`, `unclear_special`, `penalty`, `unknown`

### 4.4 Goals — `GoalResponse`

| Field | Type | Nullable | Default |
|-------|------|----------|---------|
| id | UUID | no | |
| account_id | UUID | yes | |
| owner_user_id | UUID | no | |
| title | string | no | → financial_goal |
| description | string | yes | |
| target_amount | string | no | → goal_amount |
| current_amount | string | no | default `"0"` |
| currency | string | no | `RUB` |
| target_date | date | yes | → goal_deadline_months |
| status | string | no | `active`, `deleted` |
| created_at | datetime | no | |
| updated_at | datetime | no | |

**Relation to user_context:** Context Builder should pick primary active goal or merge list; backend allows multiple goals.

### 4.5 Debts

**Not implemented.** No endpoint, table, or DTO.

### 4.6 Analytics / Cached Analysis (optional)

| Artifact | Table | HTTP read |
|----------|-------|-----------|
| Available funds snapshot | `available_funds_snapshots` | only via side-effect of GET available-balance |
| Regular expenses | `regular_expenses` | via expected-expenses (derived) |
| Expected incomes/expenses | `expected_incomes`, `expected_expenses` | GET analytics endpoints |
| Agent recommendations | `agent_recommendations` | GET /chats/recommendations (unstructured text) |

---

## 5. Auth & Security

### 5.1 User identifier in AI workflow

| Property | Value |
|----------|-------|
| Format | **PostgreSQL UUID** as RFC 4122 string |
| Example | `550e8400-e29b-41d4-a716-446655440000` |
| JWT claims | `sub` and `user_id` (both set to same UUID) |
| NOT used | telegram_id, external_id, integer id |

Workflow payload `user_id: "user_123"` must be the **real backend UUID** issued at registration.

### 5.2 Current auth model

| Mechanism | Status |
|-----------|--------|
| Bearer JWT (HS256) | ✅ Only auth method |
| API key / service token | ❌ **MISSING** |
| mTLS | ❌ Not configured |
| Internal network trust | Docker network only (no auth bypass) |
| User impersonation header | ❌ **MISSING** (e.g. `X-User-Id` + service auth) |

**Flow:**
1. Context Builder sends `Authorization: Bearer <jwt>`
2. Gateway `current_user()` → RabbitMQ `auth.verify_token` → access-service
3. `UserContext.id` attached to all downstream RPC envelopes
4. Finance/analytics handlers call `require_user(envelope)` — **all queries scoped to JWT user**

### 5.3 Access control

- No RBAC at gateway; ownership enforced per entity (`owner_user_id`, `user_id` columns)
- Cannot fetch another user's data with a different user's JWT
- **Problem for service-to-service:** Context Builder has `user_id` from workflow but **no way to act on behalf of user without that user's JWT**

### 5.4 Tracing headers

| Header | Supported |
|--------|-----------|
| X-Request-Id | ❌ not implemented |
| X-Correlation-Id | ❌ not implemented |
| chat_id / request_id | ❌ not consumed by gateway |

Recommended for Context Builder (forward for future observability):

```http
Authorization: Bearer <token>
X-Request-Id: req_001
X-Workflow-Run-Id: run_001
X-Chat-Id: chat_001
Accept: application/json
```

### 5.5 Token lifetime

- Access token: default **1440 minutes** (24h) — `ACCESS_TOKEN_MINUTES`
- Algorithm: HS256, issuer: `JWT_ISSUER` (default `family-budget-backend`)
- Refresh: `POST /api/v1/auth/refresh` with opaque refresh token

---

## 6. Query / Filter Conventions

### 6.1 Period filtering (transactions)

| Parameter | Backend name | Notes |
|-----------|--------------|-------|
| start | `date_from` | **Not** `start_date` |
| end | `date_to` | **Not** `end_date` |

Context Builder resolves `{ start_date, end_date }` → map to `date_from`, `date_to`.

| Rule | Behavior |
|------|----------|
| Boundaries | **Inclusive** both ends |
| Timezone | Dates interpreted as **UTC** start/end of day |
| Comparison period | **Same endpoint**, different date params |
| Max page_size | 500 rows per request |
| Max period | No server limit; paginate until `page * page_size >= total` |
| Default sort | `operation_at DESC` |

**Pagination algorithm for Context Builder:**

```
page = 1
all_items = []
loop:
  resp = GET /transactions?date_from=...&date_to=...&page=page&page_size=500
  all_items += resp.items
  if page * page_size >= resp.pagination.total: break
  page += 1
```

### 6.2 Intent focus filters

| Intent filter | Backend support | Where applied |
|---------------|-----------------|---------------|
| focus.category | ✅ `categories` query (category_name) | backend |
| focus.mcc | ✅ `mcc` query | backend |
| focus.card_id | ⚠️ partial — use `account_id` or `card_last4` | backend |
| focus.direction | ✅ `type=income\|expense` | backend |
| focus.merchant | ❌ **no filter** | **GAP** — filter client-side on `description` or add backend param |

---

## 7. Error Handling & Edge Cases

| Scenario | HTTP | Response body | Context Builder action |
|----------|------|---------------|------------------------|
| Missing token | 401 | `{"detail":"Missing Bearer token"}` | hard fail / re-auth |
| Invalid/expired JWT | 401 | `{"detail":"Invalid token"}` | refresh or hard fail |
| Invalid query (bad type) | 422 | `{"detail":"type must be income or expense"}` | fix params |
| Resource not found (goal get) | 404 | `{"detail":"Resource not found"}` | optional missing |
| User not found | N/A at gateway | only via internal `users.get` | no public user lookup |
| Empty transactions | 200 | `{"items":[],"pagination":{"total":0,...}}` | partial mode OK |
| No accounts | 200 | empty items | soft missing balance |
| RabbitMQ failure | 502 | `{"detail":"Internal service error"}` | retry |
| RPC timeout | 504 | `{"detail":"Internal service timeout"}` | retry (max 2) |
| Partial user data | 200 | mixed endpoints | partial mode per data quality rules |

**Idempotency:** all Context Builder reads are GET — safe to retry.

**403:** not explicitly used; unauthorized = 401.

---

## 8. Environment / Deployment

### 8.1 Base URLs

| Environment | URL |
|-------------|-----|
| Local dev (host) | `http://localhost:8081` |
| Docker internal | `http://gateway:8000` |
| Staging/prod | not defined in repo — configure per deployment |

> README mentions port 8080; **docker-compose.yml maps 8081:8000** — use 8081 locally.

### 8.2 Existing env variables (backend)

| Variable | Default | Service |
|----------|---------|---------|
| `JWT_SECRET` | dev-secret-change-me | access, gateway |
| `JWT_ISSUER` | family-budget-backend | access |
| `ACCESS_TOKEN_MINUTES` | 1440 | access |
| `RPC_TIMEOUT_SECONDS` | 30 | gateway |
| `RABBITMQ_URL` | amqp://guest:guest@rabbitmq:5672/%2F | all |
| `DATABASE_URL` | postgresql+psycopg://app:app@postgres:5432/family_budget | workers |

### 8.3 Proposed env for ai-workflow `.env`

```env
CONTEXT_BUILDER_DATA_PROVIDER=http

# Single gateway URL (recommended — all resources via /api/v1)
BACKEND_DATA_SERVICE_URL=http://gateway:8000

# Optional split URLs (all point to same gateway today)
TRANSACTIONS_SERVICE_URL=http://gateway:8000/api/v1/transactions
USER_CONTEXT_SERVICE_URL=http://gateway:8000
CATEGORY_PROFILES_SERVICE_URL=http://gateway:8000

# Service auth (REQUIRED once implemented)
BACKEND_SERVICE_TOKEN=
# OR user delegation:
BACKEND_USER_JWT=

CONTEXT_BUILDER_HTTP_TIMEOUT_SECONDS=30
CONTEXT_BUILDER_HTTP_MAX_RETRIES=2

# Query param mapping
CONTEXT_BUILDER_DATE_FROM_PARAM=date_from
CONTEXT_BUILDER_DATE_TO_PARAM=date_to
```

**Timeout recommendation:** 30s per request (matches gateway RPC timeout); allow 60s for full pagination sequence.

---

## 9. Gaps & Recommended Backend Changes

### 9.1 Gaps table

| Required by AI | Backend status | Gap | Priority | Recommendation |
|----------------|----------------|-----|----------|----------------|
| GET transactions by user+period | ✅ `GET /api/v1/transactions` | param names differ (`date_from` not `start_date`) | P0 | Document mapping; optional alias params |
| Service auth for AI | ❌ JWT user-only | No service token / impersonation | **P0** | Add `X-Service-Key` + `X-User-Id` or OAuth client credentials + user delegation |
| GET user financial context | ❌ | No unified endpoint | **P0** | New `GET /api/v1/users/me/financial-context` aggregating accounts+goals+analytics |
| GET category profiles | ❌ | No taxonomy / optimize flags | **P1** | New table `category_profiles` + `GET /api/v1/category-profiles` |
| GET previous period tx | ✅ same endpoint | — | P1 | Client-side only |
| Merchant filter | ❌ | No `description`/`merchant` query | P1 | Add `merchant` or `description_contains` filter |
| GET goals | ✅ | Not merged into user_context | P2 | Include in financial-context aggregation |
| GET debts | ❌ | No entity | P2 | New `debts` table + CRUD or merge into financial-context |
| current_savings, salary_day | ❌ | Not stored | P2 | Extend user profile or financial-context |
| cached analysis read | ⚠️ partial | snapshots write-only | P2 | `GET /api/v1/analytics/snapshots/latest` |
| ambiguous flag on tx | ❌ | — | P2 | Optional enrichment field |
| Batch multi-user | ❌ | single JWT user | P2 | Internal batch endpoint for service auth |

### 9.2 Concrete backend changes (ordered)

#### P0 — Blockers for production AI integration

1. **Service authentication + user delegation**
   - Add env `SERVICE_API_KEYS` (comma-separated) on gateway
   - New middleware: validate `X-Service-Key`, read `X-User-Id` header (UUID), build `UserContext` without JWT
   - Audit log service access

2. **Financial context endpoint**
   ```
   GET /api/v1/users/me/financial-context
   GET /api/v1/internal/users/{user_id}/financial-context  (service auth)
   ```
   Response schema matching Context Builder reference with nulls for unsupported fields.

3. **Date param aliases on transactions**
   - Accept `start_date` / `end_date` as aliases for `date_from` / `date_to`

#### P1 — Comparison mode & category analysis

4. **Category profiles**
   - Migration: `category_profiles(category_name, category_group, can_optimize, protected_by_default, is_required_expense)`
   - Seed from bank category dictionary
   - `GET /api/v1/category-profiles`

5. **Transaction merchant filter**
   - Add `description` or `merchant` query param (ILIKE)

#### P2 — Enrichment

6. **Debts module** — table + `GET /api/v1/debts`
7. **Profile fields** — `salary_day`, `current_savings` on users or financial_context
8. **Analysis cache read** — expose `available_funds_snapshots` latest row
9. **`transactions.ambiguous`** — optional boolean from import heuristics

---

## 10. Proposed API Contract for Context Builder

Final spec mapping Context Builder fetch functions → backend calls **as-is today**:

### fetch_transactions(user_id, period)

```http
GET /api/v1/transactions?date_from={period.start_date}&date_to={period.end_date}&page=1&page_size=500
Authorization: Bearer {user_jwt_or_service_delegation}
```

Paginate until all items fetched. Optional intent filters append `&type=expense`, `&categories=...`, `&mcc=...`, `&account_id=...`.

### fetch_previous_period_transactions(user_id, period)

Same as above with previous period dates.

### fetch_user_context(user_id)

**Today (composite — 3+ calls):**

```http
GET /api/v1/accounts?page_size=500
GET /api/v1/goals?status=active
GET /api/v1/analytics/expected-incomes?page_size=50
GET /api/v1/analytics/available-balance?period_start={today}&period_end={today}
```

Context Builder assembles into reference shape; mark GAP fields null.

**Target (after P0):**

```http
GET /api/v1/internal/users/{user_id}/financial-context
X-Service-Key: {key}
```

### fetch_category_profiles(user_id)

**Today:** not available. Options:
- Return empty list + `partial_mode` flag, OR
- Static config in ai-workflow until P1 backend endpoint

**Target:**

```http
GET /api/v1/category-profiles
Authorization: Bearer ... OR X-Service-Key + X-User-Id
```

### Data quality mapping

| Field | Missing severity |
|-------|------------------|
| transactions (empty) | hard missing → clarification_required |
| current_balance | soft missing → partial mode |
| current_savings | soft missing |
| category_profiles | soft missing → partial mode |
| debts | optional |
| goals | optional for non-goal intents |

---

## Appendix A: OpenAPI

- Swagger UI: `http://localhost:8081/docs`
- OpenAPI JSON: `http://localhost:8081/openapi.json`
- Contract tests: `tests/test_gateway_openapi.py`

## Appendix B: Key source files

| Area | Path |
|------|------|
| Gateway routes | `services/gateway/app/main.py` |
| Gateway DTOs | `services/gateway/app/schemas.py` |
| Transaction filters | `services/finance_service/app/main.py` → `_apply_transaction_filters` |
| Transaction model | `services/finance_service/app/models.py` |
| Excel parser | `services/file_service/app/imports/parsers/family_budget_excel_v1.py` |
| Analytics | `services/analytics_service/app/main.py` |
| Migrations | `services/migration_service/migrations/` |
| JWT | `libs/common/common/security.py` |

## Appendix C: Sample files

| File | Description |
|------|-------------|
| [transactions.sample.json](ai-integration-samples/transactions.sample.json) | GET /transactions response |
| [previous_period_transactions.sample.json](ai-integration-samples/previous_period_transactions.sample.json) | April comparison period |
| [user_context.sample.json](ai-integration-samples/user_context.sample.json) | Composite assembly + GAP notes |
| [category_profiles.sample.json](ai-integration-samples/category_profiles.sample.json) | Reference vs backend gap |
| [goals.sample.json](ai-integration-samples/goals.sample.json) | GET /goals response |
| [debts.sample.json](ai-integration-samples/debts.sample.json) | Empty — entity missing |
