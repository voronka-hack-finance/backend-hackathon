from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import NOTIFICATION_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import (
    NOTIFICATIONS_DEVICES,
    NOTIFICATIONS_DEVICES_LIST,
    NOTIFICATIONS_PERMISSION,
    NOTIFICATIONS_TEST,
)
from services.gateway.app.rpc import model_payload, rpc_call
from services.gateway.app.schemas import (
    NotificationDeliveryResponse,
    NotificationDeviceRequest,
    NotificationDeviceResponse,
    NotificationDevicesPageResponse,
    NotificationPermissionRequest,
    NotificationPreferenceResponse,
    NotificationTestRequest,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


@router.post(
    "/permission",
    summary="Настройка разрешения на push",
    description=NOTIFICATIONS_PERMISSION,
    response_model=NotificationPreferenceResponse,
    responses=PROTECTED_RESPONSES,
)
def notification_permission(payload: NotificationPermissionRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(NOTIFICATION_QUEUE, "notifications.permission.set", model_payload(payload), user=user)


@router.get(
    "/devices",
    summary="Список устройств для push",
    description=NOTIFICATIONS_DEVICES_LIST,
    response_model=NotificationDevicesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def notification_devices_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(
        NOTIFICATION_QUEUE,
        "notifications.devices.list",
        {"page": page, "page_size": page_size},
        user=user,
    )


@router.post(
    "/devices",
    summary="Сохранение устройства для push",
    description=NOTIFICATIONS_DEVICES,
    response_model=NotificationDeviceResponse,
    responses=PROTECTED_RESPONSES,
)
def notification_device(payload: NotificationDeviceRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(NOTIFICATION_QUEUE, "notifications.devices.save", model_payload(payload), user=user)


@router.post(
    "/test",
    summary="Тестовое push-уведомление",
    description=NOTIFICATIONS_TEST,
    response_model=NotificationDeliveryResponse,
    responses=PROTECTED_RESPONSES,
)
def notification_test(payload: NotificationTestRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(NOTIFICATION_QUEUE, "notifications.test.send", model_payload(payload), user=user)
