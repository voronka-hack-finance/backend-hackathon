# Backend Plan
Date: 2026-05-30
Status: Draft
Scope: backend MVP for fintech hackathon

## Context

The project is an MVP for personal and family finance analysis and management.

Financial health formulas and agent metric contracts are defined in `docs/Формулы_финансового_здоровья_и_ИИ_агенты.md`. A dedicated `health-score-service` implements those calculations using only data already stored by finance/analytics services.

The exact hackathon case is still flexible, so the backend must keep service boundaries explicit and easy to revise.

Core approved stack:

- Python + FastAPI for service runtimes;
- SQLAlchemy for DB access;
- Alembic for PostgreSQL schema migrations;
- PostgreSQL for durable data;
- MinIO for uploaded source files;
- RabbitMQ as the only internal project communication bus;
- Redis for optional cache/status/idempotency;
- Docker containers for every service and infrastructure dependency;
- TOML dependency files, most likely `pyproject.toml`.

Approved import flow:

1. User uploads an Excel file like `family-bugget.xlsx`.
2. Original file is stored.
3. Only sheets with prefixes `Р_...` and `Д_...` are parsed.
4. Parsed rows become normalized financial transactions.
5. Data is scoped to the authenticated user from verified JWT context.
6. Existing accounts are reused; missing accounts are created during import.
7. Duplicate transactions are not inserted again.
8. Public data is returned through `api-gateway-service` endpoints with pagination and filters.

## Communication Model

Authoritative decision: all project-internal communication happens through RabbitMQ task/message queues.

Public HTTP exists only between frontend and `api-gateway-service`.

Rules:

- frontend never talks directly to business services;
- backend services do not call each other through internal HTTP;
- `api-gateway-service` maps public HTTP requests to RabbitMQ task messages;
- command, query, background task, event, and reply are message types inside RabbitMQ, not separate transport mechanisms;
- synchronous public reads use RabbitMQ request-reply with `correlation_id`, `reply_to`, timeout, and typed reply messages;
- long-running actions return job/status ids and continue through background tasks/events;
- user context is carried in RabbitMQ message metadata after `access-service` verifies JWT;
- service handlers do not trust `user_id` from request payload;
- all business services may expose only technical `GET /health` and `GET /ready` probe endpoints for Docker/orchestration checks.

Message metadata:

| Field | Required | Purpose |
|-------|----------|---------|
| `message_id` | yes | idempotency and duplicate protection |
| `correlation_id` | yes | trace one frontend action across messages |
| `reply_to` | request-reply only | reply queue for synchronous calls |
| `type` | yes | command/query/event/reply name |
| `source` | yes | publisher service name |
| `user.id` | protected user operations | authenticated user scope |
| `user.email` | optional | display/audit metadata |
| `auth.scopes` | optional | coarse permission hints |
| `created_at` | yes | message creation time |

RabbitMQ task/message kinds:

| Kind | Reply | Example |
|------|-------|---------|
| Command task | usually | `accounts.create` |
| Query task | yes | `transactions.list` |
| Background task | no immediate public reply | `files.import.run` |
| Event task | no | `files.import.completed.v1` |
| Reply message | no | `transactions.list.reply` |

## Services And Responsibility Zones

### 1. api-gateway-service

Public HTTP entry point and HTTP-to-RabbitMQ adapter.

Responsibilities:

- accepts all external HTTP requests;
- accepts multipart file upload from frontend;
- publishes RabbitMQ task messages for other services;
- asks `access-service` to verify JWT through `auth.verify_token`;
- creates trusted RabbitMQ metadata after auth verification;
- waits for RabbitMQ replies for synchronous endpoints;
- returns job/status ids for long operations;
- converts internal replies/errors to public HTTP responses;
- hides internal queues, service names, stack traces, and raw service errors.

Does not own:

- user storage or password/JWT rules;
- files parsing;
- financial data;
- family/group rules;
- analytics calculations.

### 2. access-service

Authentication, registration, user profile, and token lifecycle.

Approved public endpoints through gateway:

- `POST /api/v1/auth/register`;
- `POST /api/v1/auth/login`;
- `POST /api/v1/auth/logout`;
- `POST /api/v1/auth/refresh`;
- `GET /api/v1/auth/me`;
- `PATCH /api/v1/auth/me`;
- `POST /api/v1/auth/change-password`;
- other authorization endpoints must be approved before they become part of the plan.

Responsibilities:

- register users;
- verify login/password;
- issue, refresh, and revoke tokens;
- verify JWT for gateway through RabbitMQ message `auth.verify_token`;
- return trusted identity context to gateway;
- store password hashes, not plain passwords;
- store user profile fields needed by `me`;
- handle password change.

Owns data:

- `users`;
- `refresh_sessions` or equivalent token/session table;
- user auth/profile fields needed for `me`.

### 3. migration-service

One-shot startup service for PostgreSQL schema migrations and optional dev data bootstrap.

Responsibilities:

- waits for PostgreSQL;
- applies Alembic migrations to `head` in deterministic revision order;
- records applied revision in `alembic_version` (Alembic standard);
- optionally runs dev-only data reset and Excel/demo bootstrap after schema is current;
- exits with `0` on success;
- exits non-zero if app services must not start.

Does not own:

- MinIO bucket creation;
- public HTTP API or `/health` probes (one-shot CLI job; Compose uses `service_completed_successfully`);
- business runtime;
- long-lived migration CLI outside container startup (developers run Alembic locally against the same config).

