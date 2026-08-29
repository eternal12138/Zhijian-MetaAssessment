"""Verify an uploaded ZIP or extracted release using only Python's standard library.

python3 deploy/verify-release.py /path/to/release.zip
python3 deploy/verify-release.py /opt/metacognition --allow-retired

Hashes detect accidental damage/mixed versions, not malicious tampering. Compare
the ZIP SHA-256 with the value supplied separately by the release producer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile


REQUIRED = {
    "compose.yaml", "backend/Dockerfile", "frontend/Dockerfile",
    "backend/scripts/migrate_phase32.py", "backend/scripts/migrate_phase33.py", "backend/scripts/migrate_phase34.py",
    "backend/scripts/migrate_all.py", "backend/scripts/migrate_phase35.py", "backend/scripts/migrate_phase36.py",
    "backend/scripts/report_worker.py", "backend/app/services/report_jobs.py",
    "backend/app/services/report_evidence.py",
    "backend/app/services/metacognition_pattern.py",
    "backend/app/services/metacognition_measurement.py",
    "frontend/src/views/DashboardView.vue",
    "frontend/src/components/dashboard/MacroAnalyticsDashboard.vue",
    "frontend/public/release.json", "LICENSE", "NOTICE", "README_EN.md",
}


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe archive path: {name!r}")
    if path.as_posix() != name:
        raise ValueError(f"Non-canonical archive path: {name!r}")
    return name


def validate_manifest(manifest: dict) -> dict[str, dict]:
    if manifest.get("format_version") != 1:
        raise ValueError("Unsupported release manifest format")
    records = {}
    for record in manifest["files"]:
        name = safe_name(record["path"])
        if name in records:
            raise ValueError(f"Duplicate manifest path: {name}")
        parts = PurePosixPath(name).parts
        if any(part.startswith((".venv", "node_modules")) or part in {
            ".git", "uploads", "exports", "__pycache__", ".pytest_cache",
        } for part in parts):
            raise ValueError(f"Runtime data in release: {name}")
        if name.startswith("backend/models/") or (
            PurePosixPath(name).name.startswith(".env") and not name.endswith(".example")
        ):
            raise ValueError(f"Private configuration/artifact in release: {name}")
        records[name] = record
    if missing := REQUIRED - records.keys():
        raise ValueError(f"Required release files missing: {sorted(missing)}")
    for name in manifest.get("retired_files", []):
        safe_name(name)
        if name in records:
            raise ValueError(f"Retired file included: {name}")
    return records


def verify(path: Path, *, allow_retired: bool = False) -> dict:
    archive = zipfile.ZipFile(path) if path.is_file() else None
    try:
        if archive:
            names = [safe_name(item.filename) for item in archive.infolist()]
            if len(names) != len(set(names)):
                raise ValueError("Duplicate ZIP entries")
            manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
        else:
            manifest = json.loads((path / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        records = validate_manifest(manifest)
        if archive and set(names) != set(records) | {"RELEASE_MANIFEST.json"}:
            raise ValueError("ZIP entries do not exactly match manifest")
        for name, record in records.items():
            if archive:
                data = archive.read(name)
            else:
                file = path / name
                if file.is_symlink() or not file.resolve().is_relative_to(path.resolve()):
                    raise ValueError(f"Unsafe release file: {name}")
                data = file.read_bytes()
            if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError(f"Release file differs: {name}")
            if name.endswith(".sh") and (b"\r\n" in data or data.startswith(b"\xef\xbb\xbf")):
                raise ValueError(f"Linux shell file has invalid line endings: {name}")
        if not archive and not allow_retired:
            for name in manifest.get("retired_files", []):
                if (path / name).exists():
                    raise ValueError(f"Retired source remains; back up then remove: {name}")
        return {"release_id": manifest["release_id"], "file_count": len(records), "schema_phase": manifest["schema_phase"]}
    finally:
        if archive:
            archive.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--allow-retired", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(args.path, allow_retired=args.allow_retired)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Release verification FAILED: {error}\n")
    print("Release verification OK: " + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
