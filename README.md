# taskctl

🌐 **English | [Português](README.pt-br.md)**

**taskctl** is the Task Lifecycle, Contract Engine, and Multi-Agent Orchestration CLI for **Agent-Driven Development (ADD)**.

It provides a deterministic bridge between AI coding agents (Antigravity, Claude Code, Cursor, Windsurf, Maestri, Roo Code) and software repositories by enforcing structured task contracts (`.agent/TASK.md`), falsifiable Definitions of Done (DoD), non-blocking webhook telemetry, and orchestration integrations.

---

## ⚡ Key Capabilities

- **📋 Task Lifecycle Orchestration:** Deterministic CLI commands to plan, start, audit, and complete tasks with atomic double-commits (feature commit + governance update).
- **🛡️ Scope Auditor (`taskctl audit`):** Semantic gatekeeper returning exit codes for automated CI/pre-commit checks:
  - `0`: **APPROVED** — Ready for completion.
  - `1`: **CHANGES REQUIRED** — Actionable corrections needed.
  - `2`: **REJECTED** — Critical policy violation; escalates to planner/human.
- **📡 Non-Blocking Telemetry:** Background webhook dispatcher with timeouts and circuit-breaker isolation, ensuring network drops never abort commits or developer workflows.
- **🔌 Pluggable Provider Adapters:** Native support for external platforms such as Maestri spatial canvases and [`multigravity-cli`](https://github.com/yegear1/multigravity-cli) for quota-aware profile routing.
- **🌐 Open & Decoupled Architecture:** `taskctl` strictly governs task contracts and lifecycle states. It leaves multi-profile quota tracking and worktree balancing to external tools like `multigravity-cli` without hard dependencies.
- **🌿 Greenfield & Brownfield Compliance:** 100% compliant with the `ye-sandbox/template-agent` governance and Markdown AST specification.

---

## 🚀 Quickstart

### Installation

Install in editable mode for local development:

```bash
git clone https://github.com/yegear1/taskctl.git
cd taskctl
pip install -e .
```

Verify installation:

```bash
taskctl --help
```

---

## 💻 CLI Commands

| Command | Description |
| :--- | :--- |
| `taskctl init` | Initialize `.agent/TASK.md` and `AGENTS.md` in the current repository. |
| `taskctl status` | Display the active task, acceptance criteria, git status, and quota route. |
| `taskctl plan "<prompt>"` | Request planner decomposition of upcoming tasks into `.agent/TASK.md`. |
| `taskctl next [--weight]` | Promote the next backlog task to `RUNNING` status and notify agent. |
| `taskctl audit` | Run Scope Auditor verification on staged diffs and git hygiene. |
| `taskctl done [message]` | Validate DoD, generate feature commit + governance log commit, and dispatch webhook. |
| `taskctl sync` | Sync active `.agent/TASK.md` status to Maestri canvas cockpit note. |
| `taskctl quota` | Inspect real-time Multigravity profile quotas and balancing recommendation. |
| `taskctl ws [name]` | Provision and wire a Maestri workspace for the current repository. |
| `taskctl notify <msg>` | Dispatch an ad-hoc event via configured webhook. |

---

## 📁 Architecture & Project Structure

```text
taskctl/
├── .agent/                  # ADD governance contracts & playbooks
│   ├── adr/                 # Architecture Decision Records
│   ├── skills/              # Domain-specific operational skills
│   ├── ECOSYSTEM.md         # Multi-repo topology matrix
│   ├── INVARIANTS.md        # System invariants
│   ├── NOTES.md             # Decisions, active contracts, and gotchas
│   ├── TASK.md              # Current task and roadmap (canonical AST)
│   └── ARCHIVE.md           # Completed task log archive
├── AGENTS.md                # Agent directives & DoD standards
├── pyproject.toml           # PEP 517/518/621 packaging
├── taskctl/
│   ├── __init__.py          # Package metadata
│   ├── cli.py               # CLI entrypoint & subcommands
│   ├── core/
│   │   ├── __init__.py
│   │   └── parser.py        # Strict Markdown parser & serializer
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── maestri.py       # Maestri canvas IPC adapter
│   │   └── multigravity.py  # Multigravity quota routing adapter
│   └── webhooks/
│       ├── __init__.py
│       └── dispatcher.py    # Non-blocking telemetry event dispatcher
└── tests/                   # Hermetic automated test suite
    ├── test_parser.py
    └── test_webhooks.py
```

---

## 🧪 Testing & Verification

Run the test suite and strict syntax check:

```bash
# Syntax check
python3 -m py_compile $(find taskctl -name "*.py")

# Hermetic test suite
python3 -m unittest discover tests

# Git cleanliness check
git diff --check
```

---

## 📄 License

MIT © [yegear](https://github.com/yegear)
