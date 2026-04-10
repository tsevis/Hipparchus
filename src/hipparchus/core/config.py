"""Typed configuration system for Hipparchus."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


ThemeMode = str


@dataclass(slots=True, frozen=True)
class AppConfig:
    """Application runtime configuration."""

    app_name: str
    theme_mode: ThemeMode
    cache_dir: Path
    plugins_dir: Path
    settings_file: Path
    presets_file: Path
    project_dir: Path
    default_width: int
    default_height: int
    provider_rps_limit: float


class ConfigLoader:
    """Loads application configuration from defaults and environment."""

    @staticmethod
    def load() -> AppConfig:
        home = Path.home()
        app_name = os.getenv("HIPPARCHUS_APP_NAME", "Hipparchus")
        theme_mode = os.getenv("HIPPARCHUS_THEME", "light").strip().lower() or "light"
        if theme_mode not in {"light", "dark"}:
            theme_mode = "light"

        cache_dir = Path(os.getenv("HIPPARCHUS_CACHE_DIR", str(home / ".hipparchus" / "cache")))
        plugins_dir = Path(os.getenv("HIPPARCHUS_PLUGINS_DIR", str(home / ".hipparchus" / "plugins")))
        project_dir = Path(os.getenv("HIPPARCHUS_PROJECT_DIR", str(home / ".hipparchus" / "projects")))
        settings_file = Path(os.getenv("HIPPARCHUS_SETTINGS_FILE", str(home / ".hipparchus" / "settings.json")))
        presets_file = Path(os.getenv("HIPPARCHUS_PRESETS_FILE", str(home / ".hipparchus" / "presets.json")))

        default_width = int(os.getenv("HIPPARCHUS_WINDOW_WIDTH", "1600"))
        default_height = int(os.getenv("HIPPARCHUS_WINDOW_HEIGHT", "1080"))
        provider_rps_limit = float(os.getenv("HIPPARCHUS_PROVIDER_RPS", "1.0"))

        return AppConfig(
            app_name=app_name,
            theme_mode=theme_mode,
            cache_dir=cache_dir,
            plugins_dir=plugins_dir,
            settings_file=settings_file,
            presets_file=presets_file,
            project_dir=project_dir,
            default_width=default_width,
            default_height=default_height,
            provider_rps_limit=provider_rps_limit,
        )
