# Backend Architecture Levels
Date: 2026-05-30
Status: Draft
Source: `docs/backend-plan.md`

This document shows the current backend architecture after the service responsibility split.

## 1 Level: Public Boundary

```mermaid
flowchart LR
    user(("User"))
    frontend["Frontend"]
    gateway{"api-gateway-service<br/>public HTTP API"}
    rabbit[("RabbitMQ<br/>task/message queues")]

    user -->|"request"| frontend
    frontend -->|"HTTPS + JWT"| gateway
    gateway -->|"publish message"| rabbit
    rabbit -->|"reply/event"| gateway
    gateway -->|"HTTP response / job id"| frontend
    frontend -->|"response"| user

    classDef userNode fill:#111827,stroke:#60a5fa,color:#dbeafe,stroke-width:2px
    classDef gatewayNode fill:#111827,stroke:#e5e7eb,color:#f9fafb,stroke-width:2px
    classDef infraNode fill:#111827,stroke:#f59e0b,color:#fde68a,stroke-width:2px
    classDef frontendNode fill:#111827,stroke:#f87171,color:#fee2e2,stroke-width:2px
    class user userNode
    class gateway gatewayNode
    class rabbit infraNode
    class frontend frontendNode
```

Main idea:

- frontend talks only to `api-gateway-service`;
- `api-gateway-service` maps HTTP routes to RabbitMQ task messages;
- backend services do not expose business HTTP APIs;
- health/ready are technical probes only.

## 2 Level: Services And Infrastructure

```mermaid
flowchart LR
    subgraph public["Public API"]
        gateway{"api-gateway-service"}
    end

    subgraph bus["Message Bus"]
        rabbit[("RabbitMQ<br/>task queues + request-reply + events")]
    end

    subgraph services["Backend services"]
        access["access-service<br/>auth + profile"]
        file["file-service<br/>files + import"]
        finance["finance-service<br/>transactions + accounts + goals + limits + debts"]
        scheduler["scheduler-service<br/>reminders + limit warnings"]
        notification["notification-service<br/>Firebase push"]
        analytics["analytics-service<br/>regular payments + expected funds"]
        group["group-service<br/>family groups"]
        chat["chat-service<br/>agent chat + recommendations"]
    end

    subgraph startup["Startup jobs"]
        migration["migration-service<br/>Alembic PostgreSQL migrations"]
        buckets["create-bucket-service<br/>MinIO buckets"]
    end

    subgraph infra["Infrastructure"]
        pg[("PostgreSQL")]
        minio[("MinIO")]
        redis[("Redis optional cache/status")]
        firebase["Firebase"]
    end

    gateway --> rabbit
    rabbit --> access
    rabbit --> file
    rabbit --> finance
    rabbit --> scheduler
    rabbit --> notification
    rabbit --> analytics
    rabbit --> group
    rabbit --> chat
    access --> rabbit
    file --> rabbit
    finance --> rabbit
    scheduler --> rabbit
    notification --> rabbit
    analytics --> rabbit
    group --> rabbit
    chat --> rabbit

    access --> pg
    file --> pg
    file --> minio
    finance --> pg
    scheduler --> pg
    notification --> pg
    notification --> firebase
    analytics --> pg
    group --> pg
    chat --> pg
    chat -. optional .-> redis
    analytics -. optional .-> redis
    scheduler -. optional .-> redis

    migration --> pg
    buckets --> minio
    migration --> rabbit
    buckets --> rabbit

    classDef gatewayNode fill:#111827,stroke:#e5e7eb,color:#f9fafb,stroke-width:2px
    classDef serviceNode fill:#111827,stroke:#f87171,color:#fee2e2,stroke-width:2px
    classDef infraNode fill:#111827,stroke:#f59e0b,color:#fde68a,stroke-width:2px
    classDef jobNode fill:#111827,stroke:#a78bfa,color:#ede9fe,stroke-width:2px
    class gateway gatewayNode
    class access,file,finance,scheduler,notification,analytics,group,chat serviceNode
    class rabbit,pg,minio,redis,firebase infraNode
    class migration,buckets jobNode
```

## Service Responsibilities

| Component | Responsibility |
|-----------|----------------|
| `api-gateway-service` | public HTTP API, creates RabbitMQ task messages, waits for replies, returns public responses |
| `access-service` | registration, login, logout, refresh, me, profile patch, password change, JWT verification |
| `migration-service` | Alembic schema migrations at startup; optional dev data bootstrap |
| `create-bucket-service` | MinIO bucket creation at startup |
| `file-service` | uploaded files, MinIO storage, parsing source spreadsheets, import jobs/errors, import-origin account/transaction writes |
| `finance-service` | transactions list, accounts list, goals, limits, categories, debts, finance reads/writes |
| `scheduler-service` | reminders for expected charges and limit warnings |
| `notification-service` | device ids, notification permission/preference state, Firebase push, test notification |
| `analytics-service` | regular payment CRUD, regular cost detection, expected incomes, expected expenses, available balance for period |
| `group-service` | family groups, members, invitations, accept/decline, family budget assembly |
| `chat-service` | agent recommendations, chat list, chat history, chat messages |

## RabbitMQ Interaction Matrix

