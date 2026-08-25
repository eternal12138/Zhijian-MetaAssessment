"""Build and validate a tamper-evident audio chunk manifest."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from app.models.session import AudioChunk


class AudioManifestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ManifestChunk:
    chunk_index: int
    storage_path: str
    mime_type: str
    size_bytes: int
    started_at_ms: int
    ended_at_ms: int
    sha256: str


@dataclass(frozen=True)
class AudioManifest:
    schema_version: str
    session_id: str
    chunk_count: int
    mime_type: str
    chunks: tuple[ManifestChunk, ...]
    manifest_hash: str

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_file(audio_root: Path, storage_path: str) -> Path:
    root = audio_root.resolve()
    candidate = (root / storage_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise AudioManifestError(
            "unsafe_storage_path", "音频分片路径超出受控存储目录"
        ) from error
    if not candidate.is_file():
        raise AudioManifestError(
            "chunk_file_missing", f"音频分片文件不存在：{storage_path}"
        )
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_audio_manifest(
    session_id: str,
    chunks: Iterable[AudioChunk],
    audio_root: Path,
) -> AudioManifest:
    ordered = sorted(chunks, key=lambda item: item.chunk_index)
    if not ordered:
        raise AudioManifestError("audio_required", "测评结束前必须上传录音分片")

    actual_indices = [item.chunk_index for item in ordered]
    expected_indices = list(range(len(ordered)))
    if actual_indices != expected_indices:
        raise AudioManifestError(
            "chunk_sequence_incomplete",
            f"音频分片序号不完整，期望 {expected_indices}，实际 {actual_indices}",
        )

    manifest_chunks: list[ManifestChunk] = []
    mime_types: set[str] = set()
    previous_end = 0
    for chunk in ordered:
        if chunk.ended_at_ms < chunk.started_at_ms:
            raise AudioManifestError(
                "invalid_chunk_time", f"分片 {chunk.chunk_index} 时间范围无效"
            )
        # MediaRecorder can deliver a final pre-pause chunk after resume, and
        # older clients restarted their local clock after restoring a session.
        # Chunk index remains authoritative for concatenation, so normalize
        # diagnostic timing rather than rejecting otherwise intact audio.
        normalized_start = max(chunk.started_at_ms, previous_end)
        normalized_end = max(chunk.ended_at_ms, normalized_start)
        previous_end = normalized_end
        path = _safe_file(audio_root, chunk.storage_path)
        actual_size = path.stat().st_size
        if actual_size <= 0 or actual_size != chunk.size_bytes:
            raise AudioManifestError(
                "chunk_size_mismatch",
                f"分片 {chunk.chunk_index} 文件尺寸与数据库记录不一致",
            )
        mime_types.add(chunk.mime_type)
        manifest_chunks.append(ManifestChunk(
            chunk_index=chunk.chunk_index,
            storage_path=chunk.storage_path,
            mime_type=chunk.mime_type,
            size_bytes=chunk.size_bytes,
            started_at_ms=normalized_start,
            ended_at_ms=normalized_end,
            sha256=_sha256(path),
        ))

    if len(mime_types) != 1:
        raise AudioManifestError(
            "mixed_chunk_formats", "同一会话的音频分片格式必须一致"
        )

    canonical = {
        "schema_version": "1.1",
        "session_id": session_id,
        "chunk_count": len(manifest_chunks),
        "mime_type": next(iter(mime_types)),
        "chunks": [asdict(item) for item in manifest_chunks],
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return AudioManifest(
        schema_version=canonical["schema_version"],
        session_id=session_id,
        chunk_count=len(manifest_chunks),
        mime_type=canonical["mime_type"],
        chunks=tuple(manifest_chunks),
        manifest_hash=hashlib.sha256(encoded).hexdigest(),
    )
