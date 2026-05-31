from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
import uuid as uuid_stdlib
from uuid import UUID

IMPORT_CATEGORY_NAMESPACE = uuid_stdlib.UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")

from common.messaging import MessageError, require_user
from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from services.finance_service.app.db import SessionLocal
from services.finance_service.app.models import Account, AccountCategory, CategoryLimit, SavingsGoal, Transaction

DECIMAL_FIELDS = {
    "operation_amount",
    "payment_amount",
    "cashback_amount",
    "bonus_amount",
    "investment_rounding_amount",
    "rounded_operation_amount",
    "initial_balance",
    "limit_amount",
    "target_amount",
    "current_amount",
}
UUID_FIELDS = {"id", "user_id", "owner_user_id", "created_by_user_id", "account_id", "category_id", "family_group_id"}
DATETIME_FIELDS = {"operation_at", "payment_at", "period_started_at", "created_at", "updated_at"}
DATE_FIELDS = {"target_date"}

TRANSACTION_FIELDS = (
    "id",
    "user_id",
    "account_id",
    "category_id",
    "import_id",
    "source_file_id",
    "source_sheet",
    "source_row_number",
    "type",
    "operation_at",
    "payment_at",
    "card_mask",
    "card_last4",
    "status",
    "operation_amount",
    "operation_currency",
    "payment_amount",
    "payment_currency",
    "cashback_amount",
    "category_name",
    "mcc",
    "description",
    "bonus_amount",
    "investment_rounding_amount",
    "rounded_operation_amount",
    "dedupe_key",
    "raw_payload",
    "created_at",
    "updated_at",
)
ACCOUNT_FIELDS = (
    "id",
    "owner_user_id",
    "family_group_id",
    "bank_source",
    "display_name",
    "account_type",
    "currency",
    "card_last4",
    "initial_balance",
    "is_archived",
    "created_at",
    "updated_at",
)
CATEGORY_FIELDS = (
    "id",
    "account_id",
    "created_by_user_id",
    "name",
    "description",
    "icon_key",
    "is_archived",
    "created_at",
    "updated_at",
)
LIMIT_FIELDS = (
    "id",
    "account_id",
    "category_id",
    "owner_user_id",
    "limit_amount",
    "currency",
    "period_days",
    "period_started_at",
    "is_active",
    "created_at",
    "updated_at",
)
GOAL_FIELDS = (
    "id",
    "account_id",
    "owner_user_id",
    "title",
    "description",
    "target_amount",
    "current_amount",
    "currency",
    "target_date",
    "status",
    "created_at",
    "updated_at",
)


