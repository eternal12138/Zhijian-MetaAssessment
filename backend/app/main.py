"""
知见 AI 元认知测评 —— FastAPI 主入口（全链路加固增强版）
"""
import asyncio
import logging
import time
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text, select

from app.config import get_settings
from app.database import AsyncSessionLocal, init_db
from app.core.middleware import (
    SecurityHeadersMiddleware,
    IdempotencyMiddleware,
    SlidingWindowRateLimiterMiddleware,
    RequestTracingMiddleware,
)
from app.services.runtime_model_config import load_runtime_model_settings
from app.api import (
    admin, ai_evaluation, asr, asr_provider, auth, extraction, narrations, notifications, protocol, reports, research,
    sessions, tasks, users, model_training,
)

settings = get_settings()
logger = logging.getLogger("uvicorn.error")
START_TIME = time.time()



async def _in_process_export_worker() -> None:
    """常驻后台协程：自动扫描并执行云端环境中因服务重启或未及时触发的 queued 导出任务。"""
    logger.info("启动内建数据导出后台任务处理引擎...")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                queued_job = await db.scalar(
                    select(research.ExportJob)
                    .where(
                        research.ExportJob.export_type == "audio_transcript_zip",
                        research.ExportJob.status == "queued",
                    )
                    .order_by(research.ExportJob.created_at.asc())
                    .limit(1)
                )
                if queued_job is not None:
                    job_id = queued_job.id
                    user_id = queued_job.requested_by
                    logger.info("内建导出引擎认领并启动任务 %s (用户 %s)", job_id, user_id)
                    queued_job.status = "preparing"
                    queued_job.progress = 1
                    await db.commit()
                    asyncio.create_task(research._run_audio_transcript_export(job_id, user_id))
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("内建导出引擎扫描异常: %s", e)
            await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：尝试连接数据库并初始化表"""
    if settings.APP_DEBUG:
        try:
            await init_db()
            logger.info("数据库表已就绪: %s", settings.DB_NAME)
        except Exception as e:
            logger.warning(
                "数据库不可用，API 文档可正常访问但数据操作会失败。"
                "请确保 MySQL 已启动；生产环境请执行 scripts/setup_production.py，"
                "开发环境请重新运行 dev.ps1。原因: %s",
                e,
            )
    try:
        async with AsyncSessionLocal() as db:
            await load_runtime_model_settings(db, settings)
        logger.info("运行时模型服务配置已加载")
    except Exception as e:
        logger.warning("运行时模型服务配置加载失败，将使用环境变量：%s", e)
    export_worker_task = asyncio.create_task(_in_process_export_worker())
    try:
        yield
    finally:
        export_worker_task.cancel()
        try:
            await export_worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="基于生成式 AI 启发式对话的元认知自动化测评系统",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
)

# ---- 中间件堆栈（按调用洋葱模型顺序挂载）----
# 1. 响应安全头中间件
app.add_middleware(
    SecurityHeadersMiddleware,
    enabled=settings.SECURITY_HEADERS_ENABLED,
)
# 2. APM 时延度量与 TraceId 追踪
app.add_middleware(RequestTracingMiddleware)
# 3. 接口防刷与滑动窗口速率限制
app.add_middleware(
    SlidingWindowRateLimiterMiddleware,
    enabled=settings.RATE_LIMIT_ENABLED,
    auth_limit_per_min=settings.RATE_LIMIT_AUTH_PER_MINUTE,
    general_limit_per_min=settings.RATE_LIMIT_GENERAL_PER_MINUTE,
    bypass_local_hosts=(
        settings.APP_DEBUG and settings.RATE_LIMIT_BYPASS_LOCAL_DEBUG
    ),
)
# 4. 全局请求幂等性校验（针对带 X-Idempotency-Key 的写操作）
app.add_middleware(IdempotencyMiddleware, ttl_seconds=90)
# 5. 受信任主机与 CORS 跨域
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.trusted_hosts,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Trace-Id", "X-Process-Time-Ms", "X-Idempotency-Hit",
        "X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After",
    ],
)

# ---- 注册业务路由 ----
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(asr.router, prefix="/api")
app.include_router(asr_provider.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(narrations.admin_router, prefix="/api")
app.include_router(narrations.audio_router, prefix="/api")
app.include_router(protocol.router, prefix="/api")
app.include_router(research.router, prefix="/api")
app.include_router(extraction.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(model_training.router, prefix="/api")
app.include_router(ai_evaluation.router, prefix="/api")


@app.get("/api/health")
async def health_check():
    uptime_seconds = int(time.time() - START_TIME)
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "uptime_seconds": uptime_seconds,
        "pid": os.getpid(),
        "env": "debug" if settings.APP_DEBUG else "production",
    }


@app.get("/api/health/live")
async def liveness_check():
    return {"status": "ok"}


@app.get("/api/health/ready")
async def readiness_check():
    checks = {
        "database": False,
        "audio_storage": False,
        "export_storage": False,
    }
    db_latency_ms = 0.0
    try:
        t0 = time.perf_counter()
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        db_latency_ms = (time.perf_counter() - t0) * 1000
        checks["database"] = True

        for name, path in (
            ("audio_storage", settings.audio_upload_path),
            ("export_storage", settings.research_export_path),
        ):
            path.mkdir(parents=True, exist_ok=True)
            checks[name] = path.is_dir()
    except Exception:
        logger.exception("Readiness check failed")

    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "unavailable",
            "checks": checks,
            "db_latency_ms": round(db_latency_ms, 2),
        },
    )
