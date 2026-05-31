from __future__ import annotations

import hashlib
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from minio import Minio
from sqlalchemy import Engine, text

from services.access_service.app.security import hash_password
from services.file_service.app.imports.parsers.family_budget_excel_v1 import (
    SOURCE_TYPE,
    FamilyBudgetExcelParser,
)
from services.file_service.app.storage.client import ObjectStorage
from services.finance_service.app.handlers import (
    handle_accounts_resolve_by_card,
    handle_accounts_update,
    handle_transactions_bulk_create,
)
from services.migration_service.app.config import settings

logger = logging.getLogger(__name__)

SCRIPT_KEY = "family-budget-excel"
SCRIPT_GROUP = "data-bootstrap"
CHUNK_SIZE = 500
CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SBER_BANK_SOURCE = "СБЕР"
SBER_DEMO_CARD_LAST4 = "8336"
SBER_DEMO_CARD_MASK = "*8336"
SBER_DEMO_DISPLAY_NAME = "Сбер ••8336"
SBER_DEMO_LIVE_SHEET = "СБЕР_live"
DEMO_CHATS_BASE_AT = datetime(2026, 5, 15, 9, 0, tzinfo=UTC)

_parser = FamilyBudgetExcelParser()


def run_bootstrap(engine: Engine) -> None:
    if not settings.bootstrap_excel_enabled:
        logger.info("Excel bootstrap disabled (BOOTSTRAP_EXCEL_ENABLED=false)")
        return

    path = Path(settings.bootstrap_excel_path)
    if not path.is_file():
        logger.warning("Excel bootstrap skipped: file not found at %s", path)
        return

    file_bytes = path.read_bytes()
    checksum = hashlib.sha256(file_bytes).hexdigest()
    _record_bootstrap(engine, checksum, status="running", error_message=None)
    try:
        inserted = _import_workbook(engine, path, file_bytes)
        _record_bootstrap(engine, checksum, status="completed", error_message=None)
        logger.info(
            "Excel bootstrap completed for %s: %s transactions inserted",
            settings.bootstrap_user_email,
            inserted,
        )
    except Exception as exc:
        _record_bootstrap(engine, checksum, status="failed", error_message=str(exc))
        logger.exception("Excel bootstrap failed")
        raise


