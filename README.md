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
- **✅ Conventional Commits (`taskctl lint-commit`):** Hermetic commit-message policy for `commit-msg` hooks and CI, with no external linter dependency.
- **📡 Non-Blocking Telemetry:** Background webhook and Vector sinks. Network drops, invalid endpoints, and timeouts never abort commits or status updates.
- **📈 Dependency Graph & Tracing:** `taskctl graph` (ASCII, Mermaid, JSON, cycle check) and `taskctl trace` (W3C-style spans and SLA duration alerts).
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
| `taskctl backlog` | List upcoming backlog items. |
| `taskctl plan "<prompt>"` | Request planner decomposition of upcoming tasks into `.agent/TASK.md`. |
| `taskctl next [light\|medium\|heavy] [--agent <name>] [--no-handoff]` | Promote the next backlog task to `RUNNING` and hand off to the builder. |
| `taskctl audit [--delegate] [--agent <name>] [--domain-lint]` | Run Scope Auditor on staged diffs and git hygiene. Exit `0` / `1` / `2`. `--domain-lint` or `TASKCTL_DOMAIN_LINT=1` also checks that the active task has non-empty acceptance criteria. |
| `taskctl lint-commit [msg] [--file <path>] [--rev <rev>] [--range <range>]` | Validate a message against Conventional Commits. Alias: `commit-lint`. |
| `taskctl done [message] [-p] [--agent <name>] [--no-handoff]` | Validate DoD, create the feature commit and the governance commit, dispatch webhook. |
| `taskctl graph [--mermaid\|--json\|--check-cycles] [--file <path>]` | Render the task dependency DAG. Exit `1` when a cycle is found. |
| `taskctl dashboard [--snapshot] [--split] [--dag]` | Terminal view of the active task, DoD, and audit. Alias: `tui`. |
| `taskctl trace [--last] [--id <trace_id>] [--analytics] [--json]` | Show trace spans, a waterfall, and SLA duration metrics. |
| `taskctl daemon [--watch <path>] [--once] [--json]` | Poll watched repos and broadcast lifecycle events. |
| `taskctl broadcast [msg] [--watch <path>] [--json]` | Send one cross-repo status roll-up to Vector, canvas, and webhook. |
| `taskctl sync [--pull]` | Push or pull the active task note on the Maestri canvas. |
| `taskctl quota` | Inspect Multigravity profile quotas and the balancing recommendation. |
| `taskctl ws [name] [--preset <name>] [--workers <n>]` | Provision a Maestri workspace. Presets: `trinity`, `swarm`, `audit`. |
| `taskctl notify <msg>` | Dispatch an ad-hoc event via the configured webhook. |

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
│   ├── cli.py               # CLI entrypoint and subcommands
│   ├── core/                # Parser, scope auditor, commits, dependency graph
│   ├── providers/           # Maestri IPC and multigravity quota adapters
│   ├── telemetry/           # Vector sink, cross-repo daemon, tracing
│   ├── tui/                 # Terminal dashboard
│   └── webhooks/            # Non-blocking lifecycle event dispatcher
└── tests/                   # Hermetic suite (parser, audit, graph, telemetry, TUI)
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

GitHub Actions (`.github/workflows/ci.yml`) runs the same gates on Python 3.10–3.13, plus `taskctl audit` and `taskctl lint-commit`.

---

## 📄 License

MIT © [yegear](https://github.com/yegear)
