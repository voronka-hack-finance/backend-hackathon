from __future__ import annotations

import base64
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from common.messaging import UserContext
from services.gateway.app.constants import FILE_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import (
    FILES_DELETE,
    FILES_GET,
    FILES_LIST,
    FILES_UPDATE,
    FILES_UPLOAD,
    IMPORT_ERRORS,
    IMPORT_STATUS,
)
from services.gateway.app.rpc import model_payload, rpc_call, rpc_call_async
from services.gateway.app.schemas import (
    ErrorResponse,
    FileResponse,
    FilesPageResponse,
    FileUpdateRequest,
    ImportErrorsResponse,
    ImportStatusResponse,
    StatusResponse,
    UploadResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Files"])


@router.post(
    "/files",
    summary="Загрузка Excel-файла",
    description=FILES_UPLOAD,
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**PROTECTED_RESPONSES, 400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def upload_file(
    file: UploadFile = File(..., description="Рабочая книга семейного бюджета в формате .xlsx."),
    source_type: str = Form(
        default="excel_family_budget_v1",
        description="Идентификатор парсера (по умолчанию excel_family_budget_v1).",
    ),
    user: UserContext = Depends(current_user),
) -> dict:
    file_bytes = await file.read()
    return await rpc_call_async(
        FILE_QUEUE,
        "files.upload.create",
        {
            "filename": file.filename or "upload.xlsx",
            "content_type": file.content_type,
            "source_type": source_type,
            "file_base64": base64.b64encode(file_bytes).decode("ascii"),
        },
        user=user,
        timeout_seconds=120.0,
    )


@router.get(
    "/files",
    summary="Список загруженных файлов",
    description=FILES_LIST,
    response_model=FilesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def files_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы, начиная с 1."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы (максимум 500)."),
) -> dict:
    return rpc_call(FILE_QUEUE, "files.list", {"page": page, "page_size": page_size}, user=user)


@router.get(
    "/files/{file_id}",
    summary="Метаданные файла",
    description=FILES_GET,
    response_model=FileResponse,
    responses=PROTECTED_RESPONSES,
)
def files_get(file_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FILE_QUEUE, "files.get", {"file_id": str(file_id)}, user=user)


@router.patch(
    "/files/{file_id}",
    summary="Обновление метаданных файла",
    description=FILES_UPDATE,
    response_model=FileResponse,
    responses=PROTECTED_RESPONSES,
)
def files_update(file_id: UUID, payload: FileUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FILE_QUEUE, "files.update", {"file_id": str(file_id), **model_payload(payload)}, user=user)


@router.delete(
    "/files/{file_id}",
    summary="Удаление файла",
    description=FILES_DELETE,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def files_delete(file_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FILE_QUEUE, "files.delete", {"file_id": str(file_id)}, user=user)


imports_router = APIRouter(prefix="/api/v1/imports", tags=["Imports"])


@imports_router.get(
    "/{import_id}",
    summary="Статус импорта",
    description=IMPORT_STATUS,
    response_model=ImportStatusResponse,
    responses=PROTECTED_RESPONSES,
)
def import_status(import_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FILE_QUEUE, "imports.status.get", {"import_id": str(import_id)}, user=user)


@imports_router.get(
    "/{import_id}/errors",
    summary="Ошибки импорта",
    description=IMPORT_ERRORS,
    response_model=ImportErrorsResponse,
    responses=PROTECTED_RESPONSES,
)
def import_errors(
    import_id: UUID,
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=100, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(
        FILE_QUEUE,
        "imports.errors.list",
        {"import_id": str(import_id), "page": page, "page_size": page_size},
        user=user,
    )
