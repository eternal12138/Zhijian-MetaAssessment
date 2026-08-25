"""认证路由 —— 登录 / 注册 / 修改密码"""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, UserOut, TokenResponse
from app.core.security import (
    hash_password, verify_password, create_access_token, get_current_user
)
from app.core.time import utc_now_naive
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["认证"])

class ChangePasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    """注册新用户"""
    settings = get_settings()
    if not settings.ALLOW_PUBLIC_REGISTRATION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="公开注册未开放")
    if data.role != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="公开注册只能创建学生账号")

    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        name=data.name,
        role="student",
        avatar_text=data.name[0],
        class_group=data.class_group,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    token = create_access_token({
        "sub": user.id,
        "role": user.role,
        "ver": user.token_version,
    })
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    settings = get_settings()
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()

    now = utc_now_naive()
    if user and user.locked_until and user.locked_until > now:
        retry_after = max(
            1,
            int((user.locked_until - now).total_seconds()),
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录失败次数过多，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )
    if not user or not verify_password(data.password, user.password_hash):
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(
                    minutes=settings.LOGIN_LOCKOUT_MINUTES
                )
            await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户已禁用")

    user.failed_login_attempts = 0
    user.locked_until = None
    await db.flush()
    token = create_access_token({
        "sub": user.id,
        "role": user.role,
        "ver": user.token_version,
    })
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    data: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """当前用户修改自己的密码"""
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少为6位")
    if data.new_password == "123456":
        raise HTTPException(status_code=400, detail="新密码不能继续使用默认密码")
    current_user.password_hash = hash_password(data.new_password)
    current_user.must_change_password = False
    current_user.failed_login_attempts = 0
    current_user.locked_until = None
    current_user.token_version += 1
    await db.flush()
    token = create_access_token({
        "sub": current_user.id,
        "role": current_user.role,
        "ver": current_user.token_version,
    })
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(current_user),
    )


@router.post("/skip-password-change", response_model=TokenResponse)
async def skip_password_change(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """仅在当前登录会话中暂缓修改；数据库提醒标记保持不变。"""
    token = create_access_token({
        "sub": current_user.id,
        "role": current_user.role,
        "ver": current_user.token_version,
        "password_change_deferred": True,
    })
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(current_user),
    )
