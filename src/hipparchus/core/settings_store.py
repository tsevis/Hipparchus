"""Local settings persistence for Hipparchus."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass(slots=True)
class UserSettings:
    theme_mode: str = "light"
    performance_preview_tolerance: float = 1.5
    cache_size_limit_mb: int = 4096
    provider_rps_limit: float = 1.0


class SettingsStore:
    """Read/write user settings from JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> UserSettings:
        if not self.path.exists():
            return UserSettings()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return UserSettings(
            theme_mode=str(data.get("theme_mode", "light")),
            performance_preview_tolerance=float(data.get("performance_preview_tolerance", 1.5)),
            cache_size_limit_mb=int(data.get("cache_size_limit_mb", 4096)),
            provider_rps_limit=float(data.get("provider_rps_limit", 1.0)),
        )

    def save(self, settings: UserSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
