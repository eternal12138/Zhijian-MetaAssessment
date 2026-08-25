from __future__ import annotations

import hashlib
import importlib
import logging
from pathlib import Path
from types import ModuleType


def source_revision(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path).encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"missing")
    return digest.hexdigest()


class IdleModuleReloader:
    """Reload worker-only modules between jobs without changing the worker PID."""

    def __init__(self, *, paths: tuple[Path, ...], modules: tuple[ModuleType, ...], name: str):
        self.paths = paths
        self.modules = modules
        self.name = name
        self.revision = source_revision(paths)

    def reload_if_changed(self) -> bool:
        current = source_revision(self.paths)
        if current == self.revision:
            return False
        logging.getLogger(self.name).warning("Worker source changed; reloading idle modules")
        importlib.invalidate_caches()
        for module in self.modules:
            importlib.reload(module)
        self.revision = source_revision(self.paths)
        return True
