from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class UploadResponse(BaseModel):
    file_id: UUID
    import_id: UUID
    status: str


class ImportStatusResponse(BaseModel):
    import_id: UUID
    file_id: UUID
    status: str
    total_rows: int
    parsed_rows: int
    failed_rows: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None = None


class ImportErrorItem(BaseModel):
    sheet_name: str | None
    row_number: int | None
    column_name: str | None
    raw_value: str | None
    error_code: str
    message: str


class ImportErrorsResponse(BaseModel):
    items: list[ImportErrorItem]
