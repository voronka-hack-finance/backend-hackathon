# Family Budget Backend

Микросервисный FastAPI backend для импорта `family-bugget.xlsx` и семейного финансового MVP.

Документация: [docs/backend-plan.md](docs/backend-plan.md), [docs/backend-er-diagram.md](docs/backend-er-diagram.md), [docs/backend-architecture-levels.md](docs/backend-architecture-levels.md).

## Сервисы

| Сервис | Назначение |
|--------|------------|
| `gateway` | Публичный HTTP API на `http://localhost:8080/api/v1` |
| `access-service` | Регистрация, login, refresh, JWT verify |
| `migration-service` | One-shot миграции PostgreSQL |
| `create-bucket-service` | One-shot bootstrap MinIO buckets |
| `file-service` | Загрузка Excel, MinIO, import jobs, парсер |
| `finance-service` | Accounts, transactions, goals, limits, categories |
| `analytics-service` | Available balance, expected incomes/expenses |
| `scheduler-service` | Reminders и limit warnings |
| `notification-service` | Push permission, devices, Firebase delivery |
| `group-service` | Family groups, members, invitations, budget |
| `chat-service` | Agent recommendations, chats, messages |

## Запуск

```powershell
docker compose up --build
```

Публичный healthcheck:

```text
GET http://localhost:8080/api/v1/health
```

Первый happy path:

1. `POST /api/v1/auth/register`
2. `POST /api/v1/auth/login`
3. `POST /api/v1/files` с multipart field `file`
4. `GET /api/v1/imports/{import_id}`
5. `GET /api/v1/transactions?page=1&page_size=50`

## Тесты

```powershell
pip install -e ".[dev]"
pytest
```
