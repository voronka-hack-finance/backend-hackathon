from __future__ import annotations

from fastapi import APIRouter, Depends

from common.messaging import UserContext
from services.gateway.app.constants import NOTIFICATION_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import (
    NOTIFICATIONS_DEVICES,
    NOTIFICATIONS_PERMISSION,
    NOTIFICATIONS_TEST,
)
from services.gateway.app.rpc import model_payload, rpc_call
from services.gateway.app.schemas import (
    NotificationDeliveryResponse,
    NotificationDeviceRequest,
    NotificationDeviceResponse,
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
