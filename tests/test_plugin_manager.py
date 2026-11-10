"""
Tests for PluginManager.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from agy_input_wrap.actions import WriteAction
from agy_input_wrap.plugin_base import InputPlugin
from agy_input_wrap.plugin_manager import PluginManager


class DummyPlugin(InputPlugin):
    name = "dummy"

    def process_input(self, data: bytes):
        if data == b"dummy_trigger":
            return [WriteAction(b"dummy_response")]
        return None


class TestPluginManager(unittest.TestCase):
    def test_registration_and_toggle(self) -> None:
        manager = PluginManager(load_builtins=False)
        self.assertEqual(len(manager.plugins), 0)

        dummy = DummyPlugin()
        manager.register(dummy)
        self.assertEqual(len(manager.plugins), 1)
        self.assertIs(manager.get("dummy"), dummy)

        # Trigger when enabled
        actions = manager.process_input(b"dummy_trigger")
        self.assertIsNotNone(actions)
        self.assertEqual(actions[0].data, b"dummy_response")

        # Disable
        manager.disable("dummy")
        self.assertFalse(dummy.enabled)
        self.assertIsNone(manager.process_input(b"dummy_trigger"))

        # Re-enable
        manager.enable("dummy")
        self.assertTrue(dummy.enabled)
        self.assertIsNotNone(manager.process_input(b"dummy_trigger"))

    def test_dynamic_directory_loading(self) -> None:
        manager = PluginManager(load_builtins=False)
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin_path = Path(tmp_dir) / "custom_test_plugin.py"
            plugin_path.write_text(
                "from agy_input_wrap.plugin_base import InputPlugin\n"
                "from agy_input_wrap.actions import WriteAction\n"
                "class DynamicPlugin(InputPlugin):\n"
                "    name = 'dynamic'\n"
                "    def process_input(self, data: bytes):\n"
                "        return [WriteAction(b'dynamic_out')] if data == b'dyn' else None\n"
            )

            loaded = manager.load_from_directory(Path(tmp_dir))
            self.assertEqual(loaded, 1)
            self.assertIsNotNone(manager.get("dynamic"))

            actions = manager.process_input(b"dyn")
            self.assertIsNotNone(actions)
            self.assertEqual(actions[0].data, b"dynamic_out")


if __name__ == "__main__":
    unittest.main()
