"""
数据库引擎 & 会话管理 (SQLAlchemy 2.0 async)
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    # 后台 Worker 会频繁轮询数据库；完整 SQL 日志必须显式开启。
    echo=settings.DB_ECHO,
    # MySQL DATETIME has no timezone metadata. Every pooled connection must
    # therefore use UTC so CURRENT_TIMESTAMP/func.now() and application-written
    # timestamps share one unambiguous storage convention.
    connect_args={"init_command": "SET time_zone = '+00:00'"},
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """创建所有表（开发环境使用，生产请用 Alembic）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
