from uuid import UUID

from sqlalchemy import create_engine, text

from services.finance_service.app.handlers import (
    IMPORT_CATEGORY_NAMESPACE,
    _import_category_id,
    _truthy,
    handle_categories_list,
)
from services.migration_service.app.config import Settings as MigrationSettings

ROOT_DB = MigrationSettings().database_url


def test_truthy_parses_common_values():
    assert _truthy(True) is True
    assert _truthy("true") is True
    assert _truthy("1") is True
    assert _truthy(False) is False
    assert _truthy("no") is False


def test_import_category_id_is_stable():
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    first = _import_category_id(user_id, "Фастфуд")
    second = _import_category_id(user_id, "Фастфуд")
    assert first == second
    assert first.version == 5
    assert IMPORT_CATEGORY_NAMESPACE


def test_categories_list_include_all_merges_import_names():
    engine = create_engine(ROOT_DB, pool_pre_ping=True)
    with engine.connect() as conn:
        user_id = conn.scalar(
            text(
                """
                select u.id
                from users u
                join transactions t on t.user_id = u.id
                where t.category_name is not null and btrim(t.category_name) <> ''
                limit 1
                """
            )
        )
    if user_id is None:
        return

    envelope = {"user": {"id": str(user_id)}}
    manual_only = handle_categories_list({"page": 1, "page_size": 500}, envelope)
    with_all = handle_categories_list({"page": 1, "page_size": 500, "include_all": True}, envelope)

    manual_names = {item["name"] for item in manual_only["items"]}
    all_names = {item["name"] for item in with_all["items"]}
    import_names = {item["name"] for item in with_all["items"] if item.get("source") == "import"}

    assert len(with_all["items"]) >= len(manual_only["items"])
    assert manual_names.issubset(all_names)
    assert import_names or len(all_names) > len(manual_names)

    for item in with_all["items"]:
        assert item["source"] in {"manual", "import"}
