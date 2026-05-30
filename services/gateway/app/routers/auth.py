from __future__ import annotations

from fastapi import APIRouter, Depends, status

from common.messaging import UserContext
from services.gateway.app.constants import ACCESS_QUEUE, PROTECTED_RESPONSES, PUBLIC_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import (
    AUTH_CHANGE_PASSWORD,
    AUTH_LOGIN,
    AUTH_LOGOUT,
    AUTH_ME_GET,
    AUTH_ME_PATCH,
    AUTH_REFRESH,
    AUTH_REGISTER,
)
from services.gateway.app.rpc import model_payload, rpc_call
from services.gateway.app.schemas import (
    ChangePasswordRequest,
    ErrorResponse,
    LoginRequest,
    LogoutRequest,
    ProfileUpdateRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    StatusResponse,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


@router.post(
    "/register",
    summary="Регистрация пользователя",
    description=AUTH_REGISTER,
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses=PUBLIC_RESPONSES,
)
def register(payload: RegisterRequest) -> dict:
    return rpc_call(ACCESS_QUEUE, "auth.register", model_payload(payload))


@router.post(
    "/login",
    summary="Вход и выдача токенов",
    description=AUTH_LOGIN,
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse, "description": "Неверный email или пароль."}, **PUBLIC_RESPONSES},
)
def login(payload: LoginRequest) -> dict:
    return rpc_call(ACCESS_QUEUE, "auth.login", model_payload(payload))


@router.post(
    "/logout",
    summary="Выход из сессии",
    description=AUTH_LOGOUT,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def logout(payload: LogoutRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(ACCESS_QUEUE, "auth.logout", model_payload(payload), user=user)


@router.post(
    "/refresh",
    summary="Обновление access token",
    description=AUTH_REFRESH,
    response_model=TokenResponse,
    responses=PUBLIC_RESPONSES,
)
def refresh(payload: RefreshRequest) -> dict:
    return rpc_call(ACCESS_QUEUE, "auth.refresh", model_payload(payload))


@router.get(
    "/me",
    summary="Текущий пользователь",
    description=AUTH_ME_GET,
    response_model=UserResponse,
    responses=PROTECTED_RESPONSES,
)
def me(user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(ACCESS_QUEUE, "auth.me.get", {}, user=user)


@router.patch(
    "/me",
    summary="Обновление профиля",
    description=AUTH_ME_PATCH,
    response_model=UserResponse,
    responses=PROTECTED_RESPONSES,
)
def update_me(payload: ProfileUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(ACCESS_QUEUE, "auth.me.patch", model_payload(payload), user=user)


@router.post(
    "/change-password",
    summary="Смена пароля",
    description=AUTH_CHANGE_PASSWORD,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def change_password(payload: ChangePasswordRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(ACCESS_QUEUE, "auth.change_password", model_payload(payload), user=user)
