"""Plugin interfaces and loaded plugin descriptor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class Plugin(Protocol):
    """Plugin contract for runtime registration."""

    id: str
    name: str

    def register(self) -> None:
        """Register plugin capabilities into runtime registries."""


@dataclass(slots=True, frozen=True)
class LoadedPlugin:
    """Result of plugin loading operation."""

    id: str
    name: str
    module: str
