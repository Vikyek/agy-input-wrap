"""
Plugin registry and dispatch manager for agy-input-wrap.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Optional, Sequence

from agy_input_wrap.actions import Action
from agy_input_wrap.plugin_base import InputPlugin
from agy_input_wrap.plugins.add_dir_sequencer import AddDirSequencerPlugin
from agy_input_wrap.plugins.toon_converter import ToonConverterPlugin


class PluginManager:
    """Manages active interceptor plugins and dispatches input hooks."""

    def __init__(self, load_builtins: bool = True) -> None:
        self._plugins: list[InputPlugin] = []
        if load_builtins:
            self.register(AddDirSequencerPlugin())
            self.register(ToonConverterPlugin())

    @property
    def plugins(self) -> Sequence[InputPlugin]:
        """Return registered plugins."""
        return list(self._plugins)

    def register(self, plugin: InputPlugin) -> None:
        """Register a plugin instance."""
        # Replace existing plugin with same name if present
        self._plugins = [p for p in self._plugins if p.name != plugin.name]
        self._plugins.append(plugin)

    def unregister(self, name: str) -> None:
        """Unregister a plugin by name."""
        self._plugins = [p for p in self._plugins if p.name != name]

    def get(self, name: str) -> Optional[InputPlugin]:
        """Find a plugin by name."""
        for p in self._plugins:
            if p.name == name:
                return p
        return None

    def enable(self, name: str) -> bool:
        """Enable a plugin by name."""
        p = self.get(name)
        if p:
            p.enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a plugin by name."""
        p = self.get(name)
        if p:
            p.enabled = False
            return True
        return False

    def configure_plugin(self, name: str, **kwargs: Any) -> bool:
        """Configure parameters for a specific plugin."""
        p = self.get(name)
        if p:
            p.configure(**kwargs)
            return True
        return False

    def load_from_directory(self, dir_path: Path) -> int:
        """
        Dynamically load plugins from a directory containing Python files.
        Returns the number of loaded plugins.
        """
        if not dir_path.is_dir():
            return 0

        count = 0
        for py_file in dir_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            module_name = f"agy_input_wrap_plugin_{py_file.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    # Look for InputPlugin subclasses
                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, InputPlugin)
                            and attr is not InputPlugin
                        ):
                            self.register(attr())
                            count += 1
            except Exception:
                continue

        return count

    def process_bracketed_paste(self, content: str) -> Optional[Sequence[Action]]:
        """Dispatch bracketed paste to enabled plugins."""
        for p in self._plugins:
            if not p.enabled:
                continue
            res = p.process_bracketed_paste(content)
            if res is not None:
                return res
        return None

    def process_input(self, data: bytes) -> Optional[Sequence[Action]]:
        """Dispatch raw input bytes to enabled plugins."""
        for p in self._plugins:
            if not p.enabled:
                continue
            res = p.process_input(data)
            if res is not None:
                return res
        return None
