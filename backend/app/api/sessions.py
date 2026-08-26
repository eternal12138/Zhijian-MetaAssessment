"""会话路由 —— 测评会话 CRUD + WebSocket + SSE"""
import time
import json
import asyncio
import math
import re
from datetime import datetime
from pathlib import Path
from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, UploadFile,
    WebSocket, WebSocketDisconnect, status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal, get_db
from app.core.time import utc_now_naive
from app.config import get_settings
from app.models.user import User
from app.models.task import AssessmentTask
from app.models.session import (
    AssessmentSession, DialogueTurn,
    AudioChunk, TranscriptSegment, InteractionEvent,
)
from app.schemas.session import (
    SessionOut, SessionStart, AgentResponse,
    DialogueTurnIn, DialogueTurnOut, CodedSegmentOut,
    AudioChunkOut, TranscriptBatchIn, TranscriptSegmentOut,
    InteractionEventBatchIn, InteractionEventOut, SessionCompleteIn,
)
from app.core.security import can_access_user, decode_token, get_current_user
from app.core.websocket import manager
from app.services.protocol_agent import ProtocolEvent, protocol_agent
from app.services.asr_service import ensure_asr_job
from app.services.audio_manifest import AudioManifestError

router = APIRouter(prefix="/sessions", tags=["测评会话"])
settings = get_settings()
SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LEGACY_DIALOGUE_DETAIL = {
    "code": "LEGACY_DIALOGUE_WORKFLOW_RETIRED",
    "message": "实时对话测评链路已停用，请使用固定协议的录音、转录与交互事件接口",
}
ALLOWED_AUDIO_MIME_TYPES = {
    "audio/webm",
    "audio/mp4",
    "audio/ogg",
    "audio/wav",
    "application/octet-stream",
}

# ---- 标准化主试请求体 ----
class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(default="", max_length=20_000)
    event: ProtocolEvent = ProtocolEvent.PARTICIPANT_TURN
    reminder_index: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_event_payload(self):
        if self.event is ProtocolEvent.PARTICIPANT_TURN and not self.message.strip():
            raise ValueError("被试发言不能为空")
        return self


