"""Administrator-managed human narration recordings."""
from __future__ import annotations

import hashlib
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import get_current_user, require_role
from app.database import get_db
from app.models.narration import NarrationAsset
from app.models.task import AssessmentTask
from app.models.user import User
from app.schemas.protocol import NarrationAssetOut, NarrationSlotOut
from app.services.narration_catalog import narration_slots


admin_router = APIRouter(prefix="/admin/narration-assets", tags=["真人朗读录音"])
audio_router = APIRouter(prefix="/narrations", tags=["测评朗读录音"])
settings = get_settings()

_TYPE_SUFFIX = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
}


async def _protocol_tasks(db: AsyncSession) -> list[AssessmentTask]:
    result = await db.execute(
        select(AssessmentTask)
        .where(
            AssessmentTask.status == "published",
            AssessmentTask.protocol_order > 0,
            AssessmentTask.protocol_order <= 2,
        )
        .order_by(AssessmentTask.protocol_order.asc())
    )
    return list(result.scalars().all())


def _detected_type(data: bytes, declared_type: str, filename: str) -> tuple[str, str]:
    declared = declared_type.split(";", 1)[0].strip().lower()
    suffix = Path(filename).suffix.lower()
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav", ".wav"
    if data.startswith(b"ID3") or (
        len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg", ".mp3"
    if data.startswith(b"OggS"):
        return "audio/ogg", ".ogg"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "audio/webm", ".webm"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "audio/mp4", ".m4a"
    if declared in _TYPE_SUFFIX and suffix == _TYPE_SUFFIX[declared]:
        return declared, suffix
    raise HTTPException(
        status_code=415,
        detail="录音格式无法识别；请上传 MP3、WAV、M4A、OGG 或 WebM 音频",
    )


def _safe_audio_path(storage_path: str) -> Path:
    root = settings.audio_upload_path.resolve()
    path = (root / storage_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="朗读录音不存在") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="朗读录音文件不存在")
    return path


@admin_router.get("", response_model=list[NarrationSlotOut])
async def list_narration_slots(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    del current_user
    slots = narration_slots(await _protocol_tasks(db))
    result = await db.execute(
        select(NarrationAsset).where(NarrationAsset.is_active.is_(True))
    )
    active = {item.slot_key: item for item in result.scalars().all()}
    return [
        NarrationSlotOut(
            slot_key=slot.key,
            label=slot.label,
            source_text=slot.source_text,
            category=slot.category,
            asset=active.get(slot.key),
        )
        for slot in slots
    ]


@admin_router.post(
    "/{slot_key}/upload",
    response_model=NarrationAssetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_narration(
    slot_key: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    slots = {slot.key: slot for slot in narration_slots(await _protocol_tasks(db))}
    slot = slots.get(slot_key)
    if slot is None:
        raise HTTPException(status_code=404, detail="朗读录音槽位不存在")

    original_filename = Path(file.filename or "recording").name[:255]
    declared_content_type = file.content_type or ""
    data = await file.read(settings.NARRATION_UPLOAD_MAX_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(status_code=422, detail="录音文件不能为空")
    if len(data) > settings.NARRATION_UPLOAD_MAX_BYTES:
        limit_mb = settings.NARRATION_UPLOAD_MAX_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"单个录音不能超过 {limit_mb} MB")

    mime_type, suffix = _detected_type(data, declared_content_type, original_filename)
    asset_id = str(uuid.uuid4())
    relative_path = f"narrations/{asset_id}{suffix}"
    target = settings.audio_upload_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".uploading")
    temporary.write_bytes(data)
    temporary.replace(target)

    try:
        version = int(await db.scalar(
            select(func.coalesce(func.max(NarrationAsset.version), 0)).where(
                NarrationAsset.slot_key == slot_key
            )
        ) or 0) + 1
        await db.execute(
            update(NarrationAsset)
            .where(
                NarrationAsset.slot_key == slot_key,
                NarrationAsset.is_active.is_(True),
            )
            .values(is_active=False)
        )
        asset = NarrationAsset(
            id=asset_id,
            slot_key=slot_key,
            label=slot.label,
            source_text=slot.source_text,
            original_filename=original_filename,
            storage_path=relative_path,
            mime_type=mime_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            version=version,
            is_active=True,
            uploaded_by=current_user.id,
        )
        db.add(asset)
        await db.flush()
        # created_at is populated by the database. Refresh before FastAPI performs
        # response-model validation so it never triggers async lazy-loading.
        await db.refresh(asset)
        await db.commit()
        return asset
    except Exception:
        target.unlink(missing_ok=True)
        raise


@admin_router.delete("/{asset_id}")
async def disable_narration(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    del current_user
    asset = await db.get(NarrationAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="朗读录音不存在")
    asset.is_active = False
    await db.flush()
    return {
        "status": "success",
        "message": "当前录音已停用；历史测评仍可使用该版本",
    }


@audio_router.get("/{asset_id}/audio")
async def get_narration_audio(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user
    asset = await db.get(NarrationAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="朗读录音不存在")
    return FileResponse(
        path=_safe_audio_path(asset.storage_path),
        media_type=asset.mime_type,
        filename=asset.original_filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )
