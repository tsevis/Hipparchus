"""Cache housekeeping utilities."""

from __future__ import annotations

from pathlib import Path


def enforce_size_limit(cache_root: Path, max_size_mb: int) -> int:
    """Evict oldest cache files until root is under max size. Returns deleted count."""
    max_bytes = max_size_mb * 1024 * 1024
    files = [p for p in cache_root.rglob("*.bin") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime)

    total = sum(p.stat().st_size for p in files)
    removed = 0
    for path in files:
        if total <= max_bytes:
            break
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        total -= size
        removed += 1

    return removed


def clear_project_cache(cache_root: Path, project_prefix: str) -> int:
    """Remove cached files matching a project prefix in filename."""
    removed = 0
    for path in cache_root.rglob("*.bin"):
        if path.name.startswith(project_prefix):
            path.unlink(missing_ok=True)
            removed += 1
    return removed
