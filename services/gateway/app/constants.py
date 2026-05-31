from __future__ import annotations

from services.gateway.app.schemas import ErrorResponse

ACCESS_QUEUE = "access-service"
FILE_QUEUE = "file-service"
FINANCE_QUEUE = "finance-service"
NOTIFICATION_QUEUE = "notification-service"
ANALYTICS_QUEUE = "analytics-service"
GROUP_QUEUE = "group-service"
CHAT_QUEUE = "chat-service"
HEALTH_SCORE_QUEUE = "health-score-service"

PROTECTED_RESPONSES = {
    401: {"model": ErrorResponse, "description": "Отсутствует, просрочен или недействителен Bearer JWT."},
    502: {"model": ErrorResponse, "description": "Сбой внутренней шины сообщений или downstream-сервиса."},
    504: {"model": ErrorResponse, "description": "Таймаут ожидания ответа от внутреннего сервиса."},
}

PUBLIC_RESPONSES = {
    409: {"model": ErrorResponse, "description": "Конфликт данных, например email уже зарегистрирован."},
    422: {"model": ErrorResponse, "description": "Ошибка валидации тела или параметров запроса."},
    502: {"model": ErrorResponse, "description": "Сбой внутренней шины сообщений или downstream-сервиса."},
    504: {"model": ErrorResponse, "description": "Таймаут ожидания ответа от внутреннего сервиса."},
}

OPENAPI_TAGS = [
    {"name": "System", "description": "Живость и готовность API gateway для оркестратора и балансировщика."},
    {"name": "Auth", "description": "Регистрация, вход, обновление токенов, профиль и смена пароля."},
    {"name": "Files", "description": "Загрузка Excel-исходников и метаданные файлов в object storage."},
    {"name": "Imports", "description": "Статус фонового импорта и ошибки разбора строк."},
    {"name": "Transactions", "description": "Чтение нормализованных транзакций с фильтрами и пагинацией."},
    {"name": "Accounts", "description": "Финансовые счета пользователя (только список через публичный API)."},
    {"name": "Goals", "description": "Цели накопления: создание, просмотр, изменение и удаление."},
    {"name": "Debts", "description": "User debts and credit obligations with CRUD, filters, and debt data for financial health scoring."},
    {"name": "Limits", "description": "Лимиты расходов по категориям и периодам."},
    {"name": "Categories", "description": "Пользовательские категории доходов и расходов."},
    {"name": "Notifications", "description": "Согласие на push, регистрация устройств FCM и тестовая отправка."},
    {"name": "Analytics", "description": "Доступный остаток, ожидаемые доходы и расходы на период."},
    {"name": "Financial Health", "description": "Financial health and credit-load profile calculated from finance and analytics service data."},
    {"name": "Groups", "description": "Семейные группы, участники, приглашения и сводный бюджет."},
    {"name": "Chats", "description": "Рекомендации агентов, чаты и сообщения с ролями user/assistant/system."},
]
