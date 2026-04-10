"""Runtime plugin discovery and loading."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import pkgutil
from pathlib import Path
import sys
from types import ModuleType

from hipparchus.plugins.interfaces import LoadedPlugin, Plugin


@dataclass(slots=True)
class PluginLoader:
    """Loads built-in and user plugins with fault isolation."""

    builtin_package: str
    user_plugin_dir: Path
    loaded_plugins: list[LoadedPlugin] = field(default_factory=list)
    load_errors: list[str] = field(default_factory=list)

    def load_all(self) -> None:
        self._load_builtin_plugins()
        self._load_user_plugins()

    def _load_builtin_plugins(self) -> None:
        package = importlib.import_module(self.builtin_package)
        for module_info in pkgutil.iter_modules(package.__path__, prefix=f"{self.builtin_package}."):
            self._load_from_module_name(module_info.name)

    def _load_user_plugins(self) -> None:
        if not self.user_plugin_dir.exists() or not self.user_plugin_dir.is_dir():
            return

        sys.path.insert(0, str(self.user_plugin_dir))
        try:
            for module_info in pkgutil.iter_modules([str(self.user_plugin_dir)]):
                self._load_from_module_name(module_info.name)
        finally:
            if sys.path and sys.path[0] == str(self.user_plugin_dir):
                sys.path.pop(0)

    def _load_from_module_name(self, module_name: str) -> None:
        try:
            module = importlib.import_module(module_name)
            plugin = self._extract_plugin(module)
            if plugin is None:
                self.load_errors.append(f"{module_name}: missing create_plugin()")
                return
            plugin.register()
            self.loaded_plugins.append(
                LoadedPlugin(id=plugin.id, name=plugin.name, module=module_name)
            )
        except Exception as exc:  # noqa: BLE001
            self.load_errors.append(f"{module_name}: {exc}")

    @staticmethod
    def _extract_plugin(module: ModuleType) -> Plugin | None:
        factory = getattr(module, "create_plugin", None)
        if factory is None:
            return None
        plugin = factory()
        if not isinstance(plugin, Plugin):
            return None
        return plugin
