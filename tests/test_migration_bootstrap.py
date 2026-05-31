from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from services.migration_service.app import bootstrap
from services.migration_service.app.config import Settings
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
