"""Restricted endpoints used by external ASR providers."""
from __future__ import annotations

from functools import lru_cache
import io
import math
import struct
import wave

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.asr import AsrJob
from app.services.asr_signing import verify_audio_download
from app.services.runtime_model_config import load_runtime_model_settings

router = APIRouter(prefix="/asr-provider", tags=["ASR provider"])
settings = get_settings()


@lru_cache(maxsize=1)
def _diagnostic_wav() -> bytes:
    """Create a short non-speech WAV used only for provider diagnostics."""
    sample_rate = 16000
    frame_count = sample_rate
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = round(1200 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        audio.writeframes(bytes(frames))
    return stream.getvalue()


@router.get("/diagnostic-audio", include_in_schema=False)
async def diagnostic_audio_for_provider(
    expires: int = Query(...),
    signature: str = Query(..., min_length=64, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    await load_runtime_model_settings(db, settings)
    if not verify_audio_download(
        "diagnostic",
        expires,
        signature,
        settings.ASR_AUDIO_SIGNING_SECRET,
    ):
        raise HTTPException(status_code=403, detail="诊断音频签名无效或已过期")
    return Response(
        content=_diagnostic_wav(),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/audio/{job_id}", include_in_schema=False)
async def download_audio_for_provider(
    job_id: str,
    expires: int = Query(...),
    signature: str = Query(..., min_length=64, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    await load_runtime_model_settings(db, settings)
    if not verify_audio_download(
        job_id,
        expires,
        signature,
        settings.ASR_AUDIO_SIGNING_SECRET,
    ):
        raise HTTPException(status_code=403, detail="音频下载签名无效或已过期")

    job = await db.get(AsrJob, job_id)
    if (
        job is None
        or job.status != "transcribing"
        or not job.canonical_audio_path
    ):
        raise HTTPException(status_code=404, detail="音频不存在或当前不可下载")

    root = settings.audio_upload_path.resolve()
    audio_path = (root / job.canonical_audio_path).resolve()
    try:
        audio_path.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="音频路径无效") from error
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在")

    return FileResponse(
        path=audio_path,
        media_type="audio/wav",
        filename=f"{job.id}.wav",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )
