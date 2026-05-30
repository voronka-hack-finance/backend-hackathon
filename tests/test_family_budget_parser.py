from decimal import Decimal
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from services.file_service.app.imports.parsers.family_budget_excel_v1 import (
    EXPECTED_HEADER,
    FamilyBudgetExcelParser,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_FILE = ROOT / "family-bugget.xlsx"


def test_parser_reads_real_workbook_with_full_15_column_shape():
    result = FamilyBudgetExcelParser().parse(SAMPLE_FILE.read_bytes())

    assert len(result.matched_sheets) == 40
    assert result.total_rows == 2728
    assert len(result.transactions) == 2728
    assert result.errors == []

    first = result.transactions[0]
    assert first.source_sheet == "Р_12.25"
    assert first.type == "expense"
    assert first.card_last4 == "8336"
    assert first.mcc == "5411"
    assert first.operation_amount == Decimal("-99.99")
    assert first.bonus_amount == Decimal("0.00")
    assert first.investment_rounding_amount == Decimal("0.01")
    assert first.rounded_operation_amount == Decimal("-100.00")
    assert list(first.raw_payload.keys()) == EXPECTED_HEADER

    payload = first.to_bulk_item(import_id="00000000-0000-0000-0000-000000000001", source_file_id="00000000-0000-0000-0000-000000000002")
    assert payload["bonus_amount"] == "0.00"
    assert payload["investment_rounding_amount"] == "0.01"
    assert payload["rounded_operation_amount"] == "-100.00"


def test_parser_rejects_unsupported_header():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Р_01.26"
    sheet.append(EXPECTED_HEADER[:12])
    sheet.append(["2026-01-01", "2026-01-01", "*1234", "OK", "-1", "RUB", "-1", "RUB", "0", "Test", "5411", "Desc"])
    buffer = BytesIO()
    workbook.save(buffer)

    result = FamilyBudgetExcelParser().inspect(buffer.getvalue())

    assert result.transactions == []
    assert result.errors
    assert result.errors[0].error_code == "unsupported_header"


def test_parser_skips_non_matching_sheets():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Manual"
    sheet.append(EXPECTED_HEADER)
    buffer = BytesIO()
    workbook.save(buffer)

    result = FamilyBudgetExcelParser().inspect(buffer.getvalue())

    assert result.matched_sheets == []
    assert result.errors[0].error_code == "no_supported_sheets"
