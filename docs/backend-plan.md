# Backend Plan
Date: 2026-05-30
Status: Draft
Scope: backend MVP for fintech hackathon

## Context

The project is an MVP for personal and family finance analysis and management.

The exact hackathon case is still flexible, so the backend must keep service boundaries explicit and easy to revise.

Core approved stack:

- Python + FastAPI for service runtimes;
- SQLAlchemy for DB access;
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

One-shot startup service for PostgreSQL migrations.

Responsibilities:

- waits for PostgreSQL;
- runs migrations in deterministic order;
- records applied migrations;
- exits with `0` on success;
- exits non-zero if app services must not start.

Does not own:

- MinIO bucket creation;
- public API;
- business runtime.

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
- public API.

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

### 6. finance-service

User-facing finance data service.

Approved public endpoints through gateway:

- `GET /api/v1/transactions` with pagination and filters;
- `GET /api/v1/accounts`;
- CRUD for savings goals;
- CRUD for account limits;
- CRUD for user categories.

Responsibilities:

- returns current transactions with pagination and filters;
- returns accounts;
- manages accounts for user-facing finance operations;
- manages transactions for user-facing finance operations;
- manages savings goals;
- manages limits by account/category;
- manages custom categories;
- calculates current account values needed by finance screens;
- answers RabbitMQ queries from analytics/group/scheduler when they need scoped finance data.

Owns user-facing finance read/write behavior for:

- `accounts`;
- `transactions`;
- `account_categories`;
- `category_limits`;
- `savings_goals`.

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

- `GET /api/v1/analytics/available-balance`;
- `GET /api/v1/analytics/expected-incomes`;
- `GET /api/v1/analytics/expected-expenses`.

Responsibilities:

- detects regular user expenses;
- estimates user income;
- calculates available funds for a period after regular expenses;
- excludes irregular and impulsive purchases from available-funds estimate;
- stores or caches analysis results needed by recommendations;
- provides per-user analytics for direct display;
- provides per-user analytics to `group-service` for family budget assembly.

Owns data:

- regular expense detections;
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
- uses analytics/finance context through RabbitMQ messages when needed;
- keeps chat history separate from source finance data.

Owns data:

- `chats`;
- `chat_messages`;
- `agent_recommendations`.

## Health And Readiness

Every service exposes technical probe endpoints:

- `GET /health` - process is alive;
- `GET /ready` - service can do useful work.

Readiness examples:

- `api-gateway-service`: RabbitMQ reachable;
- `access-service`: PostgreSQL and RabbitMQ reachable;
- `migration-service`: migrations completed successfully;
- `create-bucket-service`: buckets exist;
- file/finance/group/chat/analytics/scheduler/notification services: own DB dependencies and RabbitMQ reachable;
- `notification-service`: Firebase config present and RabbitMQ reachable.

These probes are not business communication between services.

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
- `categories.*`.

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
- `analytics.expected_incomes.list`;
- `analytics.expected_expenses.list`;
- `analytics.available_balance.get`;
- `analytics.member_budget.get`.

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
```

### Notifications

```text
POST /api/v1/notifications/permission
POST /api/v1/notifications/devices
POST /api/v1/notifications/test
```

### Analytics

```text
GET /api/v1/analytics/available-balance
GET /api/v1/analytics/expected-incomes
GET /api/v1/analytics/expected-expenses
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
| accounts, transactions, goals, limits, categories | finance-service |
| reminder plans and warning schedules | scheduler-service |
| devices, notification preferences, delivery log | notification-service |
| regular expenses, expected income/expense, available funds | analytics-service |
| family groups, members, invitations | group-service |
| chats, messages, agent recommendations | chat-service |
| schema migrations | migration-service |
| MinIO bucket bootstrap state | create-bucket-service |

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
- Imported files, imports, transactions, accounts, goals, limits, categories, analytics, groups, notifications, and chats are user-scoped.
- Family/group access is handled by `group-service` plus finance/analytics checks through RabbitMQ.
- Descriptions from source files are stored as-is for MVP.
- Upload has no product-level max size for MVP, but invalid/corrupt/unsupported workbooks are rejected.
- Simple dashboard sums can stay frontend-side unless explicitly owned by analytics/finance endpoint.

## MVP Build Order

1. Docker Compose with PostgreSQL, MinIO, RabbitMQ, Redis.
2. `migration-service` for PostgreSQL migrations.
3. `create-bucket-service` for MinIO buckets.
4. Shared RabbitMQ message envelope library.
5. `access-service` register/login/refresh/logout/me/change-password plus `auth.verify_token`.
6. `api-gateway-service` route-to-message mapping and request-reply support.
7. `file-service` upload metadata, MinIO storage, import jobs, parser.
8. `finance-service` account/transaction/category/limit/goal models and reads.
9. Import flow: file parser creates/reuses accounts and inserts non-duplicate transactions.
10. `analytics-service` regular expenses, expected income/expense, available funds.
11. `scheduler-service` reminder and limit-warning planning.
12. `notification-service` device storage and Firebase test/send path.
13. `group-service` family CRUD, invitations, members, family budget assembly.
14. `chat-service` recommendations, chats, messages.
15. Integration tests for RabbitMQ request-reply and import happy path.

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

### File-service writes imported finance data

- Chosen: file-service creates/reuses accounts and inserts new imported transactions during parsing.
- Rejected: file-service only storing files and delegating all finance writes.
- Reason: user explicitly assigned import data persistence to file-service.
- Trade-off: finance tables must have clear idempotency rules so file import and finance-service CRUD do not conflict.

## Proposals Not Yet Applied

No additional endpoints beyond the user's list are accepted in this plan yet.

Potential endpoint additions should be approved explicitly before they are moved into `Public API Draft`.
