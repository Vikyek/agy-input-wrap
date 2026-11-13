"""Unit tests for ToonConverterPlugin inside agy-input-wrap."""

import json
from agy_input_wrap.plugins.toon_converter import ToonConverterPlugin
from agy_input_wrap.plugin_manager import PluginManager


def _ensure_converter(plugin: ToonConverterPlugin) -> None:
    """Provide a deterministic stub converter when optional toon-mcp is absent (e.g. CI)."""
    if plugin._converter_fn is None:
        plugin._converter_fn = lambda obj, aggressive=True: '{"_toon":"stub"}'


def test_toon_converter_pure_json():
    plugin = ToonConverterPlugin(min_chars=10)
    _ensure_converter(plugin)
    data = {"items": [{"id": i, "name": f"item_{i}"} for i in range(10)]}
    json_str = json.dumps(data)
    res = plugin.process_bracketed_paste(json_str)
    assert res is not None
    assert len(res) == 1
    assert b"_toon" in res[0].data


def test_toon_converter_embedded_json():
    plugin = ToonConverterPlugin(min_chars=10)
    _ensure_converter(plugin)
    data = {"items": [{"id": i, "name": f"item_{i}"} for i in range(10)]}
    json_str = json.dumps(data)
    text = f"Here is data:\n{json_str}\nProcess this please."
    res = plugin.process_bracketed_paste(text)
    assert res is not None
    assert b"_toon" in res[0].data
    assert b"Process this please." in res[0].data


def test_toon_plugin_manager_integration():
    mgr = PluginManager(load_builtins=True)
    toon_plugin = mgr.get("toon")
    assert toon_plugin is not None
    assert toon_plugin.enabled is True

    # Test disable
    mgr.disable("toon")
    assert toon_plugin.enabled is False
    res = mgr.process_bracketed_paste('{"foo": "bar"}')
    assert res is None