def _record_bootstrap(engine: Engine, checksum: str, *, status: str, error_message: str | None) -> None:
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into bootstrap_runs(script_key, script_group, checksum, status, started_at, finished_at, error_message)
                values (:script_key, :script_group, :checksum, :status, :started_at, :finished_at, :error_message)
                on conflict (script_key) do update set
                  script_group = excluded.script_group,
                  checksum = excluded.checksum,
                  status = excluded.status,
                  started_at = case when excluded.status = 'running' then excluded.started_at else bootstrap_runs.started_at end,
                  finished_at = excluded.finished_at,
                  error_message = excluded.error_message
                """
            ),
            {
                "script_key": SCRIPT_KEY,
                "script_group": SCRIPT_GROUP,
                "checksum": checksum,
                "status": status,
                "started_at": now if status == "running" else None,
                "finished_at": now if status in {"completed", "failed"} else None,
                "error_message": error_message,
            },
        )


def _import_workbook(engine: Engine, path: Path, file_bytes: bytes) -> int:
    user_id = _create_bootstrap_user(engine)
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

    _wait_for_minio()
    storage = ObjectStorage()
    filename = path.name
    storage_key = f"{user_id}/{file_sha256}/{filename}"
    storage.put_bytes(storage_key, file_bytes, CONTENT_TYPE)

    file_id, import_id = _create_file_and_import(engine, user_id, filename, file_sha256, storage_key, len(file_bytes))

    result = _parser.parse(file_bytes)
    if result.errors and not result.transactions:
        first = result.errors[0]
        raise RuntimeError(first.message or first.error_code or "Excel parse failed")

    envelope = {"user": {"id": str(user_id), "email": settings.bootstrap_user_email}}
    inserted = 0
    for chunk in _chunks(result.transactions, CHUNK_SIZE):
        payload = {
            "items": [
                transaction.to_bulk_item(import_id=str(import_id), source_file_id=str(file_id))
                for transaction in chunk
            ]
        }
        reply = handle_transactions_bulk_create(payload, envelope)
        inserted += int(reply.get("inserted", 0))

    _finalize_import(engine, import_id, file_id, result, inserted)
    demo_inserted = _seed_sber_demo_account(
        user_id=user_id,
        envelope=envelope,
        file_id=file_id,
        import_id=import_id,
    )
    _seed_demo_chats(engine, user_id)
    return inserted + demo_inserted


def _seed_sber_demo_account(
    *,
    user_id: UUID,
    envelope: dict,
    file_id: UUID,
    import_id: UUID,
) -> int:
    account = _ensure_sber_demo_account(envelope)
    items = build_sber_demo_transactions(
        account_id=UUID(str(account["id"])),
        import_id=import_id,
        source_file_id=file_id,
    )
    reply = handle_transactions_bulk_create({"items": items}, envelope)
    inserted = int(reply.get("inserted", 0))
    logger.info(
        "SBER demo account %s seeded with %s live transactions for user %s",
        account["id"],
        inserted,
        user_id,
    )
    return inserted


def _ensure_sber_demo_account(envelope: dict) -> dict:
    account = handle_accounts_resolve_by_card(
        {
            "card_last4": SBER_DEMO_CARD_LAST4,
            "card_mask": SBER_DEMO_CARD_MASK,
            "display_name": SBER_DEMO_DISPLAY_NAME,
            "bank_source": SBER_BANK_SOURCE,
            "currency": "RUB",
            "account_type": "card",
        },
        envelope,
    )
    if account.get("bank_source") != SBER_BANK_SOURCE or account.get("display_name") != SBER_DEMO_DISPLAY_NAME:
        account = handle_accounts_update(
            {
                "account_id": account["id"],
                "bank_source": SBER_BANK_SOURCE,
                "display_name": SBER_DEMO_DISPLAY_NAME,
            },
            envelope,
        )
    return account


def build_demo_chat_mocks() -> list[dict[str, Any]]:
    return [
        {
            "title": "Расходы на еду",
            "agent_key": "expense-analysis",
            "confidence": "0.8600",
            "base_offset_days": 0,
            "messages": [
                {
                    "role": "user",
                    "offset_minutes": 0,
                    "content": "Сколько я трачу на еду в месяц? Кажется, слишком много.",
                },
                {
                    "role": "assistant",
                    "offset_minutes": 2,
                    "content": (
                        "За последние 30 дней расходы на продукты и питание вне дома — около 18 400 ₽. "
                        "Супермаркеты (Пятёрочка и др.) — 11 200 ₽, доставка и кафе — 7 200 ₽. "
                        "Это примерно 22% от вашего дохода 85 000 ₽ — в пределах нормы, "
                        "но доставка выросла на 15% к прошлому месяцу."
                    ),
                },
                {
                    "role": "user",
                    "offset_minutes": 5,
                    "content": "А если убрать доставку и кафе?",
                },
                {
                    "role": "assistant",
                    "offset_minutes": 7,
                    "content": (
                        "Без доставки и кафе расходы на еду снизятся примерно до 11 200 ₽ в месяц — "
                        "экономия около 7 200 ₽. Если направить половину в цель «Отпуск», "
                        "накопите дополнительные 3 600 ₽ ежемесячно."
                    ),
                },
            ],
        },
        {
            "title": "Цель «Отпуск»",
            "agent_key": "goals",
            "confidence": "0.9100",
            "base_offset_days": 2,
            "messages": [
                {
                    "role": "user",
                    "offset_minutes": 0,
                    "content": "Когда я смогу накопить на отпуск?",
                },
                {
                    "role": "assistant",
                    "offset_minutes": 2,
                    "content": (
                        "Цель «Отпуск» — 150 000 ₽, уже отложено 45 000 ₽ (30%). "
                        "При текущем темпе около 12 500 ₽ в месяц до цели останется примерно 8 месяцев. "
                        "Если откладывать 15 000 ₽ с каждой зарплаты, уложитесь к декабрю 2026 года."
                    ),
                },
            ],
        },
        {
            "title": "Бюджет на выходные",
            "agent_key": "available-funds",
            "confidence": "0.8800",
            "base_offset_days": 5,
            "messages": [
                {
                    "role": "user",
                    "offset_minutes": 0,
                    "content": "Сколько могу потратить в эти выходные, не залезая в цель?",
                },
                {
                    "role": "assistant",
                    "offset_minutes": 2,
                    "content": (
                        "Прогнозный баланс после обязательных расходов — около 14 800 ₽. "
                        "С учётом резерва на цель «Отпуск» рекомендую лимит 8 000–10 000 ₽ "
                        "на развлечения и спонтанные покупки до понедельника."
                    ),
                },
                {
                    "role": "user",
                    "offset_minutes": 4,
                    "content": "Ок, а если захочу сходить в кино и поужинать?",
                },
                {
                    "role": "assistant",
                    "offset_minutes": 6,
                    "content": (
                        "Кино на двоих и ужин вне дома обычно укладываются в 4 500–6 000 ₽. "
                        "Это комфортно укладывается в рекомендованный лимит, "
                        "если не планируете крупных покупок на маркетплейсах."
                    ),
                },
            ],
        },
        {
            "title": "Где сократить траты",
            "agent_key": "expense-optimization",
            "confidence": "0.8400",
            "base_offset_days": 8,
            "messages": [
                {
                    "role": "user",
                    "offset_minutes": 0,
                    "content": "Где можно сократить траты без особого дискомфорта?",
                },
                {
                    "role": "assistant",
                    "offset_minutes": 2,
                    "content": (
                        "Три зоны с быстрым эффектом: маркетплейсы (OZON около 4 200 ₽ в месяц) — "
                        "отложенные покупки; подписки Яндекс Плюс и музыка — 798 ₽; "
                        "такси в будни вместо метро — около 2 800 ₽. "
                        "Перенос 2–3 заказов и четырёх поездок на транспорт даст примерно 3 500 ₽ в месяц."
                    ),
                },
            ],
        },
        {
            "title": "Покупка ноутбука",
            "agent_key": "large-purchase",
            "confidence": "0.8200",
            "base_offset_days": 11,
            "messages": [
                {
                    "role": "user",
                    "offset_minutes": 0,
                    "content": "Хочу ноутбук за 95 000 ₽. Как лучше накопить?",
                },
                {
                    "role": "assistant",
                    "offset_minutes": 2,
                    "content": (
                        "При балансе около 52 000 ₽ и активной цели «Отпуск» одновременное накопление "
                        "на две крупные цели рискованно. Варианты: (1) отложить покупку на 3 месяца "
                        "и копить 20 000 ₽ в месяц с карты Сбер ••8336; (2) рассрочка 0% "
                        "с платежом около 15 800 ₽ в месяц — тогда сократите развлечения на 5 000 ₽. "
                        "Без рассрочки к концу августа наберёте сумму, не трогая цель отпуска, "
                        "если откладываете 18 000 ₽ ежемесячно."
                    ),
                },
                {
                    "role": "user",
                    "offset_minutes": 6,
                    "content": "Рассрочку не хочу. Сколько откладывать, чтобы не сдвинуть отпуск?",
                },
                {
                    "role": "assistant",
                    "offset_minutes": 8,
                    "content": (
                        "Чтобы купить ноутбук к концу августа и сохранить темп по «Отпуску», "
                        "откладывайте 18 000 ₽ в месяц: 12 500 ₽ на цель и 5 500 ₽ сверх текущего темпа "
                        "на ноутбук. После покупки вернитесь к прежнему взносу 12 500 ₽ — "
                        "срок отпуска сдвинется не более чем на 3 недели."
                    ),
                },
            ],
        },
    ]


def build_demo_recommendation_mocks() -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for spec in build_demo_chat_mocks():
        first_user_message = next(message for message in spec["messages"] if message["role"] == "user")
        recommendations.append(
            {
                "agent_key": spec["agent_key"],
                "title": spec["title"],
                "content": first_user_message["content"],
                "confidence": spec["confidence"],
            }
        )
    return recommendations


def _seed_demo_chats(engine: Engine, user_id: UUID) -> None:
    specs = build_demo_chat_mocks()
    message_count = 0
    recommendation_count = 0
    for spec in specs:
        chat_id = uuid4()
        chat_base = DEMO_CHATS_BASE_AT + timedelta(days=spec["base_offset_days"])
        timestamps = [
            chat_base + timedelta(minutes=message["offset_minutes"]) for message in spec["messages"]
        ]
        created_at = timestamps[0]
        updated_at = timestamps[-1]
        first_user_message = next(message for message in spec["messages"] if message["role"] == "user")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into chats(id, user_id, title, status, created_at, updated_at)
                    values (:id, :user_id, :title, 'active', :created_at, :updated_at)
                    """
                ),
                {
                    "id": chat_id,
                    "user_id": user_id,
                    "title": spec["title"],
                    "created_at": created_at,
                    "updated_at": updated_at,
                },
            )
            conn.execute(
                text(
                    """
                    insert into agent_recommendations(
                      user_id, chat_id, agent_key, title, content, confidence, created_at
                    )
                    values (:user_id, :chat_id, :agent_key, :title, :content, :confidence, :created_at)
                    """
                ),
                {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "agent_key": spec["agent_key"],
                    "title": spec["title"],
                    "content": first_user_message["content"],
                    "confidence": spec["confidence"],
                    "created_at": created_at,
                },
            )
            recommendation_count += 1
            for message, created_at in zip(spec["messages"], timestamps, strict=True):
                conn.execute(
                    text(
                        """
                        insert into chat_messages(chat_id, user_id, role, content, created_at)
                        values (:chat_id, :user_id, :role, :content, :created_at)
                        """
                    ),
                    {
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "role": message["role"],
                        "content": message["content"],
                        "created_at": created_at,
                    },
                )
                message_count += 1
    logger.info(
        "Demo chats seeded: %s chats, %s recommendations and %s messages for user %s",
        len(specs),
        recommendation_count,
        message_count,
        user_id,
    )