Legacy note: the repo currently ships numbered raw SQL files under `services/migration_service/migrations/` and a custom `schema_migrations` tracker. The approved direction is to replace that runner with Alembic (see [Database Migrations (Alembic)](#database-migrations-alembic)).

### 4. create-bucket-service

One-shot startup service for MinIO bootstrap.

Responsibilities:

- waits for MinIO;
- creates required buckets;
- applies required bucket policies;
- records or logs bucket bootstrap state;
- exits with `0` on success.

Does not own:

- PostgreSQL migrations;
- file parsing;
- public HTTP API or `/health` probes (one-shot CLI job).

### 5. file-service

File ingestion service. Owns uploaded source files and import pipeline.

Approved public endpoints through gateway:

- CRUD for the list of uploaded source files;
- endpoints for upload/import status and import errors related to source tables.

Responsibilities:

- receives file-related RabbitMQ commands from gateway;
- stores original source files in MinIO;
- stores file metadata and import jobs in PostgreSQL;
- parses transaction spreadsheets;
- imports only approved sheets `Р_...` and `Д_...`;
- creates accounts during import if they do not exist;
- reuses existing accounts if they already exist;
- adds only transactions that have not been added before;
- stores parser/import errors with human-readable `message`;
- publishes import status events.

Owns data:

- `uploaded_files`;
- `import_jobs`;
- `import_errors`;
- import parser metadata.

Writes finance data during import:

- accounts created from imported file context;
- imported transactions;
- raw imported categories/card metadata needed for import traceability.

Integration note: spreadsheet account resolution is performed inside `finance-service` `transactions.bulk_create` during import (not a separate gateway HTTP call). Internal RPC `accounts.resolve_by_card` remains for other services. Cross-file transaction dedupe uses `(user_id, dedupe_key)`.

### 6. finance-service

User-facing finance data service.

Approved public endpoints through gateway:

- `GET /api/v1/transactions` with pagination and filters;
- `GET /api/v1/accounts`;
- CRUD for savings goals;
- CRUD for account limits;
- CRUD for user categories;
- CRUD for user debts (loans, credit cards, other obligations).

Responsibilities:

- returns current transactions with pagination and filters;
- returns accounts;
- manages accounts for user-facing finance operations;
- manages transactions for user-facing finance operations;
- manages savings goals;
- manages limits by account/category;
- manages custom categories;
- manages user debt records (remaining balance, monthly payment, credit limit, overdue state);
- calculates current account values needed by finance screens;
- answers RabbitMQ queries from analytics/group/scheduler/health-score when they need scoped finance data.

Owns user-facing finance read/write behavior for:

- `accounts`;
- `transactions`;
- `account_categories`;
- `category_limits`;
- `savings_goals`;
- `user_debts`.

Important boundary:

- `file-service` may write imported accounts/transactions as part of ingestion;
- `finance-service` owns user-facing CRUD/read behavior and finance policies around those records.

### 7. scheduler-service

Planning and reminder orchestration.

Responsibilities:

- plans user reminders for upcoming expected regular charges;
- detects when user spending is close to limits;
- creates scheduled notification tasks;
- consumes analytics/finance events needed for reminder planning;
- publishes notification send tasks to `notification-service`.

Owns data:

- reminder plans;
- reminder execution state;
- limit-warning schedule state.

No public business endpoints are approved yet, except health/ready probes.

### 8. notification-service

User notification delivery through Firebase.

Approved public endpoints through gateway:

- endpoints to allow/enable notifications;
- endpoints to save `device_id`;
- endpoint to send a test notification.

Responsibilities:

- stores user device identifiers;
- stores notification permission/preference state;
- sends push notifications through Firebase;
- consumes scheduler notification tasks;
- records delivery attempts/results.

Owns data:

- `notification_devices`;
- `notification_preferences`;
- `notification_deliveries`.

### 9. analytics-service

Finance analysis service.

Approved public endpoints through gateway:

- `GET /api/v1/analytics/regular-expenses`;
- `POST /api/v1/analytics/regular-expenses`;
- `GET /api/v1/analytics/regular-expenses/{regular_expense_id}`;
- `PATCH /api/v1/analytics/regular-expenses/{regular_expense_id}`;
- `DELETE /api/v1/analytics/regular-expenses/{regular_expense_id}`;
- `GET /api/v1/analytics/available-balance`;
- `GET /api/v1/analytics/expected-incomes`;
- `GET /api/v1/analytics/expected-expenses`.

Responsibilities:

- detects regular user expenses;
- stores and manages regular payment records manually created by the user, for example subscriptions, rent, utilities, or other planned recurring charges;
- lets the user correct or disable automatically detected regular payments without editing source transactions;
- estimates user income;
- calculates available funds for a period after regular expenses;
- excludes irregular and impulsive purchases from available-funds estimate;
- stores or caches analysis results needed by recommendations;
- provides per-user analytics for direct display;
- provides per-user analytics to `group-service` for family budget assembly.

Owns data:

- regular payment records: detected regular expenses and manually maintained recurring charges;
- expected income records;
- expected expense records;
- available funds snapshots/results.

### 10. group-service

Family/group collaboration service.

Approved public endpoints through gateway:

- CRUD for family/group creation and management;
- `GET` for family budget assembly;
- CRUD for family members;
- CRUD for family invitations;
- `POST` accept family invitation;
- `POST` decline family invitation.

Responsibilities:

- creates and manages family groups;
- sends invitations;
- accepts and declines invitations;
- manages group members and member roles/statuses;
- checks group membership for family operations;
- assembles family budget by requesting per-member data from `analytics-service`;
- coordinates family access without moving finance ownership out of finance-service.

Owns data:

- `family_groups`;
- `family_members`;
- `family_invitations`.

### 11. chat-service

Agent recommendations and chat service.

Approved public endpoints through gateway:

- `GET` initial recommendations from all agents;
- `GET` chat history;
- `POST` create chat message;
- CRUD for chat list.

Responsibilities:

- stores chats;
- stores chat messages;
- returns initial agent recommendations;
- coordinates recommendation agents;
- requests ready-made health/metrics profile from `health-score-service` instead of assembling ad-hoc finance/analytics slices;
- keeps chat history separate from source finance data.

Owns data:

- `chats`;
- `chat_messages`;
- `agent_recommendations`.

### 12. health-score-service

Financial and credit health scoring service. Implements metric formulas from `docs/Формулы_финансового_здоровья_и_ИИ_агенты.md` using only data that already exists in the project.

Approved public endpoints through gateway:

- `GET /api/v1/health/profile` — full calculated metrics profile for the current period (the JSON shape from formulas doc section 8, with explicit `null` / `data_gaps` for unavailable fields);
- `GET /api/v1/health/score` — compact dashboard view: `financial_health_score`, status label, `credit_load_index`, credit zone label, top 3 risk drivers;
- `GET /api/v1/health/history` — paginated list of stored monthly snapshots for trend charts.

Responsibilities:

- aggregates scoped finance/analytics data through RabbitMQ request-reply (does not read other services' PostgreSQL tables directly);
- normalizes transactions into income/expense/transfer/cash/uncategorized buckets for the selected period;
- calculates primary metrics: `total_income`, `total_expenses`, `net_cashflow`, `expense_to_income_ratio`, `savings_rate`, category breakdowns;
- calculates secondary metrics: `clarity_score`, category overspend vs limits, `forecast_expenses`, `forecast_balance`, `safe_daily_budget`, goal progress/affordability;
- calculates composite indicators: `financial_health_score`, simplified `credit_load_index`;
- stores monthly snapshot rows for history and cache;
- publishes `health.profile.calculated.v1` event after successful recalculation (optional consumer: `chat-service`, `scheduler-service`);
- exposes agent-ready profile payload for `chat-service` and external AI Context Builder (same contract as section 8 of the formulas doc).

Does not own:

- raw transactions, accounts, goals, limits, categories, debts;
- regular expense detection logic;
- user-facing CRUD for finance entities;
- LLM calls or chat history.

#### Input data sources (existing project only)

| Need | Source | RabbitMQ / field |
|------|--------|------------------|
| Transactions for period | `finance-service` | `transactions.list` with `date_from`, `date_to`, `status=OK`, pagination |
| Period income/expense totals | `finance-service` | `transactions.sum_by_scope` |
| Account balances | `finance-service` | `accounts.list` → `current_balance` |
| Balance before period | `finance-service` | `finance.balance_before_period` |
| Category limits | `finance-service` | `limits.list` |
| Savings goals | `finance-service` | `goals.list` |
| User debts | `finance-service` | `debts.list` |
| Regular (fixed) expenses | `analytics-service` | `analytics.regular_expenses.list` |
| Expected income/expense | `analytics-service` | `analytics.expected_incomes.list`, `analytics.expected_expenses.list` |
| Available funds snapshot | `analytics-service` | `analytics.available_balance.get` |

Explicitly **not** available in the current backend (must not be invented):

- `is_fixed` flag on transactions;
- AI category profiles (`categoryGroup`, `canOptimize`) — see `docs/ai-integration-samples/category_profiles.sample.json`.

#### Metric coverage and fallbacks

**Fully supported from transactions + accounts + limits + goals + analytics:**

- `total_income`, `total_expenses`, `net_cashflow`, `expense_to_income_ratio`, `savings_rate`, `expense_progress`;
- `category_expenses`, `category_share`, `category_overspend`, `category_overspend_percent` (when `category_limits` exist);
- `unclear_expenses`, `clarity_score` — bank categories `Переводы`, `Наличные`, plus expenses with empty `category_name`;
- `optional_expenses` — static MVP mapping aligned with formulas doc: `Рестораны`, `Фастфуд`, `Маркетплейсы`, `Подписки` (matched by `category_name` case-insensitive);
- `fixed_expenses` — sum of `COALESCE(regular_expenses.expected_amount, regular_expenses.average_amount)` where status `active` (manual planned amount first, detected average as fallback; proxy for `is_fixed`);
- `variable_expenses` — `total_expenses - fixed_expenses`;
- `saving_potential_soft/normal/hard` — from `optional_expenses`;
- `average_daily_expense`, `forecast_expenses`, `forecast_balance`, `safe_daily_budget` — use `expected_incomes` / `expected_expenses` when present, otherwise current-month run-rate;
- `goal_progress`, `required_monthly_saving`, `goal_affordability` — from `savings_goals`;
- `reserve_months` — `SUM(accounts.current_balance) / mandatory_monthly_expenses`, where `mandatory_monthly_expenses = fixed_expenses + expenses in bank categories ЖКХ, Кредиты, Супермаркеты` for the period (normalized to monthly);
- `income_stability_score` — coefficient of variation of monthly income totals over last 3 complete calendar months from transactions;
- `financial_health_score` — weighted formula from doc section 5.1; components without data are excluded and weights renormalized (see below).

**Supported from `user_debts` when user maintains debt records (preferred over transaction proxy):**

- `monthly_credit_payments` — `SUM(monthly_payment)` for active debts with `monthly_payment > 0`; fallback: sum of expense `payment_amount` where `category_name` matches `Кредиты` (or import alias `credits`) in the selected month;
- `debt_to_income_ratio` — `monthly_credit_payments / average_monthly_income * 100`, where `average_monthly_income` is mean of last 3 months income totals;
- `active_credits_count` — count of active debts with `debt_type` in (`loan`, `credit_card`); fallback: distinct merchant patterns among credit-category expenses with recurring pattern (≥2 months);
- `credit_card_utilization` — `SUM(remaining_balance) / SUM(credit_limit) * 100` across active `debt_type=credit_card` rows where `credit_limit > 0`; if multiple cards, aggregate balances and limits separately before ratio;
- `overdue_days` — `MAX(overdue_days)` across active debts; `overdue_score` from formulas doc section 6;
- `credit_card_utilization_score` — derived from `credit_card_utilization` when debt records exist;
- `free_cashflow_after_debt` — uses debt-based `monthly_credit_payments` when available;
- simplified `credit_load_index` — uses all components with data; when debts exist, `credit_load_index_partial: false` for credit-card and overdue components; otherwise partial proxy as before.

**Not calculated (return `null` + reason in `data_gaps`):**

- `credit_card_utilization`, `overdue_days`, `overdue_score`, `credit_card_utilization_score` — when user has no active `user_debts` and transaction proxy is insufficient;
- exact `budget_score` when user has no `category_limits` covering ≥50% of expense categories;
- `goal_score` when user has no active `savings_goals`.

#### `financial_health_score` weight renormalization

Base weights from formulas doc: cashflow 25%, debt 20%, reserve 15%, budget 15%, clarity 10%, goal 10%, income stability 5%.

If a component cannot be computed, drop it and scale remaining weights to 100%. Example: no goals → goal 10% redistributed across other present components. Response always includes `score_components` with raw 0–100 values and `weights_applied`.

#### Status labels (user-facing)

| Score range | `financial_health_status` |
|-------------|---------------------------|
| 80–100 | `good` |
| 60–79 | `stable_with_growth_areas` |
| 40–59 | `needs_control` |
| 20–39 | `survival_mode` |
| 0–19 | `alert` |

| Index range | `credit_load_zone` |
|-------------|-------------------|
| 0–25 | `green` |
| 26–50 | `yellow` |
| 51–75 | `orange` |
| 76–100 | `red` |

Owns data:

- `health_score_snapshots` — monthly calculated profile JSON, composite scores, period key, `calculated_at`;
- optional Redis cache keyed by `(user_id, period)` with TTL aligned to import/analytics refresh.

Triggers for recalculation:

- on demand via `GET /api/v1/health/profile?refresh=true`;
- background task on `files.import.completed.v1` (user has new transactions);
- optional nightly rescan per user with recent activity.

## Health And Readiness

Every service exposes technical probe endpoints:

- `GET /health` - process is alive;
- `GET /ready` - service can do useful work.

Readiness examples:

- `api-gateway-service`: RabbitMQ reachable;
- `access-service`: PostgreSQL and RabbitMQ reachable;
- `migration-service`: Alembic migrations applied to `head` successfully;
- `create-bucket-service`: buckets exist;
- file/finance/group/chat/analytics/scheduler/notification/health-score services: own DB dependencies and RabbitMQ reachable;
- `notification-service`: Firebase config present and RabbitMQ reachable.

These probes are not business communication between services.

## Database Migrations (Alembic)

Authoritative decision: PostgreSQL schema evolution moves from hand-written numbered `.sql` files to **Alembic** managed by `migration-service`.

All services continue to share one PostgreSQL database. Schema ownership stays centralized in `migration-service`; individual services keep SQLAlchemy models as the declared shape of their tables.

### Current state (legacy, to be retired)

| Piece | Location | Notes |
|-------|----------|-------|
| SQL files | `services/migration_service/migrations/*.sql` | Sorted by filename (`000_…`, `005_…`, …) |
| Runner | `services/migration_service/app/main.py` → `_apply_migrations()` | Executes whole files once |
| Tracking | `schema_migrations(version text PK)` | Custom table, not Alembic |

### Target layout

```text
services/migration_service/
  alembic.ini
  alembic/
    env.py                 # DB URL from settings; combined target_metadata
    script.py.mako
    versions/              # linear revision chain only
      0001_initial_schema.py
      0002_user_debts.py
      ...
  app/
    main.py                # wait postgres → alembic upgrade head → bootstrap
    bootstrap.py           # data seed only (unchanged responsibility)
    reset.py               # dev reset only
  migrations/              # legacy SQL — archived after baseline, no new files
```

Add `alembic>=1.13` to root `pyproject.toml`.

### `env.py` and combined metadata

`target_metadata` must register **all** ORM tables from service packages, for example:

- `services.access_service.app.models`
- `services.file_service.app.models`
- `services.finance_service.app.models`
- analytics, group, chat, health-score, notification, scheduler models when present

Tables that exist only in SQL today (no ORM yet) stay in the baseline revision until a service adds a model; new changes after baseline should prefer model + autogenerate, with manual edits in the revision file.

`env.py` reads `DATABASE_URL` from the same settings object used by `migration-service` startup so Docker Compose and local CLI share one connection config.

### Startup sequence (after Alembic cutover)

1. Wait until PostgreSQL accepts connections.
2. Run `alembic upgrade head` (replaces `_apply_migrations()`).
3. If `BOOTSTRAP_RESET_ON_START=true` (dev), run `reset_application_data()`.
4. If `BOOTSTRAP_EXCEL_ENABLED=true`, run `run_bootstrap()`.
5. Exit `0`.

Compose dependency graph is unchanged: every runtime service waits for `migration-service` `service_completed_successfully`.

### Developer workflow

| Task | Command |
|------|---------|
| Apply all pending revisions | `alembic -c services/migration_service/alembic.ini upgrade head` |
| Create revision (autogenerate draft) | `alembic -c services/migration_service/alembic.ini revision --autogenerate -m "describe change"` |
| Create empty revision | `alembic revision -m "describe change"` |
| Roll back one revision (local dev) | `alembic downgrade -1` |
| Show current revision | `alembic current` |
| Show history | `alembic history` |

Rules:

- every schema change ships as a new file under `alembic/versions/`;
- autogenerate output is **never** committed without human review (indexes, `server_default`, FK names, data backfills);
- keep revision chain linear on `main` — no merge heads in MVP;
- schema migrations must not embed demo users, Excel import, or bucket setup (those stay in `bootstrap.py` / `create-bucket-service`).

### Transition plan (numbered SQL → Alembic)

1. **Add Alembic scaffold** — `alembic.ini`, `alembic/env.py`, empty `versions/`.
2. **Baseline revision** — create `0001_initial_schema` whose `upgrade()` reproduces the schema produced by the current SQL chain (`000_common` … latest). Treat existing `.sql` files as read-only reference while writing the baseline; do not run both systems on fresh installs after cutover.
3. **Bridge existing databases** — one-time revision or startup helper:
   - if `alembic_version` is empty but `schema_migrations` has rows → `alembic stamp 0001_initial_schema` (schema already applied), then drop `schema_migrations`;
   - fresh database → normal `upgrade head` from empty.
4. **Switch runner** — replace `_apply_migrations()` in `main.py` with Alembic CLI/API call; remove inserts into `schema_migrations`.
5. **Freeze legacy SQL** — stop adding files under `migrations/*.sql`; document folder as archived baseline source.
6. **New features via Alembic only** — e.g. `user_debts` lands in `0002_user_debts.py` (or next revision), not `080_….sql`.
7. **Tests** — extend migration tests: fresh DB reaches `head`, bridge path from legacy `schema_migrations`, optional downgrade smoke on non-prod.

### What does not move to Alembic

| Concern | Owner | Reason |
|---------|-------|--------|
| Demo user + Excel import | `migration-service` `bootstrap.py` | repeatable dev seed, not schema |
| Dev table truncate | `migration-service` `reset.py` | environment tooling |
| MinIO buckets | `create-bucket-service` | object storage, not PostgreSQL |
| `bootstrap_runs` data rows | `bootstrap.py` | runtime seed state |

## RabbitMQ Message Draft

Message names are draft contracts and may be renamed before implementation.

### access-service

- `auth.register`;
- `auth.login`;
- `auth.logout`;
- `auth.refresh`;
- `auth.me.get`;
- `auth.me.patch`;
- `auth.change_password`;
- `auth.verify_token`;
- `users.get`.

### file-service

- `files.upload.create`;
- `files.list`;
- `files.get`;
- `files.update`;
- `files.delete`;
- `imports.status.get`;
- `imports.errors.list`;
- `files.import.run`;
- `files.import.started.v1`;
- `files.import.completed.v1`;
- `files.import.failed.v1`;

### finance-service

- `transactions.list`;
- `transactions.get`;
- `transactions.create`;
- `transactions.update`;
- `transactions.delete`;
- `transactions.bulk_create`;
- `transactions.sum_by_scope`;
- `accounts.list`;
- `accounts.get`;
- `accounts.create`;
- `accounts.update`;
- `accounts.delete`;
- `goals.*`;
- `limits.*`;
- `categories.*`;
- `debts.list`;
- `debts.get`;
- `debts.create`;
- `debts.update`;
- `debts.delete`.

### scheduler-service

- `reminders.plan_regular_expenses`;
- `reminders.plan_limit_warning`;
- `reminders.due.scan`;
- `notifications.schedule`.

### notification-service

- `notifications.permission.set`;
- `notifications.devices.save`;
- `notifications.test.send`;
- `notifications.send`;

### analytics-service

- `analytics.regular_expenses.detect`;
- `analytics.regular_expenses.list` (needed by `health-score-service` for `fixed_expenses`);
- `analytics.regular_expenses.get`;
- `analytics.regular_expenses.create`;
- `analytics.regular_expenses.update`;
- `analytics.regular_expenses.delete`;
- `analytics.expected_incomes.list`;
- `analytics.expected_expenses.list`;
- `analytics.available_balance.get`;
- `analytics.member_budget.get`;
- `analytics.member_budget.batch` (family group budget aggregation);
- `analytics.regular_expenses.due_for_reminders` (scheduler integration).

### group-service

- `groups.*`;
- `group_members.*`;
- `group_invitations.*`;
- `group_invitations.accept`;
- `group_invitations.decline`;
- `groups.family_budget.get`.

### chat-service

- `chat.recommendations.initial.get`;
- `chats.*`;
- `chat_messages.list`;
- `chat_messages.create`.

### health-score-service

- `health.profile.get` — full agent-ready metrics profile for period;
- `health.score.get` — compact score + status labels;
- `health.history.list` — paginated snapshots;
- `health.profile.recalculate` — background/full refresh command;
- `health.profile.calculated.v1` — event after snapshot stored.

Internal read dependencies (request-reply to other queues, not owned messages):

- `transactions.list`, `transactions.sum_by_scope`, `accounts.list`, `finance.balance_before_period`, `limits.list`, `goals.list`, `debts.list`;
- `analytics.available_balance.get`, `analytics.expected_incomes.list`, `analytics.expected_expenses.list`, `analytics.regular_expenses.list`.

## Public API Draft

All public endpoints are served by `api-gateway-service`.

### Access

```text
POST  /api/v1/auth/register
POST  /api/v1/auth/login
POST  /api/v1/auth/logout
POST  /api/v1/auth/refresh
GET   /api/v1/auth/me
PATCH /api/v1/auth/me
POST  /api/v1/auth/change-password
```

### Files

```text
POST   /api/v1/files
GET    /api/v1/files
GET    /api/v1/files/{file_id}
PATCH  /api/v1/files/{file_id}
DELETE /api/v1/files/{file_id}
GET    /api/v1/imports/{import_id}
GET    /api/v1/imports/{import_id}/errors
```

### Finance

```text
GET    /api/v1/transactions
GET    /api/v1/accounts
GET    /api/v1/goals
POST   /api/v1/goals
GET    /api/v1/goals/{goal_id}
PATCH  /api/v1/goals/{goal_id}
DELETE /api/v1/goals/{goal_id}
GET    /api/v1/limits
POST   /api/v1/limits
GET    /api/v1/limits/{limit_id}
PATCH  /api/v1/limits/{limit_id}
DELETE /api/v1/limits/{limit_id}
GET    /api/v1/categories
POST   /api/v1/categories
GET    /api/v1/categories/{category_id}
PATCH  /api/v1/categories/{category_id}
DELETE /api/v1/categories/{category_id}
GET    /api/v1/debts
POST   /api/v1/debts
GET    /api/v1/debts/{debt_id}
PATCH  /api/v1/debts/{debt_id}
DELETE /api/v1/debts/{debt_id}
```

Debt record fields (request/response DTO):

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | uuid | response | |
| owner_user_id | uuid | response | from JWT scope |
| account_id | uuid | optional | link to credit-card account when known |
| title | string | yes | e.g. `Ипотека`, `Кредитная карта *8336` |
| debt_type | string | yes | `loan`, `credit_card`, `other` |
| remaining_balance | decimal string | yes | current outstanding amount |
| credit_limit | decimal string | credit_card | required when `debt_type=credit_card` |
| monthly_payment | decimal string | optional | planned monthly payment |
| currency | string | yes | default `RUB` |
| payment_day | int | optional | day of month (1–31) |
| overdue_days | int | optional | user-maintained overdue duration |
| interest_rate | decimal string | optional | annual rate if known |
| status | string | yes | `active`, `closed`, `deleted` |
| created_at / updated_at | datetime | response | |

List filters: `status` (default `active`), optional `debt_type`.

Aggregates for AI Context Builder and health-score (computed server-side, not stored):

- `has_debt` — any active debt with `remaining_balance > 0`;
- `debt_amount` — `SUM(remaining_balance)` for active debts;
- `monthly_debt_payment` — `SUM(monthly_payment)` for active debts.

### Notifications

```text
POST /api/v1/notifications/permission
POST /api/v1/notifications/devices
POST /api/v1/notifications/test
```

### Analytics

```text
GET    /api/v1/analytics/regular-expenses
POST   /api/v1/analytics/regular-expenses
GET    /api/v1/analytics/regular-expenses/{regular_expense_id}
PATCH  /api/v1/analytics/regular-expenses/{regular_expense_id}
DELETE /api/v1/analytics/regular-expenses/{regular_expense_id}
GET    /api/v1/analytics/available-balance
GET    /api/v1/analytics/expected-incomes
GET    /api/v1/analytics/expected-expenses
```

### Groups

```text
GET    /api/v1/groups
POST   /api/v1/groups
GET    /api/v1/groups/{group_id}
PATCH  /api/v1/groups/{group_id}
DELETE /api/v1/groups/{group_id}
GET    /api/v1/groups/{group_id}/budget
GET    /api/v1/groups/{group_id}/members
POST   /api/v1/groups/{group_id}/members
PATCH  /api/v1/groups/{group_id}/members/{member_id}
DELETE /api/v1/groups/{group_id}/members/{member_id}
GET    /api/v1/groups/{group_id}/invitations
POST   /api/v1/groups/{group_id}/invitations
PATCH  /api/v1/groups/{group_id}/invitations/{invitation_id}
DELETE /api/v1/groups/{group_id}/invitations/{invitation_id}
POST   /api/v1/group-invitations/{invitation_id}/accept
POST   /api/v1/group-invitations/{invitation_id}/decline
```

### Chat

```text
GET    /api/v1/chats/recommendations
GET    /api/v1/chats
POST   /api/v1/chats
GET    /api/v1/chats/{chat_id}
PATCH  /api/v1/chats/{chat_id}
DELETE /api/v1/chats/{chat_id}
GET    /api/v1/chats/{chat_id}/messages
POST   /api/v1/chats/{chat_id}/messages
```

### Health

```text
GET /api/v1/health/profile
GET /api/v1/health/score
GET /api/v1/health/history
```

Query params for profile/score:

- `period` — calendar month `YYYY-MM` (default: current UTC month);
- `refresh` — `true` forces recalculation instead of cached snapshot.

### Technical Probes

```text
GET /health
GET /ready
```

## Data Model Draft

Detailed ER diagram: `docs/backend-er-diagram.md`.

Primary ownership:

| Data | Owner |
|------|-------|
| users, sessions | access-service |
| uploaded files, import jobs, import errors | file-service |
| accounts, transactions, goals, limits, categories, user_debts | finance-service |
| reminder plans and warning schedules | scheduler-service |
| devices, notification preferences, delivery log | notification-service |
| regular payment records, expected income/expense, available funds | analytics-service |
| family groups, members, invitations | group-service |
| chats, messages, agent recommendations | chat-service |
| health score snapshots | health-score-service |
| schema migrations (`alembic_version`) | migration-service |
| MinIO bucket bootstrap state | create-bucket-service |

### health-score-service tables (draft)

`health_score_snapshots`:

| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| user_id | uuid FK → users | |
| period | varchar(7) | `YYYY-MM` |
| financial_health_score | numeric(5,2) | 0–100 |
| credit_load_index | numeric(5,2) | 0–100, may be partial |
| financial_health_status | varchar(32) | enum-like string |
| credit_load_zone | varchar(16) | green/yellow/orange/red |
| profile_json | jsonb | full section-8 payload + `data_gaps` |
| score_components | jsonb | per-component scores and applied weights |
| calculated_at | timestamptz | |
| created_at | timestamptz | |

Unique: `(user_id, period)`.

### finance-service tables (draft) — `user_debts`

| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| owner_user_id | uuid FK → users | indexed |
| account_id | uuid FK → accounts | nullable; optional link to card account |
| title | varchar(255) | |
| description | text | nullable |
| debt_type | varchar(32) | `loan`, `credit_card`, `other` |
| remaining_balance | numeric(18,2) | current outstanding amount |
| credit_limit | numeric(18,2) | nullable; used for `credit_card` |
| monthly_payment | numeric(18,2) | nullable |
| currency | varchar(8) | default `RUB` |
| payment_day | smallint | nullable, 1–31 |
| overdue_days | integer | nullable, default 0 |
| interest_rate | numeric(8,4) | nullable |
| status | varchar(32) | `active`, `closed`, `deleted` |
| created_at | timestamptz | |
| updated_at | timestamptz | |

Index: `(owner_user_id, status)`, `(owner_user_id, debt_type)`.

Validation rules:

- `credit_limit` required and `> 0` when `debt_type=credit_card`;
- `remaining_balance >= 0`;
- soft delete via `status=deleted` (same pattern as goals/limits);
- all queries scoped to `owner_user_id` from RabbitMQ envelope.

## Parser Strategy

Parser interface should remain replaceable:

- `supports(file_metadata, workbook_metadata) -> bool`;
- `parse(file_stream) -> Iterable[ParsedTransaction]`;
- `validate_header(sheet_name, header_row) -> ValidationResult`;
- `normalize_row(sheet_name, row_number, row_values) -> ParsedTransaction`.

Rules:

- include only sheets matching source prefixes `Р_...` and `Д_...`;
- skip all other sheets;
- require the known export header;
- preserve original row in `raw_payload`;
- convert money to decimal, not float;
- keep original category and description text as-is;
- generate human-readable `message` for file/sheet/row errors.

## MVP Constraints

- All public business endpoints require JWT unless explicitly public auth endpoint.
- Public clients can call only `api-gateway-service`.
- Backend business services communicate through RabbitMQ only.
- Health/ready endpoints are technical probes, not service-to-service business APIs.
- Imported files, imports, transactions, accounts, goals, limits, categories, debts, analytics, health scores, groups, notifications, and chats are user-scoped.
- Family/group access is handled by `group-service` plus finance/analytics checks through RabbitMQ.
- Descriptions from source files are stored as-is for MVP.
- Upload has no product-level max size for MVP, but invalid/corrupt/unsupported workbooks are rejected.
- Simple dashboard sums can stay frontend-side unless explicitly owned by analytics/finance/health-score endpoint.

## MVP Build Order

1. Docker Compose with PostgreSQL, MinIO, RabbitMQ, Redis.
2. `migration-service` for PostgreSQL migrations (legacy numbered SQL until Alembic cutover).
3. **Alembic migration system** — baseline revision from existing SQL, switch startup to `alembic upgrade head`, retire `schema_migrations` (see [Database Migrations (Alembic)](#database-migrations-alembic)).
4. `create-bucket-service` for MinIO buckets.
5. Shared RabbitMQ message envelope library.
6. `access-service` register/login/refresh/logout/me/change-password plus `auth.verify_token`.
7. `api-gateway-service` route-to-message mapping and request-reply support.
8. `file-service` upload metadata, MinIO storage, import jobs, parser.
9. `finance-service` account/transaction/category/limit/goal/debt models, CRUD handlers, and reads.
10. Import flow: file parser creates/reuses accounts and inserts non-duplicate transactions.
11. `analytics-service` regular payment CRUD, regular expense detection, expected income/expense, available funds.
12. `health-score-service` metric engine, snapshots, profile/score endpoints; consumes finance (including `debts.list`) + analytics via RabbitMQ only.
13. `scheduler-service` reminder and limit-warning planning.
14. `notification-service` device storage and Firebase test/send path.
15. `group-service` family CRUD, invitations, members, family budget assembly.
16. `chat-service` recommendations, chats, messages; uses `health.profile.get` for agent context.
17. Integration tests for RabbitMQ request-reply, import happy path, and health profile calculation.

## Decisions Log

### RabbitMQ-only internal task communication

- Chosen: all project-internal business communication goes through RabbitMQ task/message queues.
- Rejected: internal service-to-service HTTP endpoints.
- Reason: user explicitly selected RabbitMQ-task-only service communication.
- Trade-off: request-reply, timeouts, correlation ids, retries, and dead-letter queues become required MVP infrastructure concerns.

### Rename auth-service to access-service

- Chosen: `access-service` owns registration, login/logout, refresh, me, password change, and token verification.
- Rejected: old `auth-service` name.
- Reason: current service map uses access-service.
- Trade-off: all older docs and message names must use access/access-auth consistently.

### Split bucket bootstrap from migrations

- Chosen: `migration-service` owns PostgreSQL migrations only; `create-bucket-service` owns MinIO buckets.
- Rejected: one migration service doing all bootstrap.
- Reason: user explicitly separated migration and bucket bootstrap responsibilities.
- Trade-off: startup sequencing has one more one-shot service.

### Alembic instead of numbered raw SQL

- Chosen: Alembic revision chain under `migration-service`, tracked in `alembic_version`; SQLAlchemy models across services feed `target_metadata` for autogenerate.
- Rejected: continuing to add hand-sorted `NNN_service.sql` files and custom `schema_migrations` runner indefinitely.
- Reason: schema drift between ORM models and SQL files already appears in audits; Alembic gives revision history, downgrade path for dev, and autogenerate aligned with SQLAlchemy 2.x already in stack.
- Trade-off: one-time baseline squash and bridge from legacy SQL; developers must review autogenerate output; tables without ORM models need manual revision steps until models exist.

### File-service writes imported finance data

- Chosen: file-service creates/reuses accounts and inserts new imported transactions during parsing.
- Rejected: file-service only storing files and delegating all finance writes.
- Reason: user explicitly assigned import data persistence to file-service.
- Trade-off: finance tables must have clear idempotency rules so file import and finance-service CRUD do not conflict.

### Health-score-service boundary

- Chosen: dedicated `health-score-service` owns all financial/credit health formulas and agent-ready metric profiles.
- Rejected: pushing score calculation into `analytics-service` (different responsibility: forecasting/detection) or `chat-service` (LLM orchestration only).
- Reason: formulas doc defines a stable metrics contract for UI and multiple AI agents; single calculator avoids duplication between chat, dashboard, and external Context Builder.
- Trade-off: service orchestrates many RabbitMQ reads per profile; snapshots + Redis cache required for acceptable latency.
- Data constraint: when `user_debts` is empty, credit metrics fall back to transaction-category proxy; partial index is explicit in API responses via `credit_load_index_partial`.

### User debts in finance-service

- Chosen: `finance-service` owns `user_debts` table and CRUD (`GET/POST/PATCH/DELETE /api/v1/debts`).
- Rejected: placing debts in `analytics-service` (forecast inputs) or `access-service` (profile fields only).
- Reason: debts are durable finance obligations with balances and payment schedules; they feed credit-load formulas (`monthly_credit_payments`, `credit_card_utilization`, `overdue_days`) and AI Context Builder fields (`hasDebt`, `debtAmount`, `monthlyDebtPayment`) defined in `docs/Формулы_финансового_здоровья_и_ИИ_агенты.md` and `docs/ai-integration-samples/user_context.sample.json`.
- Trade-off: users must maintain debt records manually for full credit metrics; transaction-category proxy remains fallback when debts are absent.

### Manual regular payments in analytics-service

- Chosen: `analytics-service` owns CRUD for regular payment records in addition to automatic regular expense detection.
- Rejected: placing manual subscriptions/rent CRUD in `finance-service`.
- Reason: these records are analysis/forecast inputs used for available-funds calculation, reminders, health scoring, and recommendations; they are not raw transactions.
- Trade-off: `analytics-service` must clearly distinguish detected records from user-created or user-edited records.

## Proposals Not Yet Applied

Potential endpoint additions beyond the approved list (including debts CRUD above) should be approved explicitly before they are moved into `Public API Draft`.

Still open:

- unified `GET /api/v1/users/me/financial-context` aggregation endpoint (see `docs/ai-context-builder-backend-integration.md`);
- service-to-service auth for AI Context Builder;
- `category_profiles` taxonomy table.

Implementation backlog (approved in plan, not yet in code):

- Alembic cutover per [Database Migrations (Alembic)](#database-migrations-alembic);
- `user_debts` CRUD per finance-service section.