@router.post("", response_model=SessionOut, status_code=201)
async def start_session(
    data: SessionStart,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """开始一次测评会话"""
    task = await db.get(AssessmentTask, data.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "published" and user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="任务尚未发布")

    session = AssessmentSession(
        user_id=user.id,
        task_id=data.task_id,
        status="preparation",
        model_id="standardized-think-aloud",
        model_params={
            "neutral_prompt_only": True,
            "silence_threshold_seconds": 15,
        },
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return SessionOut(
        id=session.id,
        user_id=session.user_id,
        task_id=session.task_id,
        run_id=session.run_id,
        sequence_no=session.sequence_no,
        status=session.status,
        start_time=session.start_time,
        end_time=session.end_time,
        elapsed_minutes=session.elapsed_minutes,
        ai_agent_version=session.ai_agent_version,
        model_id=session.model_id,
        model_params=session.model_params,
    )


# ---- 标准化主试 SSE ----

@router.post("/chat")
async def chat_sse(
    data: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """记录被试发言；仅明确的静默提醒事件允许主试输出固定提示。"""
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=LEGACY_DIALOGUE_DETAIL)

    if not SAFE_SESSION_ID.fullmatch(data.session_id):
        raise HTTPException(status_code=400, detail="会话 ID 格式不合法")
    session = await db.get(AssessmentSession, data.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    _ensure_session_owner(session, user)
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="会话已结束")

    message = data.message.strip()
    if data.event is ProtocolEvent.PARTICIPANT_TURN and not message:
        raise HTTPException(status_code=422, detail="被试发言不能为空")
    decision = protocol_agent.handle(
        data.event,
        reminder_index=data.reminder_index,
    )

    async def generate():
        try:
            if data.event is ProtocolEvent.PARTICIPANT_TURN:
                db.add(DialogueTurn(
                    session_id=data.session_id,
                    role="user",
                    content=message,
                    timestamp=int(time.time() * 1000),
                ))

            if decision.should_respond and decision.message:
                db.add(DialogueTurn(
                    session_id=data.session_id,
                    role="agent",
                    content=decision.message,
                    timestamp=int(time.time() * 1000),
                ))
                chunk_data = {
                    "content": decision.message,
                    "event": decision.event.value,
                    "prompt_index": decision.prompt_index,
                }
                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"

            await db.commit()
            yield "data: [DONE]\n\n"
        except Exception:
            await db.rollback()
            error_data = {"content": "", "error": "protocol_event_failed"}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/{session_id}/history")
async def get_session_history(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的会话对话历史。"""
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=LEGACY_DIALOGUE_DETAIL)
    session = await db.get(AssessmentSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    session_owner = await db.get(User, session.user_id)
    if session_owner is None or not can_access_user(user, session_owner):
        raise HTTPException(status_code=403, detail="无权访问此会话")
    result = await db.execute(
        select(DialogueTurn)
        .where(DialogueTurn.session_id == session_id)
        .order_by(DialogueTurn.timestamp.asc())
    )
    turns = result.scalars().all()
    return [
        {
            "id": t.id,
            "sessionId": t.session_id,
            "role": t.role,
            "content": t.content,
            "timestamp": t.timestamp,
        }
        for t in turns
    ]


@router.post(
    "/{session_id}/audio-chunks",
    response_model=AudioChunkOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_audio_chunk(
    session_id: str,
    chunk_index: int = Form(..., ge=0),
    started_at_ms: int = Form(0, ge=0),
    ended_at_ms: int = Form(0, ge=0),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传单个录音分片；相同会话和序号重复上传时覆盖元数据，不重复插入。"""
    session = await _get_session(session_id, db)
    _ensure_session_owner(session, user)
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="会话已结束，不能继续上传音频")
    if not SAFE_SESSION_ID.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="会话 ID 格式不合法")

    mime_type = (file.content_type or "application/octet-stream").split(";", 1)[0].lower()
    if mime_type not in ALLOWED_AUDIO_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"不支持的音频格式：{mime_type}")

    content = await file.read(settings.AUDIO_CHUNK_MAX_BYTES + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=400, detail="音频分片不能为空")
    if len(content) > settings.AUDIO_CHUNK_MAX_BYTES:
        raise HTTPException(status_code=413, detail="音频分片超过大小限制")

    extension = {
        "audio/webm": ".webm",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
    }.get(mime_type, ".bin")
    audio_root = settings.audio_upload_path
    session_dir = audio_root / session_id
    await asyncio.to_thread(session_dir.mkdir, parents=True, exist_ok=True)
    target_path = session_dir / f"chunk-{chunk_index:06d}{extension}"
    await asyncio.to_thread(target_path.write_bytes, content)
    storage_path = target_path.relative_to(audio_root).as_posix()

    result = await db.execute(
        select(AudioChunk).where(
            AudioChunk.session_id == session_id,
            AudioChunk.chunk_index == chunk_index,
        )
    )
    chunk = result.scalar_one_or_none()
    if chunk is None:
        chunk = AudioChunk(
            session_id=session_id,
            chunk_index=chunk_index,
            storage_path=storage_path,
            original_filename=file.filename or "",
            mime_type=mime_type,
            size_bytes=len(content),
            started_at_ms=started_at_ms,
            ended_at_ms=max(ended_at_ms, started_at_ms),
        )
        db.add(chunk)
    else:
        chunk.storage_path = storage_path
        chunk.original_filename = file.filename or chunk.original_filename
        chunk.mime_type = mime_type
        chunk.size_bytes = len(content)
        chunk.started_at_ms = started_at_ms
        chunk.ended_at_ms = max(ended_at_ms, started_at_ms)

    if session.status == "preparation":
        session.status = "in_progress"
    await db.flush()
    await db.refresh(chunk)
    return AudioChunkOut.model_validate(chunk)


@router.post(
    "/{session_id}/transcripts",
    response_model=list[TranscriptSegmentOut],
    status_code=status.HTTP_201_CREATED,
)
async def save_transcript_segments(
    session_id: str,
    data: TranscriptBatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """批量保存最终转录片段；客户端片段 ID 保证重试幂等。"""
    session = await _get_session(session_id, db)
    _ensure_session_owner(session, user)
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="会话已结束，不能继续保存转录")

    client_ids = [item.client_segment_id for item in data.segments]
    result = await db.execute(
        select(TranscriptSegment).where(
            TranscriptSegment.session_id == session_id,
            TranscriptSegment.client_segment_id.in_(client_ids),
        )
    )
    existing = {
        item.client_segment_id: item
        for item in result.scalars().all()
    }

    saved: list[TranscriptSegment] = []
    for item in data.segments:
        segment = existing.get(item.client_segment_id)
        if segment is None:
            segment = TranscriptSegment(
                session_id=session_id,
                client_segment_id=item.client_segment_id,
            )
            db.add(segment)
        segment.text = item.text.strip()
        segment.started_at_ms = item.started_at_ms
        segment.ended_at_ms = max(item.ended_at_ms, item.started_at_ms)
        segment.is_final = item.is_final
        segment.source = item.source
        saved.append(segment)

    if session.status == "preparation":
        session.status = "in_progress"
    await db.flush()
    for segment in saved:
        await db.refresh(segment)
    return [TranscriptSegmentOut.model_validate(item) for item in saved]


