# Family Budget Backend

Микросервисный backend для импорта семейного бюджета из Excel (`family-bugget.xlsx`), нормализации транзакций и MVP API для личных и семейных финансов.

Публичный HTTP доступен **только** через `api-gateway` (`:8080`). Внутренние сервисы общаются через **RabbitMQ** (request-reply и фоновые задачи).

## Визуальные материалы (заглушки)

Перед релизом замените SVG-заглушки на финальные PNG/SVG в `docs/images/`.

| Заглушка | Что должно быть на финальной картинке |
|----------|--------------------------------------|
| [Архитектура](docs/images/placeholder-architecture.svg) | Frontend → Gateway → RabbitMQ → бизнес-сервисы, PostgreSQL, MinIO |
| [Импорт Excel](docs/images/placeholder-import-flow.svg) | Цепочка upload → MinIO → parse → `transactions.bulk_create` |
| [Структура репо](docs/images/placeholder-repo-structure.svg) | Каталоги `services/`, `libs/common`, `docs/`, `tests/` |

![Заглушка: архитектура](docs/images/placeholder-architecture.svg)

![Заглушка: импорт](docs/images/placeholder-import-flow.svg)

![Заглушка: структура](docs/images/placeholder-repo-structure.svg)

## Документация

| Документ | Содержание |
|----------|------------|
| [docs/backend-plan.md](docs/backend-plan.md) | Контракты API, очереди, ответственность сервисов |
| [docs/backend-er-diagram.md](docs/backend-er-diagram.md) | Схема PostgreSQL |
| [docs/backend-architecture-levels.md](docs/backend-architecture-levels.md) | Границы слоёв и потоки |
| [docs/audit-report.md](docs/audit-report.md) | Полный аудит код ↔ docs |
| [docs/production-backlog.md](docs/production-backlog.md) | Открытые production-задачи и расхождения |

## Сервисы

| Сервис | Порт (compose) | Назначение |
|--------|----------------|------------|
| `gateway` | 8080 | Публичный REST `/api/v1/*` → RabbitMQ |
| `access-service` | — | Регистрация, JWT, refresh, `auth.verify_token` |
| `file-service` | — | Загрузка Excel, MinIO, import jobs, парсер |
| `finance-service` | — | Счета, транзакции, цели, лимиты, категории |
| `analytics-service` | — | Доступный баланс, ожидаемые доходы/расходы |
| `notification-service` | — | Push-настройки и доставка (Firebase опционально) |
| `group-service` | — | Семейные группы, приглашения, бюджет группы |
| `chat-service` | — | Чаты и рекомендации ассистента |
| `scheduler-service` | — | Напоминания и предупреждения по лимитам |
| `migration-service` | — | One-shot SQL-миграции |
| `create-bucket-service` | — | One-shot bootstrap MinIO |

Инфраструктура: PostgreSQL, MinIO, RabbitMQ, Redis.

## Структура кода (после рефакторинга)

```
services/gateway/app/
  main.py           # сборка FastAPI-приложения
  routers/          # HTTP-маршруты по доменам (auth, files, …)
  rpc.py            # HTTP → RabbitMQ request-reply
  dependencies.py   # JWT через access-service

services/<name>/app/
  main.py           # health/ready + запуск worker
  handlers.py       # обработчики RabbitMQ (access, file, finance)
```

Общая библиотека: `libs/common` (`messaging`, `security`, …).

## Требования

- Python **3.12+** (как в Docker-образе `python:3.12-slim`)
- Docker и Docker Compose — для полного стека

> На Windows команда `python` часто указывает на **3.10**. Используйте `py -3.12` или скрипт ниже — иначе `pip install` и `datetime.UTC` не сработают.

## Зависимости (pyproject.toml)

Единственный источник зависимостей — корневой [`pyproject.toml`](pyproject.toml). Файл `requirements.txt` не используется.

**Рекомендуемая настройка (Windows, Python 3.12):**

```powershell
.\scripts\setup-dev.ps1
.\.venv\Scripts\Activate.ps1
pytest
```

Вручную:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

Существующий `.venv-tests` (3.12) тоже подходит: активируйте его перед `pytest`.

## Запуск (Docker)

```powershell
copy infra\.env.example infra\.env
docker compose up --build
```

Проверка gateway:

```http
GET http://localhost:8080/api/v1/health
```

OpenAPI (локально): `http://localhost:8080/docs`

### Happy path

1. `POST /api/v1/auth/register` — тело `{ "email", "password", "display_name" }`
2. `POST /api/v1/auth/login` — получить `access_token`
3. `POST /api/v1/files` — multipart, поле `file` (`.xlsx`), заголовок `Authorization: Bearer <token>`
4. `GET /api/v1/imports/{import_id}` — статус импорта
5. `GET /api/v1/transactions?page=1&page_size=50` — транзакции

## Тесты

```powershell
pip install -e ".[dev]"
pytest
```

Интеграционный smoke (нужен поднятый Docker-стек):

```powershell
$env:RUN_DOCKER_SMOKE = "1"
pytest tests/test_integration_rabbitmq_import.py
```

## Конфигурация

Шаблон переменных: [infra/.env.example](infra/.env.example).  
В compose используется anchor `x-app-env` в [docker-compose.yml](docker-compose.yml).

Обязательно смените `JWT_SECRET` вне dev-окружения.

## Лицензия / статус

Hackathon MVP — см. [docs/production-backlog.md](docs/production-backlog.md) перед production-деплоем.