def handle_transactions_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    page, page_size = _page(payload)
    with SessionLocal() as db:
        base = _apply_transaction_filters(select(Transaction), user_id=user_id, payload=payload)
        count_stmt = _apply_transaction_filters(select(func.count()).select_from(Transaction), user_id=user_id, payload=payload)
        total = db.scalar(count_stmt) or 0
        rows = db.scalars(
            base.order_by(Transaction.operation_at.desc(), Transaction.source_row_number.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [_serialize(row, TRANSACTION_FIELDS) for row in rows],
            "pagination": {"page": page, "page_size": page_size, "total": total},
        }


def handle_transactions_get(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        transaction = _get_owned(db, Transaction, Transaction.user_id, user_id, payload.get("transaction_id") or payload.get("id"))
        return _serialize(transaction, TRANSACTION_FIELDS)


def handle_transactions_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        row = _prepare_transaction_row(db, user_id, payload)
        transaction = Transaction(**row)
        db.add(transaction)
        db.commit()
        db.refresh(transaction)
        return _serialize(transaction, TRANSACTION_FIELDS)


def handle_transactions_update(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    transaction_id = payload.get("transaction_id") or payload.get("id")
    with SessionLocal() as db:
        transaction = _get_owned(db, Transaction, Transaction.user_id, user_id, transaction_id)
        updates = {key: value for key, value in payload.items() if key in TRANSACTION_FIELDS and key not in {"id", "user_id"}}
        _assign(transaction, updates)
        db.commit()
        db.refresh(transaction)
        return _serialize(transaction, TRANSACTION_FIELDS)


def handle_transactions_delete(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        transaction = _get_owned(db, Transaction, Transaction.user_id, user_id, payload.get("transaction_id") or payload.get("id"))
        db.delete(transaction)
        db.commit()
    return {"status": "deleted"}


def handle_transactions_bulk_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise MessageError(422, "items must be a list")
    with SessionLocal() as db:
        rows = [_prepare_transaction_row(db, user_id, item) for item in items]
        if not rows:
            return {"received": 0, "inserted": 0}
        stmt = insert(Transaction).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        result = db.execute(stmt)
        db.commit()
        return {"received": len(rows), "inserted": result.rowcount or 0}


def handle_transactions_sum_by_scope(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        expense_stmt = _apply_transaction_filters(
            select(func.coalesce(func.sum(Transaction.operation_amount), 0)),
            user_id=user_id,
            payload={**payload, "type": "expense"},
        )
        income_stmt = _apply_transaction_filters(
            select(func.coalesce(func.sum(Transaction.operation_amount), 0)),
            user_id=user_id,
            payload={**payload, "type": "income"},
        )
        return {
            "income_total": _decimal_str(db.scalar(income_stmt)),
            "expense_total": _decimal_str(db.scalar(expense_stmt)),
        }


def handle_finance_balance_before_period(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    period_start = _parse_date(payload.get("period_start")) or date.today()
    with SessionLocal() as db:
        value = db.execute(
            text(
                """
                select
                  coalesce((select sum(initial_balance) from accounts where owner_user_id = :user_id and is_archived = false), 0)
                  + coalesce((select sum(operation_amount) from transactions where user_id = :user_id and operation_at::date < :period_start), 0)
                  as actual_balance
                """
            ),
            {"user_id": user_id, "period_start": period_start},
        ).scalar()
    return {"actual_balance": _decimal_str(Decimal(str(value or "0"))), "currency": "RUB"}


def handle_finance_income_expected_candidates(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    page, page_size = _page(payload)
    period_start = _parse_date(payload.get("period_start"))
    period_end = _parse_date(payload.get("period_end"))
    date_filter = ""
    params: dict[str, Any] = {"user_id": user_id, "offset": (page - 1) * page_size, "limit": page_size}
    if period_start and period_end:
        date_filter = "where expected_at between :period_start and :period_end"
        params["period_start"] = period_start
        params["period_end"] = period_end
    base_sql = """
        select null as id,
               null as account_id,
               coalesce(nullif(description, ''), nullif(category_name, ''), 'income') as source_pattern,
               avg(abs(operation_amount)) as expected_amount,
               coalesce(max(payment_currency), max(operation_currency), 'RUB') as currency,
               (max(operation_at) + interval '30 days')::date as expected_at,
               least(0.9500, cast(count(*) as numeric) / 12.0) as confidence,
               null as created_at,
               null as updated_at
        from transactions
        where user_id = :user_id and type = 'income'
        group by coalesce(nullif(description, ''), nullif(category_name, ''), 'income')
    """
    with SessionLocal() as db:
        rows = db.execute(
            text(
                f"""
                select *
                from ({base_sql}) s
                {date_filter}
                order by expected_at nulls last, expected_amount desc
                offset :offset limit :limit
                """
            ),
            params,
        ).mappings().all()
        total = db.execute(text(f"select count(*) from ({base_sql}) s {date_filter}"), params).scalar() or 0
    return {"items": [_serialize_mapping(row) for row in rows], "pagination": {"page": page, "page_size": page_size, "total": total}}


def handle_finance_expense_pattern_candidates(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    min_occurrences = max(int(payload.get("min_occurrences") or 2), 2)
    limit = min(max(int(payload.get("limit") or 25), 1), 100)
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                select coalesce(nullif(description, ''), nullif(category_name, ''), nullif(mcc, ''), 'unknown') as merchant_pattern,
                       avg(abs(operation_amount)) as average_amount,
                       coalesce(max(payment_currency), max(operation_currency), 'RUB') as currency,
                       max(operation_at) + interval '30 days' as next_expected_at,
                       count(*) as occurrences
                from transactions
                where user_id = :user_id and type = 'expense'
                group by coalesce(nullif(description, ''), nullif(category_name, ''), nullif(mcc, ''), 'unknown')
                having count(*) >= :min_occurrences
                order by count(*) desc, avg(abs(operation_amount)) desc
                limit :limit
                """
            ),
            {"user_id": user_id, "min_occurrences": min_occurrences, "limit": limit},
        ).mappings().all()
    return {"items": [_serialize_mapping(row) for row in rows], "pagination": None}


def handle_accounts_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        page, page_size = _page(payload)
        stmt = select(Account).where(Account.owner_user_id == user_id)
        if not payload.get("include_archived"):
            stmt = stmt.where(Account.is_archived.is_(False))
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.scalars(
            stmt.order_by(Account.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return {
            "items": [_serialize_account(db, row) for row in rows],
            "pagination": {"page": page, "page_size": page_size, "total": total},
        }


def handle_accounts_get(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        account = _get_owned(db, Account, Account.owner_user_id, user_id, payload.get("account_id") or payload.get("id"))
        return _serialize_account(db, account)


def handle_accounts_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    data = _pick(payload, ACCOUNT_FIELDS, exclude={"id", "owner_user_id", "created_at", "updated_at"})
    data["owner_user_id"] = user_id
    data.setdefault("display_name", _account_display_name(payload))
    data.setdefault("currency", "RUB")
    data.setdefault("account_type", "card")
    data.setdefault("initial_balance", Decimal("0"))
    _coerce_entity_data(data)
    with SessionLocal() as db:
        account = Account(**data)
        db.add(account)
        db.commit()
        db.refresh(account)
        return _serialize_account(db, account)


def handle_accounts_update(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        account = _get_owned(db, Account, Account.owner_user_id, user_id, payload.get("account_id") or payload.get("id"))
        updates = _pick(payload, ACCOUNT_FIELDS, exclude={"id", "owner_user_id", "created_at", "updated_at"})
        _assign(account, updates)
        db.commit()
        db.refresh(account)
        return _serialize_account(db, account)


def handle_accounts_delete(payload: dict, envelope: dict) -> dict:
    return _delete_entity_response(envelope, Account, Account.owner_user_id, payload.get("account_id") or payload.get("id"))


def handle_accounts_resolve_by_card(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        account = _resolve_account(db, user_id, payload)
        db.commit()
        return _serialize_account(db, account)


def handle_categories_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        if _truthy(payload.get("include_all")):
            return _list_categories_including_import(db, user_id, payload)
        return _list_owned(db, AccountCategory, AccountCategory.created_by_user_id, CATEGORY_FIELDS, user_id, payload)


def handle_categories_get(payload: dict, envelope: dict) -> dict:
    return _get_entity_response(
        envelope,
        AccountCategory,
        AccountCategory.created_by_user_id,
        CATEGORY_FIELDS,
        payload.get("category_id") or payload.get("id"),
    )


def handle_categories_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    data = _pick(payload, CATEGORY_FIELDS, exclude={"id", "created_by_user_id", "created_at", "updated_at"})
    if not data.get("name"):
        raise MessageError(422, "name is required")
    data["created_by_user_id"] = user_id
    return _create_entity(AccountCategory, CATEGORY_FIELDS, data, owner_user_id=user_id)


def handle_categories_update(payload: dict, envelope: dict) -> dict:
    return _update_entity_response(
        envelope,
        AccountCategory,
        AccountCategory.created_by_user_id,
        CATEGORY_FIELDS,
        payload.get("category_id") or payload.get("id"),
        payload,
    )


def handle_categories_delete(payload: dict, envelope: dict) -> dict:
    return _delete_entity_response(
        envelope,
        AccountCategory,
        AccountCategory.created_by_user_id,
        payload.get("category_id") or payload.get("id"),
    )


def handle_limits_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        return _list_owned(db, CategoryLimit, CategoryLimit.owner_user_id, LIMIT_FIELDS, user_id, payload)


def handle_limits_get(payload: dict, envelope: dict) -> dict:
    return _get_entity_response(
        envelope,
        CategoryLimit,
        CategoryLimit.owner_user_id,
        LIMIT_FIELDS,
        payload.get("limit_id") or payload.get("id"),
    )


def handle_limits_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    data = _pick(payload, LIMIT_FIELDS, exclude={"id", "owner_user_id", "created_at", "updated_at"})
    if data.get("limit_amount") is None:
        raise MessageError(422, "limit_amount is required")
    data["owner_user_id"] = user_id
    data.setdefault("currency", "RUB")
    data.setdefault("period_days", 30)
    return _create_entity(CategoryLimit, LIMIT_FIELDS, data, owner_user_id=user_id)


def handle_limits_update(payload: dict, envelope: dict) -> dict:
    return _update_entity_response(
        envelope,
        CategoryLimit,
        CategoryLimit.owner_user_id,
        LIMIT_FIELDS,
        payload.get("limit_id") or payload.get("id"),
        payload,
    )


def handle_limits_delete(payload: dict, envelope: dict) -> dict:
    return _delete_entity_response(envelope, CategoryLimit, CategoryLimit.owner_user_id, payload.get("limit_id") or payload.get("id"))


def handle_limits_due_warnings(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    horizon_until = _parse_datetime(payload.get("horizon_until")) or datetime.now(UTC)
    limit = min(max(int(payload.get("limit") or 500), 1), 1000)
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                select id, period_started_at + (period_days * interval '1 day') as scheduled_at
                from category_limits
                where owner_user_id = :user_id
                  and is_active = true
                  and period_started_at + (period_days * interval '1 day') <= :horizon_until
                order by scheduled_at
                limit :limit
                """
            ),
            {"user_id": user_id, "horizon_until": horizon_until, "limit": limit},
        ).mappings().all()
    return {"items": [_serialize_mapping(row) for row in rows], "pagination": None}


def handle_goals_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        return _list_owned(db, SavingsGoal, SavingsGoal.owner_user_id, GOAL_FIELDS, user_id, payload)


def handle_goals_get(payload: dict, envelope: dict) -> dict:
    return _get_entity_response(envelope, SavingsGoal, SavingsGoal.owner_user_id, GOAL_FIELDS, payload.get("goal_id") or payload.get("id"))


def handle_goals_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    data = _pick(payload, GOAL_FIELDS, exclude={"id", "owner_user_id", "created_at", "updated_at"})
    if not data.get("title") or data.get("target_amount") is None:
        raise MessageError(422, "title and target_amount are required")
    data["owner_user_id"] = user_id
    data.setdefault("currency", "RUB")
    data.setdefault("current_amount", Decimal("0"))
    data.setdefault("status", "active")
    return _create_entity(SavingsGoal, GOAL_FIELDS, data, owner_user_id=user_id)


def handle_goals_update(payload: dict, envelope: dict) -> dict:
    return _update_entity_response(
        envelope,
        SavingsGoal,
        SavingsGoal.owner_user_id,
        GOAL_FIELDS,
        payload.get("goal_id") or payload.get("id"),
        payload,
    )


def handle_goals_delete(payload: dict, envelope: dict) -> dict:
    return _delete_entity_response(envelope, SavingsGoal, SavingsGoal.owner_user_id, payload.get("goal_id") or payload.get("id"))


def _apply_transaction_filters(stmt: Select, *, user_id: UUID, payload: dict) -> Select:
    conditions = [Transaction.user_id == user_id]
    date_from = payload.get("date_from")
    date_to = payload.get("date_to")
    categories = payload.get("categories")
    mcc = payload.get("mcc")
    transaction_type = payload.get("type") or payload.get("transaction_type")
    status = payload.get("status")
    has_cashback = payload.get("has_cashback")
    card_last4 = payload.get("card_last4")
    account_id = payload.get("account_id")
    category_id = payload.get("category_id")

    if date_from is not None:
        conditions.append(Transaction.operation_at >= datetime.combine(_parse_date(date_from), time.min, tzinfo=UTC))
    if date_to is not None:
        conditions.append(Transaction.operation_at <= datetime.combine(_parse_date(date_to), time.max, tzinfo=UTC))
    if categories:
        conditions.append(Transaction.category_name.in_(_as_list(categories)))
    if mcc:
        conditions.append(Transaction.mcc.in_(_as_list(mcc)))
    if transaction_type:
        if transaction_type not in {"income", "expense"}:
            raise MessageError(422, "type must be income or expense")
        conditions.append(Transaction.type == transaction_type)
    if status:
        conditions.append(Transaction.status == status)
    if card_last4:
        conditions.append(Transaction.card_last4.in_(_as_list(card_last4)))
    if account_id:
        conditions.append(Transaction.account_id == UUID(str(account_id)))
    if category_id:
        conditions.append(Transaction.category_id == UUID(str(category_id)))
    if has_cashback is True:
        conditions.append(and_(Transaction.cashback_amount.is_not(None), Transaction.cashback_amount != 0))
    elif has_cashback is False:
        conditions.append(or_(Transaction.cashback_amount.is_(None), Transaction.cashback_amount == 0))
    return stmt.where(*conditions)


def _prepare_transaction_row(db: Session, user_id: UUID, item: dict) -> dict:
    row = _pick(item, TRANSACTION_FIELDS, exclude={"id", "user_id", "created_at", "updated_at"})
    required = ["import_id", "source_file_id", "source_sheet", "source_row_number", "type", "operation_at", "operation_amount"]
    missing = [field for field in required if row.get(field) in {None, ""}]
    if missing:
        raise MessageError(422, f"Missing transaction fields: {', '.join(missing)}")
    row["user_id"] = user_id
    row["import_id"] = UUID(str(row["import_id"]))
    row["source_file_id"] = UUID(str(row["source_file_id"]))
    if row.get("account_id"):
        row["account_id"] = UUID(str(row["account_id"]))
    elif row.get("card_last4"):
        account = _resolve_account(
            db,
            user_id,
            {
                "card_last4": row.get("card_last4"),
                "currency": row.get("payment_currency") or row.get("operation_currency") or "RUB",
                "display_name": row.get("card_mask") or _account_display_name(row),
            },
        )
        row["account_id"] = account.id
    if row.get("category_id"):
        row["category_id"] = UUID(str(row["category_id"]))
    row.setdefault("account_id", None)
    row.setdefault("category_id", None)
    for field in DECIMAL_FIELDS:
        if field in row:
            row[field] = _parse_decimal(row[field])
    for field in ("operation_at", "payment_at"):
        if field in row:
            row[field] = _parse_datetime(row[field])
    row.setdefault("dedupe_key", f"{row['source_sheet']}:{row['source_row_number']}")
    row.setdefault("raw_payload", {})
    return row


def _resolve_account(db: Session, user_id: UUID, payload: dict) -> Account:
    card_last4 = _last4(payload.get("card_last4") or payload.get("card_mask"))
    if card_last4:
        account = db.scalar(
            select(Account).where(
                Account.owner_user_id == user_id,
                Account.card_last4 == card_last4,
                Account.is_archived.is_(False),
            )
        )
        if account is not None:
            return account
    account = Account(
        owner_user_id=user_id,
        card_last4=card_last4,
        display_name=str(payload.get("display_name") or _account_display_name(payload)),
        account_type=str(payload.get("account_type") or "card"),
        currency=str(payload.get("currency") or "RUB"),
        bank_source=payload.get("bank_source"),
        initial_balance=_parse_decimal(payload.get("initial_balance") or "0") or Decimal("0"),
    )
    db.add(account)
    db.flush()
    return account


def _list_categories_including_import(db: Session, user_id: UUID, payload: dict) -> dict:
    page, page_size = _page(payload)
    include_archived = _truthy(payload.get("include_archived"))

    manual_stmt = select(AccountCategory).where(AccountCategory.created_by_user_id == user_id)
    if not include_archived:
        manual_stmt = manual_stmt.where(AccountCategory.is_archived.is_(False))
    manual_rows = db.scalars(manual_stmt).all()

    items: list[dict] = []
    seen_names: set[str] = set()
    for row in manual_rows:
        item = _serialize(row, CATEGORY_FIELDS)
        item["source"] = "manual"
        items.append(item)
        seen_names.add(str(item["name"]).casefold())

    import_rows = db.execute(
        text(
            """
            select
              category_name as name,
              min(operation_at) as created_at,
              max(operation_at) as updated_at
            from transactions
            where user_id = :user_id
              and category_name is not null
              and btrim(category_name) <> ''
            group by category_name
            order by category_name
            """
        ),
        {"user_id": user_id},
    ).mappings().all()

    for row in import_rows:
        name = str(row["name"])
        if name.casefold() in seen_names:
            continue
        category_id = _import_category_id(user_id, name)
        items.append(
            {
                "id": str(category_id),
                "account_id": None,
                "created_by_user_id": str(user_id),
                "name": name,
                "description": None,
                "icon_key": None,
                "is_archived": False,
                "created_at": row["created_at"].isoformat() if row["created_at"] else datetime.now(UTC).isoformat(),
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else datetime.now(UTC).isoformat(),
                "source": "import",
            }
        )
        seen_names.add(name.casefold())

    items.sort(key=lambda item: str(item["name"]).casefold())
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return {"items": page_items, "pagination": {"page": page, "page_size": page_size, "total": total}}


def _import_category_id(user_id: UUID, name: str) -> UUID:
    return uuid_stdlib.uuid5(IMPORT_CATEGORY_NAMESPACE, f"{user_id}:{name}")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _list_owned(db: Session, model, owner_column, fields: tuple[str, ...], user_id: UUID, payload: dict) -> dict:
    page, page_size = _page(payload)
    stmt = select(model).where(owner_column == user_id)
    include_archived = bool(payload.get("include_archived"))
    if hasattr(model, "is_archived") and not include_archived:
        stmt = stmt.where(model.is_archived.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order_column = getattr(model, "updated_at", getattr(model, "created_at", None))
    if order_column is not None:
        stmt = stmt.order_by(order_column.desc())
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    items = [_serialize(row, fields) for row in rows]
    if model is AccountCategory:
        for item in items:
            item["source"] = "manual"
    return {"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}}


def _get_entity_response(envelope: dict, model, owner_column, fields: tuple[str, ...], entity_id: Any) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        row = _get_owned(db, model, owner_column, user_id, entity_id)
        return _serialize(row, fields)


def _create_entity(model, fields: tuple[str, ...], data: dict, *, owner_user_id: UUID | None = None) -> dict:
    _coerce_entity_data(data)
    with SessionLocal() as db:
        if owner_user_id is not None:
            _validate_owned_references(db, owner_user_id, data)
        row = model(**data)
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize(row, fields)


def _update_entity_response(
    envelope: dict,
    model,
    owner_column,
    fields: tuple[str, ...],
    entity_id: Any,
    payload: dict,
) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        row = _get_owned(db, model, owner_column, user_id, entity_id)
        updates = _pick(payload, fields, exclude={"id", owner_column.key, "created_at", "updated_at"})
        _assign(row, updates)
        _validate_owned_references(db, user_id, updates)
        db.commit()
        db.refresh(row)
        return _serialize(row, fields)


def _delete_entity_response(envelope: dict, model, owner_column, entity_id: Any) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        row = _get_owned(db, model, owner_column, user_id, entity_id)
        if hasattr(row, "is_archived"):
            row.is_archived = True
        elif hasattr(row, "status"):
            row.status = "deleted"
        else:
            db.delete(row)
        db.commit()
    return {"status": "deleted"}


def _get_owned(db: Session, model, owner_column, user_id: UUID, entity_id: Any):
    if not entity_id:
        raise MessageError(422, "id is required")
    row = db.scalar(select(model).where(model.id == UUID(str(entity_id)), owner_column == user_id))
    if row is None:
        raise MessageError(404, "Resource not found")
    return row


def _validate_owned_references(db: Session, user_id: UUID, data: dict) -> None:
    account_id = data.get("account_id")
    if account_id:
        exists = db.scalar(
            select(Account.id).where(
                Account.id == UUID(str(account_id)),
                Account.owner_user_id == user_id,
                Account.is_archived.is_(False),
            )
        )
        if not exists:
            raise MessageError(404, "Account not found")
    category_id = data.get("category_id")
    if category_id:
        exists = db.scalar(
            select(AccountCategory.id).where(
                AccountCategory.id == UUID(str(category_id)),
                AccountCategory.created_by_user_id == user_id,
                AccountCategory.is_archived.is_(False),
            )
        )
        if not exists:
            raise MessageError(404, "Category not found")


def _assign(row, updates: dict) -> None:
    _coerce_entity_data(updates)
    for key, value in updates.items():
        setattr(row, key, value)


def _coerce_entity_data(data: dict) -> None:
    for field in DECIMAL_FIELDS:
        if field in data:
            data[field] = _parse_decimal(data[field])
    for field in UUID_FIELDS:
        if field in data and data[field]:
            data[field] = UUID(str(data[field]))
    for field in DATETIME_FIELDS:
        if field in data and data[field]:
            data[field] = _parse_datetime(data[field])
    for field in DATE_FIELDS:
        if field in data and data[field]:
            data[field] = _parse_date(data[field])


def _pick(payload: dict, fields: tuple[str, ...], *, exclude: set[str]) -> dict:
    return {key: payload[key] for key in fields if key in payload and key not in exclude}


def _serialize(row, fields: tuple[str, ...]) -> dict:
    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(row, field)
        if isinstance(value, Decimal):
            value = _decimal_str(value)
        elif isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif isinstance(value, UUID):
            value = str(value)
        result[field] = value
    return result


def _serialize_mapping(row) -> dict:
    result: dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, Decimal):
            value = _decimal_str(value)
        elif isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif isinstance(value, UUID):
            value = str(value)
        result[key] = value
    return result


def _serialize_account(db: Session, account: Account) -> dict:
    payload = _serialize(account, ACCOUNT_FIELDS)
    transaction_total = db.scalar(
        select(func.coalesce(func.sum(Transaction.operation_amount), 0)).where(
            Transaction.user_id == account.owner_user_id,
            Transaction.account_id == account.id,
        )
    )
    current_balance = Decimal(str(account.initial_balance or "0")) + Decimal(str(transaction_total or "0"))
    payload["current_balance"] = _decimal_str(current_balance)
    return payload


def _page(payload: dict) -> tuple[int, int]:
    page = max(int(payload.get("page") or 1), 1)
    page_size = min(max(int(payload.get("page_size") or 50), 1), 500)
    return page, page_size


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _last4(value: Any) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


def _account_display_name(payload: dict) -> str:
    card_last4 = _last4(payload.get("card_last4") or payload.get("card_mask"))
    return f"Card {card_last4}" if card_last4 else "Imported account"


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _decimal_str(value: Any) -> str:
    return format(Decimal(str(value or "0")), "f")


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


MESSAGE_HANDLERS = {
    "transactions.list": handle_transactions_list,
    "transactions.get": handle_transactions_get,
    "transactions.create": handle_transactions_create,
    "transactions.update": handle_transactions_update,
    "transactions.delete": handle_transactions_delete,
    "transactions.bulk_create": handle_transactions_bulk_create,
    "transactions.sum_by_scope": handle_transactions_sum_by_scope,
    "finance.balance_before_period": handle_finance_balance_before_period,
    "finance.income_expected_candidates": handle_finance_income_expected_candidates,
    "finance.expense_pattern_candidates": handle_finance_expense_pattern_candidates,
    "accounts.list": handle_accounts_list,
    "accounts.get": handle_accounts_get,
    "accounts.create": handle_accounts_create,
    "accounts.update": handle_accounts_update,
    "accounts.delete": handle_accounts_delete,
    "accounts.resolve_by_card": handle_accounts_resolve_by_card,
    "categories.list": handle_categories_list,
    "categories.get": handle_categories_get,
    "categories.create": handle_categories_create,
    "categories.update": handle_categories_update,
    "categories.delete": handle_categories_delete,
    "limits.list": handle_limits_list,
    "limits.get": handle_limits_get,
    "limits.create": handle_limits_create,
    "limits.update": handle_limits_update,
    "limits.delete": handle_limits_delete,
    "limits.due_warnings": handle_limits_due_warnings,
    "goals.list": handle_goals_list,
    "goals.get": handle_goals_get,
    "goals.create": handle_goals_create,
    "goals.update": handle_goals_update,
    "goals.delete": handle_goals_delete,
}
