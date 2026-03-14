"""Filesystem helpers for sensitive wallet/config state."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None:
    """Atomically write text to a path with restrictive permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def chmod_if_exists(path: Path, mode: int = 0o600) -> None:
    """Best-effort chmod for sensitive files."""
    try:
        path.chmod(mode)
    except FileNotFoundError:
        return
