# agy-input-wrap

Clean, high-performance, decoupled PTY input interceptor and modular plugin architecture for [`antigravity-cli`](https://github.com/google-deepmind/antigravity-cli) (`agy`).

---

## 🎯 Purpose

When using `antigravity-cli` with interactive terminal UIs (BubbleTea / Lipgloss), pasting or submitting a multiline input such as:

```text
/add-dir /path/to/project
Please inspect this directory and fix the bug
```

often pastes both lines directly into the prompt textarea as a single multiline blob, rather than first running the `/add-dir` workspace addition command and then submitting the prompt.

`agy-input-wrap` transparently intercepts terminal inputs:
1. **Detects** `/add-dir <path>\n<prompt>` (both typed multiline and bracketed paste).
2. **Feeds** `/add-dir <path>\r` into the child PTY so the TUI processes it as an immediate slash command.
3. **Pauses** briefly (configurable, default 200ms) to allow the BubbleTea TUI to switch/add the workspace directory.
4. **Feeds** `<prompt>\r` into the child PTY.
5. If `/add-dir <path>` has no following newline/text (e.g. single-line execution), it passes through **untouched**.
6. All other terminal input passes through with **zero added latency**.

---

## 🏗️ Architecture

```
Terminal (User)
       │
       ▼ (stdin raw mode)
┌─────────────────────────────────────────────────────────────┐
│                       agy-input-wrap                        │
│                                                             │
│  ┌─────────────────────────┐   ┌─────────────────────────┐  │
│  │ StreamProcessor         │──▶│ PluginManager           │  │
│  │ (Bracketed paste & raw) │   │ (AddDirSequencerPlugin) │  │
│  └─────────────────────────┘   └─────────────────────────┘  │
│               │                                             │
│               ▼                                             │
│  ┌─────────────────────────┐                                │
│  │ ActionScheduler         │ (Non-blocking timed queue)     │
│  │ WriteAction / Sleep     │                                │
│  └─────────────────────────┘                                │
│               │                                             │
└───────────────┼─────────────────────────────────────────────┘
                ▼ (master PTY)
        ┌───────────────┐
        │  /usr/bin/agy │  (Child process in slave PTY)
        └───────────────┘
```

- **Zero External Dependencies**: Built entirely using Python 3 standard library (`pty`, `termios`, `tty`, `select`, `fcntl`, `signal`).
- **Complete Decoupling**: Standalone utility; does not depend on or modify `toon-mcp` or `toon-wrap`.
- **PTY Transparency**: Runs child in its own session (`setsid`), forwards window resizing (`SIGWINCH`), and guarantees terminal state restoration via `try...finally` and `atexit` handlers.
- **Non-blocking Delays**: Delays use `select()` timer wakeups in the event loop, ensuring child stdout rendering and screen redraws never freeze during pauses.

---

## 📦 Installation

### Automatic Installation

Run the bundled installation script to create a symlink in `~/.local/bin`:

```bash
git clone https://github.com/Vikyek/agy-input-wrap.git ~/Projects/agy-input-wrap
cd ~/Projects/agy-input-wrap
./install.sh
```

### Manual Installation

Alternatively, link or copy the executable directly:

```bash
mkdir -p ~/.local/bin
ln -sf ~/Projects/agy-input-wrap/bin/agy-input-wrap ~/.local/bin/agy-input-wrap
chmod +x ~/.local/bin/agy-input-wrap
```

Verify the installation:

```bash
agy-input-wrap --version
agy-input-wrap --list-plugins
```

### Agensi & Agent Skill Ingestion (`SKILL.md`)

`agy-input-wrap` is structured as a standard agent skill compliant with the open `SKILL.md` specification and compatible with the Agensi marketplace:
- Root [`SKILL.md`](SKILL.md) enables direct single-skill ingestion across Agensi, Antigravity, Claude Code, and Codex CLI.
- Modular skill definition located at [`skills/agy-input-wrap/SKILL.md`](skills/agy-input-wrap/SKILL.md).
- Teaches connected agents how to intercept, sequence, and tune terminal PTY streams to eliminate prompt truncation.

---

## 🔌 Chaining with `agy` and `toon-wrap`

`agy-input-wrap` cleanly chains with other terminal wrappers such as `toon-wrap` in `~/.local/bin/agy`:

```bash
# When toon-wrap is enabled:
toon-wrap -- /home/v/.local/bin/agy-input-wrap /usr/bin/agy "$@"

# When toon-wrap is disabled or absent:
/home/v/.local/bin/agy-input-wrap /usr/bin/agy "$@"
```

---

## ⚙️ Configuration & Environment Variables

| Setting | Type | Default | Description |
|---|---|---|---|
| `--delay-ms <MS>` | CLI flag | `200` | Delay between `/add-dir` and prompt execution (ms) |
| `AGY_ADD_DIR_DELAY_MS` | Env Var | `200` | Fallback delay if `--delay-ms` is not specified |
| `AGY_INPUT_WRAP_DISABLE` | Env Var | `0` | If set to `1`, bypasses wrapping and executes child directly |
| `--disable-plugin <NAME>` | CLI flag | `[]` | Disable specific plugin by name |
| `--plugin-dir <DIR>` | CLI flag | `[]` | Load custom plugins from directory |
| `--list-plugins` | CLI flag | - | Show registered plugins and exit |

---

## 🧩 Plugin System

You can create modular plugins by subclassing `InputPlugin`:

```python
from agy_input_wrap.plugin_base import InputPlugin
from agy_input_wrap.actions import WriteAction, SleepAction

class CustomPlugin(InputPlugin):
    name = "custom"

    def process_bracketed_paste(self, content: str):
        # Inspect or transform bracketed paste content
        return None

    def process_input(self, data: bytes):
        # Inspect or transform raw streaming input
        return None
```

Place custom plugins in `~/.config/agy-input-wrap/plugins/*.py` or pass via `--plugin-dir`.

---

## 🧪 Testing

Run the full automated test suite (including unit tests and mock PTY tests):

```bash
PYTHONPATH=. python3 -m unittest discover -v -s tests
```

Tests cover:
- Passthrough of normal keystrokes and text (0 latency).
- Passthrough of single-line `/add-dir /foo`.
- Splitting and delay sequencing of `/add-dir /foo\nbar` (both plain and bracketed paste).
- Action scheduler and non-blocking timers.
- Plugin management and dynamic directory loading.


---

## Support & Sponsorship

`agy-input-wrap` is authored and maintained by **[Vikyek](https://github.com/Vikyek)** as an independent open-source project. Everything is 100% open-source, telemetry-free, and public.

<div align="center">


[![Sponsor Vikyek](https://img.shields.io/badge/Sponsor-%E2%9D%A4-ea4aaa?logo=github&style=for-the-badge)](https://github.com/sponsors/Vikyek)
[![Donate on Liberapay](https://img.shields.io/badge/Donate-Liberapay-f6c915?style=for-the-badge&logo=liberapay&logoColor=black)](https://liberapay.com/Vikyek)
[![Donate with Stripe](https://img.shields.io/badge/Donate-Stripe-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://profile.stripe.com/@vikyek)

</div>

> ### 🎯 Active Sponsorship Goal: Monthly Living Essentials
> **Target:** **2,710 PLN / ~$680 USD per month** (`630 PLN / week`) — Rent & Essential Utilities  
> Covering basic living essentials directly unlocks dedicated, sustainable full-time independent open-source engineering across Arch Linux utilities, developer tools, and AI middleware free from corporate telemetry, ads, or paywalls.

If this project saves you time, optimizes your setup, or accelerates your workflow, consider supporting ongoing work:

- **GitHub Sponsors**: [github.com/sponsors/Vikyek](https://github.com/sponsors/Vikyek) *(Monthly tiers and one-time tips)*
- **Liberapay**: [liberapay.com/Vikyek](https://liberapay.com/Vikyek) *(0% platform fee recurrent patronage in EUR/USD/PLN)*
- **Direct Stripe Profile**: [profile.stripe.com/@vikyek](https://profile.stripe.com/@vikyek) *(Direct one-time tips & sponsorship)*

Every contribution—monthly or one-time—directly supports active maintenance, hardware testbeds, and new feature development!

---

## 📄 License

MIT © [Vikyek](https://github.com/Vikyek)
