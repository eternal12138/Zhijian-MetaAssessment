"""用户路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserOut
from app.core.security import can_access_user, get_current_user

router = APIRouter(prefix="/users", tags=["用户"])


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserOut.model_validate(user)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取指定用户信息"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not can_access_user(current_user, user):
        raise HTTPException(status_code=403, detail="无权查看该用户")
    return UserOut.model_validate(user)