def build_sber_demo_transactions(
    *,
    account_id: UUID,
    import_id: UUID,
    source_file_id: UUID,
) -> list[dict[str, Any]]:
    specs = [
        {
            "row": 900_001,
            "type": "income",
            "operation_at": "2026-05-25T09:15:00+00:00",
            "payment_at": "2026-05-25T09:15:00+00:00",
            "operation_amount": "85000.00",
            "payment_amount": "85000.00",
            "cashback_amount": "0.00",
            "bonus_amount": "0.00",
            "investment_rounding_amount": "0.00",
            "rounded_operation_amount": "85000.00",
            "category_name": "Зарплата",
            "mcc": None,
            "description": "ООО «ТехноСофт»",
        },
        {
            "row": 900_002,
            "type": "expense",
            "operation_at": "2026-05-28T19:42:00+00:00",
            "payment_at": "2026-05-28T19:42:00+00:00",
            "operation_amount": "-2347.50",
            "payment_amount": "-2347.50",
            "cashback_amount": "23.48",
            "bonus_amount": "23.48",
            "investment_rounding_amount": "2.50",
            "rounded_operation_amount": "-2350.00",
            "category_name": "Супермаркеты",
            "mcc": "5411",
            "description": "Пятёрочка",
        },
        {
            "row": 900_003,
            "type": "expense",
            "operation_at": "2026-05-29T08:17:00+00:00",
            "payment_at": "2026-05-29T08:17:00+00:00",
            "operation_amount": "-456.00",
            "payment_amount": "-456.00",
            "cashback_amount": "4.56",
            "bonus_amount": "4.56",
            "investment_rounding_amount": "4.00",
            "rounded_operation_amount": "-460.00",
            "category_name": "Тaxi",
            "mcc": "4121",
            "description": "Яндекс Go",
        },
        {
            "row": 900_004,
            "type": "expense",
            "operation_at": "2026-05-30T14:03:00+00:00",
            "payment_at": "2026-05-30T14:03:00+00:00",
            "operation_amount": "-1890.00",
            "payment_amount": "-1890.00",
            "cashback_amount": "37.80",
            "bonus_amount": "37.80",
            "investment_rounding_amount": "10.00",
            "rounded_operation_amount": "-1900.00",
            "category_name": "Маркетплейсы",
            "mcc": "5399",
            "description": "OZON.RU",
        },
    ]
    items: list[dict[str, Any]] = []
    for spec in specs:
        raw_payload = {
            "Дата операции": spec["operation_at"].replace("+00:00", ""),
            "Дата платежа": spec["payment_at"].replace("+00:00", ""),
            "Номер карты": SBER_DEMO_CARD_MASK,
            "Статус": "OK",
            "Сумма операции": spec["operation_amount"],
            "Валюта операции": "RUB",
            "Сумма платежа": spec["payment_amount"],
            "Валюта платежа": "RUB",
            "Кэшбэк": spec["cashback_amount"],
            "Категория": spec["category_name"],
            "MCC": spec["mcc"] or "",
            "Описание": spec["description"],
            "Бонусы (включая кэшбэк)": spec["bonus_amount"],
            "Округление на инвесткопилку": spec["investment_rounding_amount"],
            "Сумма операции с округлением": spec["rounded_operation_amount"],
        }
        dedupe_key = hashlib.sha256(
            f"{SBER_DEMO_LIVE_SHEET}:{spec['row']}:{spec['description']}:{spec['operation_amount']}".encode()
        ).hexdigest()
        items.append(
            {
                "account_id": str(account_id),
                "import_id": str(import_id),
                "source_file_id": str(source_file_id),
                "source_sheet": SBER_DEMO_LIVE_SHEET,
                "source_row_number": spec["row"],
                "type": spec["type"],
                "operation_at": spec["operation_at"],
                "payment_at": spec["payment_at"],
                "card_mask": SBER_DEMO_CARD_MASK,
                "card_last4": SBER_DEMO_CARD_LAST4,
                "status": "OK",
                "operation_amount": spec["operation_amount"],
                "operation_currency": "RUB",
                "payment_amount": spec["payment_amount"],
                "payment_currency": "RUB",
                "cashback_amount": spec["cashback_amount"],
                "category_name": spec["category_name"],
                "mcc": spec["mcc"],
                "description": spec["description"],
                "bonus_amount": spec["bonus_amount"],
                "investment_rounding_amount": spec["investment_rounding_amount"],
                "rounded_operation_amount": spec["rounded_operation_amount"],
                "dedupe_key": dedupe_key,
                "raw_payload": raw_payload,
            }
        )
    return items


