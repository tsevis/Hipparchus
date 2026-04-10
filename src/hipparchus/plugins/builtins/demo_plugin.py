"""Demo plugin used to validate loader wiring."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DemoPlugin:
    """Minimal built-in plugin implementation."""

    id: str = "builtin.demo"
    name: str = "Demo Builtin"

    def register(self) -> None:
        return None


def create_plugin() -> DemoPlugin:
    """Plugin factory expected by PluginLoader."""
    return DemoPlugin()
