"""Merge browser chunks and transcode them to canonical 16 kHz mono PCM WAV."""
from __future__ import annotations

import shutil
import subprocess
import hashlib
import math
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from app.services.audio_manifest import AudioManifest


class AudioProcessingError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProcessedAudio:
    source_path: str
    canonical_path: str
    duration_ms: int
    rms_dbfs: float | None
    peak_dbfs: float | None
    contains_signal: bool
    size_bytes: int
    sha256: str


EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "application/octet-stream": ".bin",
}


def _resolve_ffmpeg(configured: str) -> str:
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    discovered = shutil.which(configured)
    if discovered:
        return discovered
    if configured.strip().lower() == "ffmpeg":
        try:
            import imageio_ffmpeg

            bundled = Path(imageio_ffmpeg.get_ffmpeg_exe())
            if bundled.is_file():
                return str(bundled.resolve())
        except (ImportError, RuntimeError, OSError):
            pass
    raise AudioProcessingError(
        "ffmpeg_not_found",
        "未找到 FFmpeg，请安装后将 FFMPEG_PATH 配置为可执行文件路径",
    )


def _relative(audio_root: Path, path: Path) -> str:
    return path.resolve().relative_to(audio_root.resolve()).as_posix()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze_pcm16_signal(path: Path) -> tuple[float | None, float | None, bool]:
    """Measure signal level without retaining or exposing audio content."""
    sample_count = 0
    sum_squares = 0
    peak = 0
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getsampwidth() != 2:
                raise AudioProcessingError(
                    "invalid_canonical_audio",
                    "转码后的 WAV 不是 16 位 PCM 音频",
                )
            while True:
                frames = audio.readframes(16_384)
                if not frames:
                    break
                samples = array("h")
                samples.frombytes(frames)
                if sys.byteorder != "little":
                    samples.byteswap()
                sample_count += len(samples)
                sum_squares += sum(sample * sample for sample in samples)
                peak = max(
                    peak,
                    max((abs(sample) for sample in samples), default=0),
                )
    except (wave.Error, OSError) as error:
        raise AudioProcessingError(
            "invalid_canonical_audio", "转码后的 WAV 文件无法读取"
        ) from error

    rms = math.sqrt(sum_squares / sample_count) if sample_count else 0.0
    rms_dbfs = round(20 * math.log10(rms / 32768), 2) if rms else None
    peak_dbfs = round(20 * math.log10(peak / 32768), 2) if peak else None
    contains_signal = bool(
        rms_dbfs is not None
        and peak_dbfs is not None
        and rms_dbfs > -60
        and peak_dbfs > -50
    )
    return rms_dbfs, peak_dbfs, contains_signal


def merge_and_transcode(
    manifest: AudioManifest,
    audio_root: Path,
    ffmpeg_path: str,
) -> ProcessedAudio:
    output_dir = (audio_root / manifest.session_id / "asr").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = manifest.manifest_hash[:20]
    suffix = EXTENSIONS.get(manifest.mime_type, ".bin")
    source = output_dir / f"{stem}-source{suffix}"
    canonical = output_dir / f"{stem}-16k-mono.wav"
    source_tmp = source.with_suffix(source.suffix + ".tmp")
    canonical_tmp = output_dir / f"{stem}-16k-mono.tmp.wav"

    if len(manifest.chunks) > 1 and manifest.mime_type == "audio/wav":
        raise AudioProcessingError(
            "segmented_wav_unsupported",
            "多段独立 WAV 不能直接拼接，请使用浏览器 WebM/MP4/OGG 分片",
        )

    root = audio_root.resolve()
    with source_tmp.open("wb") as target:
        for chunk in manifest.chunks:
            chunk_path = (root / chunk.storage_path).resolve()
            try:
                chunk_path.relative_to(root)
            except ValueError as error:
                raise AudioProcessingError(
                    "unsafe_storage_path", "音频分片路径超出受控目录"
                ) from error
            with chunk_path.open("rb") as stream:
                shutil.copyfileobj(stream, target, length=1024 * 1024)
    source_tmp.replace(source)

    ffmpeg = _resolve_ffmpeg(ffmpeg_path)
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(canonical_tmp),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode != 0 or not canonical_tmp.is_file():
        canonical_tmp.unlink(missing_ok=True)
        detail = (result.stderr or "FFmpeg 转码失败").strip()[-1500:]
        raise AudioProcessingError("ffmpeg_transcode_failed", detail)
    canonical_tmp.replace(canonical)

    try:
        with wave.open(str(canonical), "rb") as audio:
            duration_ms = round(audio.getnframes() / audio.getframerate() * 1000)
    except (wave.Error, OSError, ZeroDivisionError) as error:
        raise AudioProcessingError(
            "invalid_canonical_audio", "转码后的 WAV 文件无法读取"
        ) from error
    if duration_ms <= 0:
        raise AudioProcessingError("empty_canonical_audio", "转码后的音频时长为零")
    rms_dbfs, peak_dbfs, contains_signal = analyze_pcm16_signal(canonical)
    return ProcessedAudio(
        source_path=_relative(audio_root, source),
        canonical_path=_relative(audio_root, canonical),
        duration_ms=duration_ms,
        rms_dbfs=rms_dbfs,
        peak_dbfs=peak_dbfs,
        contains_signal=contains_signal,
        size_bytes=canonical.stat().st_size,
        sha256=file_sha256(canonical),
    )
