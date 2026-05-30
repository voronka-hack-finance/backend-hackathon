from pathlib import Path
from unittest.mock import MagicMock, patch

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