@router.post(
    "/{session_id}/events",
    response_model=list[InteractionEventOut],
    status_code=status.HTTP_201_CREATED,
)
async def save_interaction_events(
    session_id: str,
    data: InteractionEventBatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """批量幂等保存测评交互事件。"""
    session = await db.get(AssessmentSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    _ensure_session_owner(session, user)

    client_ids = [item.client_event_id for item in data.events]
    result = await db.execute(
        select(InteractionEvent).where(
            InteractionEvent.session_id == session_id,
            InteractionEvent.client_event_id.in_(client_ids),
        )
    )
    existing = {
        item.client_event_id: item
        for item in result.scalars().all()
    }
    new_items = [
        item for item in data.events
        if item.client_event_id not in existing
    ]
    if session.status == "completed" and new_items:
        raise HTTPException(status_code=409, detail="会话已结束，不能追加交互事件")

    saved: list[InteractionEvent] = []
    for item in data.events:
        event = existing.get(item.client_event_id)
        if event is None:
            event = InteractionEvent(
                session_id=session_id,
                client_event_id=item.client_event_id,
                sequence_no=item.sequence_no,
                event_type=item.event_type,
                occurred_at_ms=item.occurred_at_ms,
                client_timestamp_ms=item.client_timestamp_ms,
                source="browser",
                payload=item.payload or None,
            )
            db.add(event)
        saved.append(event)

    if new_items and session.status == "preparation":
        session.status = "in_progress"
    await db.flush()
    for event in saved:
        await db.refresh(event)
    return [InteractionEventOut.model_validate(item) for item in saved]


@router.get(
    "/{session_id}/events",
    response_model=list[InteractionEventOut],
)
async def list_interaction_events(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按实验时间线返回交互事件；学生本人及获授权教师/管理员可查看。"""
    session = await db.get(AssessmentSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    session_owner = await db.get(User, session.user_id)
    if session_owner is None or not can_access_user(user, session_owner):
        raise HTTPException(status_code=403, detail="无权访问此会话")
    result = await db.execute(
        select(InteractionEvent)
        .where(InteractionEvent.session_id == session_id)
        .order_by(
            InteractionEvent.sequence_no.asc(),
            InteractionEvent.occurred_at_ms.asc(),
            InteractionEvent.created_at.asc(),
        )
    )
    return [
        InteractionEventOut.model_validate(item)
        for item in result.scalars().all()
    ]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取会话详情（含全部对话与编码）"""
    session = await _get_session(session_id, db)
    session_owner = await db.get(User, session.user_id)
    if session_owner is None or not can_access_user(user, session_owner):
        raise HTTPException(status_code=403, detail="无权访问此会话")
    return await _session_to_out(session, db)


@router.post("/{session_id}/message", response_model=AgentResponse)
async def send_message(
    session_id: str,
    data: DialogueTurnIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """记录一轮被试发言；正式任务不自动触发 AI 追问或实时编码。"""
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=LEGACY_DIALOGUE_DETAIL)
    session = await _get_session(session_id, db)
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作此会话")

    if session.status == "completed":
        raise HTTPException(status_code=400, detail="会话已结束")

    if session.status == "preparation":
        session.status = "in_progress"

    # 记录用户消息
    user_msg = DialogueTurn(
        session_id=session.id,
        role="user",
        content=data.content,
        audio_url=data.audio_url,
        timestamp=int(time.time() * 1000),
        emotion_features=data.emotion_features.model_dump() if data.emotion_features else None,
    )
    db.add(user_msg)
    await db.flush()

    decision = protocol_agent.handle(ProtocolEvent.PARTICIPANT_TURN)
    agent_reply = decision.message or ""
    coded_out = None

    await db.refresh(session)

    # WebSocket 只通知新发言已记录，不向正式任务注入自由生成内容。
    await manager.send(session_id, {
        "type": "participant_turn_recorded",
        "message": agent_reply,
        "coded_segment": None,
    })

    return AgentResponse(
        message=agent_reply,
        coded_segment=coded_out,
        session_status=session.status,
    )


@router.post("/{session_id}/complete", response_model=SessionOut)
async def complete_session(
    session_id: str,
    data: SessionCompleteIn | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """完成测评会话；等待前端上传队列结束后调用，重复调用安全。"""
    session = await _get_session(session_id, db)
    _ensure_session_owner(session, user)
    payload = data or SessionCompleteIn()
    if session.status == "completed":
        return await _session_to_out(session, db)

    audio_count = await db.scalar(
        select(func.count(AudioChunk.id)).where(AudioChunk.session_id == session_id)
    ) or 0
    transcript_count = await db.scalar(
        select(func.count(TranscriptSegment.id)).where(
            TranscriptSegment.session_id == session_id,
            TranscriptSegment.is_final.is_(True),
        )
    ) or 0
    if payload.expected_audio_chunks and audio_count < payload.expected_audio_chunks:
        raise HTTPException(
            status_code=409,
            detail=f"音频分片尚未上传完成：{audio_count}/{payload.expected_audio_chunks}",
        )
    if payload.expected_transcript_segments and transcript_count < payload.expected_transcript_segments:
        raise HTTPException(
            status_code=409,
            detail=f"转录片段尚未保存完成：{transcript_count}/{payload.expected_transcript_segments}",
        )

    chunks_result = await db.execute(
        select(AudioChunk)
        .where(AudioChunk.session_id == session_id)
        .order_by(AudioChunk.chunk_index.asc())
    )
    try:
        await ensure_asr_job(
            session,
            list(chunks_result.scalars().all()),
            db,
        )
    except AudioManifestError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "message": str(error)},
        ) from error

    session.status = "completed"
    session.end_time = utc_now_naive()
    session.elapsed_minutes = max(
        session.elapsed_minutes,
        math.ceil(payload.elapsed_seconds / 60) if payload.elapsed_seconds else 0,
    )
    await db.flush()
    return await _session_to_out(await _get_session(session_id, db), db)


# ---- WebSocket 端点 ----

@router.websocket("/{session_id}/ws")
async def session_websocket(websocket: WebSocket, session_id: str):
    """WebSocket 实时对话通道"""
    await websocket.close(code=4404, reason=LEGACY_DIALOGUE_DETAIL["message"])
    return
    token = websocket.query_params.get("token", "")
    payload = decode_token(token)
    user_id = payload.get("sub") if payload else None
    if not user_id or not SAFE_SESSION_ID.fullmatch(session_id):
        await websocket.close(code=4401)
        return

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        session = await db.get(AssessmentSession, session_id)
        if (
            user is None
            or not user.is_active
            or (
                user.must_change_password
                and payload.get("password_change_deferred") is not True
            )
            or int(payload.get("ver", -1)) != user.token_version
            or session is None
        ):
            await websocket.close(code=4401)
            return
        session_owner = await db.get(User, session.user_id)
        if session_owner is None or not can_access_user(user, session_owner):
            await websocket.close(code=4403)
            return

    await manager.connect(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # 客户端可以通过 WebSocket 发送消息，由上层 API 处理
            await manager.send(session_id, {"type": "echo", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(session_id)


# ---- 辅助 ----

async def _get_session(session_id: str, db: AsyncSession) -> AssessmentSession:
    result = await db.execute(
        select(AssessmentSession)
        .where(AssessmentSession.id == session_id)
        .options(
            selectinload(AssessmentSession.dialogue_turns),
            selectinload(AssessmentSession.coded_segments),
            selectinload(AssessmentSession.audio_chunks),
            selectinload(AssessmentSession.transcript_segments),
            selectinload(AssessmentSession.interaction_events),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


def _ensure_session_owner(session: AssessmentSession, user: User) -> None:
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作此会话")


async def _session_to_out(session: AssessmentSession, db: AsyncSession) -> SessionOut:
    return SessionOut(
        id=session.id,
        user_id=session.user_id,
        task_id=session.task_id,
        run_id=session.run_id,
        sequence_no=session.sequence_no,
        status=session.status,
        start_time=session.start_time,
        end_time=session.end_time,
        elapsed_minutes=session.elapsed_minutes,
        ai_agent_version=session.ai_agent_version,
        model_id=session.model_id,
        model_params=session.model_params,
        dialogue_turns=[
            DialogueTurnOut(
                id=t.id, session_id=t.session_id, role=t.role,
                content=t.content, audio_url=t.audio_url,
                timestamp=t.timestamp, emotion_features=t.emotion_features,
            ) for t in (session.dialogue_turns or [])
        ],
        coded_segments=[
            CodedSegmentOut.model_validate(s) for s in (session.coded_segments or [])
        ],
        audio_chunks=[
            AudioChunkOut.model_validate(item)
            for item in sorted(session.audio_chunks or [], key=lambda chunk: chunk.chunk_index)
        ],
        transcript_segments=[
            TranscriptSegmentOut.model_validate(item)
            for item in sorted(
                session.transcript_segments or [],
                key=lambda segment: (segment.started_at_ms, segment.created_at),
            )
        ],
        interaction_events=[
            InteractionEventOut.model_validate(item)
            for item in sorted(
                session.interaction_events or [],
                key=lambda event: (
                    event.sequence_no,
                    event.occurred_at_ms,
                    event.created_at,
                ),
            )
        ],
    )
