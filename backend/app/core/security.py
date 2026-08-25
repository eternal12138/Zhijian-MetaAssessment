"""
认证与安全工具
"""
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.models.user import User

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


def is_password_action_path(path: str) -> bool:
    """Allow authentication actions behind proxies with or without /api."""
    return any(
        path.endswith(suffix)
        for suffix in (
            "/auth/change-password",
            "/auth/skip-password-change",
            "/users/me",
        )
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 JWT 中解析当前用户，注入到路由依赖"""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少认证令牌")
    token = credentials.credentials
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证令牌")

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌缺少用户标识")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    if int(payload.get("ver", -1)) != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证令牌已失效")
    password_change_deferred = payload.get("password_change_deferred") is True
    password_action_path = is_password_action_path(request.url.path)
    if (
        user.must_change_password
        and not password_change_deferred
        and not password_action_path
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "password_change_required",
                "message": "当前使用初始或重置密码，请先选择修改密码或暂不修改",
            },
        )
    return user


def require_role(*roles: str):
    """角色守卫工厂 —— 接受一个或多个角色，支持 admin 全局通行"""
    async def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role == "admin":
            return user  # admin 无视限制
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要 {', '.join(roles)} 权限"
            )
        return user
    return role_checker


def can_access_user(viewer: User, target: User) -> bool:
    """判断用户是否可查看目标用户的数据；教师仅限其管理班级内的学生。"""
    if viewer.id == target.id or viewer.role == "admin":
        return True
    if viewer.role != "teacher" or target.role != "student" or not target.class_group:
        return False
    managed_classes = {
        item.strip()
        for item in (viewer.managed_classes or "").split(",")
        if item.strip()
    }
    return target.class_group in managed_classes