def _create_bootstrap_user(engine: Engine) -> UUID:
    user_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into users(id, email, password_hash, display_name, created_at, updated_at)
                values (:id, :email, :password_hash, :display_name, now(), now())
                """
            ),
            {
                "id": user_id,
                "email": settings.bootstrap_user_email,
                "password_hash": hash_password(settings.bootstrap_user_password),
                "display_name": settings.bootstrap_user_display_name,
            },
        )
    return user_id


def _create_file_and_import(
    engine: Engine,
    user_id: UUID,
    filename: str,
    sha256: str,
    storage_key: str,
    size_bytes: int,
) -> tuple[UUID, UUID]:
    file_id = uuid4()
    import_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into uploaded_files(
                  id, user_id, original_filename, content_type, size_bytes, sha256,
                  storage_bucket, storage_key, status, created_at, updated_at
                )
                values (
                  :id, :user_id, :filename, :content_type, :size_bytes, :sha256,
                  :bucket, :storage_key, 'uploaded', now(), now()
                )
                """
            ),
            {
                "id": file_id,
                "user_id": user_id,
                "filename": filename,
                "content_type": CONTENT_TYPE,
                "size_bytes": size_bytes,
                "sha256": sha256,
                "bucket": settings.uploads_bucket,
                "storage_key": storage_key,
            },
        )
        conn.execute(
            text(
                """
                insert into import_jobs(
                  id, user_id, file_id, source_type, status, total_rows, parsed_rows, failed_rows,
                  started_at, finished_at, error_message, created_at, updated_at
                )
                values (
                  :id, :user_id, :file_id, :source_type, 'running', 0, 0, 0,
                  now(), null, null, now(), now()
                )
                """
            ),
            {
                "id": import_id,
                "user_id": user_id,
                "file_id": file_id,
                "source_type": SOURCE_TYPE,
            },
        )
    return file_id, import_id


def _finalize_import(engine: Engine, import_id: UUID, file_id: UUID, result, inserted: int) -> None:
    if result.errors and result.transactions:
        job_status = "partially_completed"
        file_status = "parsed"
    elif result.errors:
        job_status = "failed"
        file_status = "failed"
    else:
        job_status = "completed"
        file_status = "parsed"
    error_message = result.errors[0].message if result.errors else None
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                update import_jobs
                set status = :status,
                    total_rows = :total_rows,
                    parsed_rows = :parsed_rows,
                    failed_rows = :failed_rows,
                    error_message = :error_message,
                    finished_at = now(),
                    updated_at = now()
                where id = :id
                """
            ),
            {
                "id": import_id,
                "status": job_status,
                "total_rows": result.total_rows,
                "parsed_rows": inserted,
                "failed_rows": result.failed_rows,
                "error_message": error_message,
            },
        )
        conn.execute(
            text("update uploaded_files set status = :status, updated_at = now() where id = :id"),
            {"id": file_id, "status": file_status},
        )


def _wait_for_minio() -> None:
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    deadline = time.monotonic() + 90
    while True:
        try:
            client.bucket_exists(settings.uploads_bucket)
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def _chunks(items, size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]
