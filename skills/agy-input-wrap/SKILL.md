---
name: agy-input-wrap
description: >-
  Clean, high-performance PTY terminal input interceptor and prompt optimizer
  for AI coding CLIs (antigravity-cli, claude-code, codex, aider). Sequences
  slash commands like /add-dir before multi-line prompts, prevents bracketed
  paste buffer truncation, and compresses terminal input noise.
version: 1.0.0
summary: >-
  PTY input interceptor and prompt optimizer sequencing slash commands before
  multiline prompts and preventing bracketed paste buffer truncation in AI CLIs.
tags:
  - prompt-skill-engineering
  - llm-ops
  - workflow-automation
  - terminal-middleware
keywords:
  - pty-wrapper
  - bracketed-paste
  - input-sequencing
  - antigravity-cli
  - terminal-optimizer
  - token-reduction
  - agy-input-wrap
use_cases:
  - Preventing multiline pasted prompts from eating slash commands in terminal TUIs
  - Sequencing directory additions and configuration flags before submitting prompt payloads
  - Chaining transparently with toon-wrap and AI coding CLIs to eliminate input corruption
---

# Terminal Input Optimizer & PTY Wrapper (`agy-input-wrap`)

`agy-input-wrap` is a decoupled, zero-latency PTY terminal interceptor and prompt optimizer designed for interactive terminal coding agents (such as `antigravity-cli`, `claude-code`, `codex`, `aider`).

## Problem Solved

When working with terminal coding agents using rich TUI frameworks (BubbleTea, Lipgloss, Prompt Toolkit), pasting multi-line text containing a slash command and a prompt:

```text
/add-dir /path/to/project
Please inspect this directory and fix the bug
```

often dumps both lines simultaneously into the prompt textarea as a single multiline string blob. The agent never executes `/add-dir` as a command, causing missing workspace context and failed executions.

`agy-input-wrap` transparently intercepts the PTY stream:
1. **Detects** `/add-dir <path>\n<prompt>` (both typed multiline and bracketed paste).
2. **Feeds** `/add-dir <path>\r` into the child PTY so the TUI processes it as an immediate slash command.
3. **Pauses** briefly (configurable, default 200ms) non-blocking via `select()` to allow the TUI to switch/add the workspace directory.
4. **Feeds** `<prompt>\r` into the child PTY.
5. All other terminal input passes through with **zero added latency**.

---

## When to Activate

Activate this skill when:
- Setting up or troubleshooting terminal wrappers for AI coding CLIs.
- Fixing prompt truncation, dropped slash commands, or multiline paste bugs in terminal TUIs.
- Chaining input middleware with token compressors (`toon-wrap`).
- Creating custom input preprocessing plugins (e.g. prompt normalization, sensitive input masking).

---

## Quickstart & Chaining

### 1. Installation

```bash
cd ~/Projects/agy-input-wrap
./install.sh
```

Verify the installation:
```bash
agy-input-wrap --version
agy-input-wrap --list-plugins
```

### 2. Chaining with `agy` and `toon-wrap`

To chain `agy-input-wrap` with `toon-wrap` (payload compression) and `agy` (the agent CLI):

```bash
# In ~/.local/bin/agy:
toon-wrap -- /home/v/.local/bin/agy-input-wrap /usr/bin/agy "$@"

# Or standalone:
agy-input-wrap /usr/bin/agy "$@"
```

### 3. Configuration & Tuning

| Flag / Env Var | Default | Purpose |
|---|---|---|
| `--delay-ms <MS>` / `AGY_ADD_DIR_DELAY_MS` | `200` | Delay between slash command and prompt submission (ms) |
| `AGY_INPUT_WRAP_DISABLE=1` | `0` | Completely bypass interceptor and run child directly |
| `--list-plugins` | - | List active input plugins |
| `--disable-plugin <NAME>` | `[]` | Disable a specific plugin |
| `--plugin-dir <DIR>` | `[]` | Load custom modular plugins |

### 4. Custom Plugin Development

Create custom input handlers by subclassing `InputPlugin`:

```python
from agy_input_wrap.plugin_base import InputPlugin

class PromptSanitizerPlugin(InputPlugin):
    name = "prompt-sanitizer"

    def process_bracketed_paste(self, content: str):
        # Inspect or transform bracketed paste content
        return None

    def process_input(self, data: bytes):
        # Inspect or transform raw streaming bytes
        return None
```
