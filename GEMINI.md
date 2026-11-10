# Workspace Rules: agy-input-wrap

## Project Overview
`agy-input-wrap` is a decoupled, high-performance PTY input interceptor and modular plugin architecture for `antigravity-cli` (`agy`).
Author: Vikyek (solo indie author).

## Architecture & Design Principles
- **Decoupled Architecture**: Zero external dependencies beyond Python 3 standard library. Do not mix into `toon-wrap` or `toon-mcp`.
- **PTY Transparency**: Runs target binaries inside a transparent PTY proxy with proper raw mode (`tty.setraw`), `SIGWINCH` forwarding, and guaranteed termios restoration via exit handlers and `try...finally`.
- **Zero Added Latency**: Unmatched keystrokes and single-line commands must pass through directly with 0ms added delay.
- **Modular Plugin Engine**: Extensible plugins subclassing `InputPlugin` in `agy_input_wrap/plugins/` or custom plugin directories.
- **Non-blocking Timing**: Timed action sequences (`WriteAction`, `SleepAction`) use `select()` timer wakeups to never freeze child stdout rendering or terminal resizing.

## Verification
Run tests before committing changes:
```bash
PYTHONPATH=. python3 -m unittest discover -v -s tests
```
