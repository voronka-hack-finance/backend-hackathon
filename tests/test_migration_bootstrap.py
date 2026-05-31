from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from services.migration_service.app import bootstrap
from services.migration_service.app.config import Settings
from services.migration_service.app import main as migration_main
from services.migration_service.app import reset

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_FILE = ROOT / "family-bugget.xlsx"


def test_default_demo_user_credentials():
    settings = Settings()
    assert settings.bootstrap_user_email == "demo@example.com"
    assert settings.bootstrap_user_password == "secret123"
    assert settings.bootstrap_user_display_name == "Иван Иванов"
    assert settings.bootstrap_reset_on_start is True


def test_default_excel_path_points_to_repo_root_file():
    settings = Settings()
    assert settings.bootstrap_excel_path.name == "family-bugget.xlsx"
    assert settings.bootstrap_excel_path.parent == ROOT


def test_run_bootstrap_skips_when_disabled():
    engine = MagicMock()
    with patch.object(bootstrap.settings, "bootstrap_excel_enabled", False):
        bootstrap.run_bootstrap(engine)
    engine.begin.assert_not_called()


def test_run_bootstrap_skips_when_file_missing(tmp_path: Path):
    engine = MagicMock()
    missing = tmp_path / "missing.xlsx"
    with (
        patch.object(bootstrap.settings, "bootstrap_excel_enabled", True),
        patch.object(bootstrap.settings, "bootstrap_excel_path", missing),
    ):
        bootstrap.run_bootstrap(engine)
    engine.begin.assert_not_called()


def test_reset_skips_when_disabled():
    engine = MagicMock()
    with patch.object(reset.settings, "bootstrap_reset_on_start", False):
        reset.reset_application_data(engine)
    engine.connect.assert_not_called()


def test_reset_preserves_alembic_version_table():
    assert reset.PRESERVED_TABLES == frozenset({"alembic_version"})


def test_migration_service_uses_alembic_runner():
    assert not hasattr(migration_main, "_apply_migrations")
    assert migration_main.ALEMBIC_INI.name == "alembic.ini"
    assert migration_main.BASELINE_REVISION == "0001_initial_schema"


def test_legacy_bridge_detects_schema_migrations_without_alembic_version():
    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    conn.scalar.side_effect = [True, 3, False]

    assert migration_main._needs_legacy_bridge(engine) is True


def test_legacy_bridge_skips_when_alembic_version_exists():
    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    conn.scalar.side_effect = [True, 3, True, 1]

    assert migration_main._needs_legacy_bridge(engine) is False


def test_alembic_scaffold_exists():
    service_dir = Path("services/migration_service")
    versions = sorted((service_dir / "alembic" / "versions").glob("*.py"))

    assert (service_dir / "alembic.ini").is_file()
    assert (service_dir / "alembic" / "env.py").is_file()
    assert (service_dir / "alembic" / "script.py.mako").is_file()
    assert [path.stem for path in versions] == [
        "0001_initial_schema",
        "0002_expanded_plan",
        "0003_bucket_policy_state",
        "0004_transaction_dedupe",
        "0005_health_score_service",
        "0006_regular_expenses_manual_crud",
        "0007_user_debts",
    ]


def test_parser_reads_sample_file_for_bootstrap_contract():
    if not SAMPLE_FILE.is_file():
        return
    result = bootstrap._parser.parse(SAMPLE_FILE.read_bytes())
    assert result.total_rows == 2728
    assert len(result.transactions) == 2728
    assert result.errors == []


def test_build_sber_demo_transactions_has_four_realistic_items():
    account_id = uuid4()
    import_id = uuid4()
    file_id = uuid4()
    items = bootstrap.build_sber_demo_transactions(
        account_id=account_id,
        import_id=import_id,
        source_file_id=file_id,
    )
    assert len(items) == 4
    assert {item["type"] for item in items} == {"income", "expense"}
    assert sum(1 for item in items if item["type"] == "income") == 1
    assert all(item["account_id"] == str(account_id) for item in items)
    assert all(item["card_last4"] == bootstrap.SBER_DEMO_CARD_LAST4 for item in items)
    assert all(item["source_sheet"] == bootstrap.SBER_DEMO_LIVE_SHEET for item in items)
    assert all(item["status"] == "OK" for item in items)
    assert items[0]["category_name"] == "Зарплата"
    assert items[1]["description"] == "Пятёрочка"
    assert items[2]["description"] == "Яндекс Go"
    assert items[3]["description"] == "OZON.RU"
    assert len({item["dedupe_key"] for item in items}) == 4


def test_build_demo_chat_mocks_has_five_realistic_ml_dialogs():
    specs = bootstrap.build_demo_chat_mocks()
    assert len(specs) == 5
    assert len({spec["title"] for spec in specs}) == 5
    for spec in specs:
        messages = spec["messages"]
        assert messages
        assert spec["agent_key"]
        assert spec["confidence"]
        assert messages[0]["role"] == "user"
        assert any(message["role"] == "assistant" for message in messages)
        assert all(message["content"].strip() for message in messages)
        assert all(message["offset_minutes"] >= 0 for message in messages)
        assert messages == sorted(messages, key=lambda item: item["offset_minutes"])


def test_build_demo_recommendation_mocks_match_chat_openers():
    chat_specs = bootstrap.build_demo_chat_mocks()
    recommendations = bootstrap.build_demo_recommendation_mocks()
    assert len(recommendations) == 5
    assert [item["title"] for item in recommendations] == [item["title"] for item in chat_specs]
    assert [item["agent_key"] for item in recommendations] == [item["agent_key"] for item in chat_specs]
    for recommendation, chat in zip(recommendations, chat_specs, strict=True):
        first_user = next(message for message in chat["messages"] if message["role"] == "user")
        assert recommendation["content"] == first_user["content"]
        assert recommendation["confidence"] == chat["confidence"]
