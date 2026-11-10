"""
CLI interface and argument parsing for agy-input-wrap.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Optional, Sequence

from agy_input_wrap import __version__
from agy_input_wrap.engine import run_pty_proxy
from agy_input_wrap.plugin_manager import PluginManager


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser for agy-input-wrap."""
    parser = argparse.ArgumentParser(
        prog="agy-input-wrap",
        description=(
            "Run an interactive CLI inside a modular PTY proxy that intercepts and "
            "sequences multiline commands such as /add-dir for antigravity-cli."
        ),
    )
    parser.add_argument(
        "--delay-ms",
        type=float,
        default=None,
        help="Delay in milliseconds between sequenced commands (default: 200).",
    )
    parser.add_argument(
        "--disable-plugin",
        action="append",
        default=[],
        metavar="NAME",
        help="Disable a specific plugin by name (can be specified multiple times).",
    )
    parser.add_argument(
        "--plugin-dir",
        action="append",
        default=[],
        type=Path,
        metavar="DIR",
        help="Load additional plugins from the specified directory.",
    )
    parser.add_argument(
        "--list-plugins",
        action="store_true",
        help="List available plugins and exit.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Target command and arguments to execute (optionally preceded by '--').",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for agy-input-wrap."""
    parser = build_parser()
    args = parser.parse_args(argv)

    manager = PluginManager()

    # Load custom plugin directories
    default_config_plugins = Path.home() / ".config" / "agy-input-wrap" / "plugins"
    if default_config_plugins.is_dir():
        manager.load_from_directory(default_config_plugins)

    for p_dir in args.plugin_dir:
        manager.load_from_directory(p_dir)

    # Configure plugins
    if args.delay_ms is not None:
        manager.configure_plugin("add_dir_sequencer", delay_sec=args.delay_ms / 1000.0)

    # Disable specified plugins
    for disabled in args.disable_plugin:
        manager.disable(disabled)

    if args.list_plugins:
        print("Registered agy-input-wrap plugins:")
        for p in manager.plugins:
            status = "enabled" if p.enabled else "disabled"
            print(f"  - {p.name} [{status}]")
        return 0

    cmd = list(args.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]

    if not cmd:
        parser.print_help(sys.stderr)
        return 2

    # Environment bypass check
    if os.environ.get("AGY_INPUT_WRAP_DISABLE") == "1":
        os.execvp(cmd[0], cmd)

    return run_pty_proxy(cmd, manager)


if __name__ == "__main__":
    sys.exit(main())