| Flow | Publisher | Consumer | Pattern | Message |
|------|-----------|----------|---------|---------|
| Register/login/logout/refresh/me | `api-gateway-service` | `access-service` | request-reply | `auth.*`, `auth.me.*` |
| Token verification | `api-gateway-service` | `access-service` | request-reply | `auth.verify_token` |
| File upload and CRUD | `api-gateway-service` | `file-service` | request-reply | `files.*`, `imports.*` |
| File import worker | `file-service` | `file-service` worker | background task | `files.import.run` |
| Create/reuse account during import | `file-service` | `finance-service` | request-reply | `accounts.resolve_by_card` |
| Save imported transactions | `file-service` | `finance-service` | request-reply | `transactions.bulk_create` |
| Transactions list | `api-gateway-service` | `finance-service` | request-reply | `transactions.list` |
| Accounts list | `api-gateway-service` | `finance-service` | request-reply | `accounts.list` |
| Goals CRUD | `api-gateway-service` | `finance-service` | request-reply | `goals.*` |
| Limits CRUD | `api-gateway-service` | `finance-service` | request-reply | `limits.*` |
| Categories CRUD | `api-gateway-service` | `finance-service` | request-reply | `categories.*` |
| Debts CRUD | `api-gateway-service` | `finance-service` | request-reply | `debts.*` |
| Reminder planning | `scheduler-service` | `finance-service` / `analytics-service` | request-reply | finance/analytics queries |
| Notification delivery | `scheduler-service` | `notification-service` | background task | `notifications.send` |
| Notification devices/test | `api-gateway-service` | `notification-service` | request-reply | `notifications.*` |
| Regular payments CRUD | `api-gateway-service` | `analytics-service` | request-reply | `analytics.regular_expenses.*` |
| Analytics reads | `api-gateway-service` | `analytics-service` | request-reply | `analytics.*` |
| Family budget | `group-service` | `analytics-service` | request-reply | `analytics.member_budget.get` |
| Group CRUD/invitations | `api-gateway-service` | `group-service` | request-reply | `groups.*`, `group_invitations.*` |
| Chat/recommendations | `api-gateway-service` | `chat-service` | request-reply | `chats.*`, `chat_messages.*`, `chat.recommendations.initial.get` |

## Message Context

Every RabbitMQ task/message uses a common envelope:

```json
{
  "message_id": "uuid",
  "correlation_id": "uuid",
  "type": "transactions.list",
  "source": "api-gateway-service",
  "reply_to": "reply.api-gateway-service.uuid",
  "created_at": "2026-05-30T12:00:00Z",
  "user": {
    "id": "uuid",
    "email": "user@example.com"
  },
  "payload": {}
}
```

Rules:

- `user.id` appears only after `access-service` verifies JWT;
- services validate required metadata before work;
- request-reply task messages must use timeout handling;
- consumers must be idempotent because messages can be redelivered;
- failed background tasks go to retry/dead-letter queues.

## 3 Level: Main Runtime Flows

### Authenticated Read

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant GW as api-gateway-service
    participant MQ as RabbitMQ
    participant AS as access-service
    participant FS as finance-service

    FE->>GW: GET /api/v1/transactions + JWT
    GW->>MQ: auth.verify_token
    MQ->>AS: auth.verify_token
    AS->>MQ: auth.verify_token.reply(user)
    MQ->>GW: auth.verify_token.reply(user)
    GW->>MQ: transactions.list(user, filters)
    MQ->>FS: transactions.list
    FS->>MQ: transactions.list.reply(page)
    MQ->>GW: transactions.list.reply(page)
    GW->>FE: HTTP 200
```

### File Import

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant GW as api-gateway-service
    participant MQ as RabbitMQ
    participant AS as access-service
    participant File as file-service
    participant Finance as finance-service
    participant DB as PostgreSQL
    participant S3 as MinIO

    FE->>GW: POST /api/v1/files + JWT + Excel
    GW->>MQ: auth.verify_token
    MQ->>AS: auth.verify_token
    AS->>MQ: auth.verify_token.reply(user)
    MQ->>GW: auth.verify_token.reply(user)
    GW->>MQ: files.upload.create(user, file)
    MQ->>File: files.upload.create
    File->>S3: store original file
    File->>DB: create uploaded_file + import_job
    File->>MQ: files.import.run(import_id)
    File->>MQ: files.upload.create.reply(import_id)
    MQ->>GW: files.upload.create.reply(import_id)
    GW->>FE: HTTP 202 import_id
    MQ->>File: files.import.run
    File->>MQ: accounts.resolve_by_card
    MQ->>Finance: accounts.resolve_by_card
    Finance->>DB: find/create account
    Finance->>MQ: accounts.resolve_by_card.reply(account_id)
    MQ->>File: accounts.resolve_by_card.reply(account_id)
    File->>MQ: transactions.bulk_create
    MQ->>Finance: transactions.bulk_create
    Finance->>DB: insert non-duplicate transactions
    Finance->>MQ: transactions.bulk_create.reply
    File->>MQ: files.import.completed.v1
```

### Family Budget

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant GW as api-gateway-service
    participant MQ as RabbitMQ
    participant Group as group-service
    participant Analytics as analytics-service

    FE->>GW: GET /api/v1/groups/{id}/budget
    GW->>MQ: groups.family_budget.get
    MQ->>Group: groups.family_budget.get
    Group->>MQ: analytics.member_budget.get for each member
    MQ->>Analytics: analytics.member_budget.get
    Analytics->>MQ: analytics.member_budget.get.reply
    MQ->>Group: analytics replies
    Group->>MQ: groups.family_budget.get.reply
    MQ->>GW: groups.family_budget.get.reply
    GW->>FE: HTTP 200
```

## Health And Ready

Every service exposes:

```text
GET /health
GET /ready
```

These are technical probes only and are not used for business communication.

## Related Documents

- `docs/backend-plan.md`
- `docs/backend-er-diagram.md`
