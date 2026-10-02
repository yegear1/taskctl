# NOTES.md — Project Decisions, Context, and Contracts

> Stores the WHY. The WHAT lives in `git log` / `TASK.md`. Record only entries that explain
> an architectural decision or gotcha; do not include changelogs.

---

## How to Use

1. Read before planning. Decisions here take precedence over "obvious defaults", unless explicitly revisited.
2. Record: trade-offs, contracts, gotchas, new skills, deliberate technical debt.
3. Lengthy entries $\rightarrow$ formal ADR in `.agent/adr/` and only one line + link here.

---

## Formal ADRs

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](adr/001-modular-cli-architecture.md) | Modular CLI Architecture & Fail-Safe Webhook Dispatcher | Approved | 2026-10-01 |
| [ADR-002](adr/002-vector-telemetry-sink.md) | VictoriaLogs & Vector Direct Sink Integration with Provider Telemetry | Approved | 2026-10-01 |
| [ADR-003](adr/003-conventional-commits-policy.md) | Conventional Commits Policy Engine & Scope Auditor Integration | Approved | 2026-10-01 |
| [ADR-004](adr/004-remote-agent-canvas-contract-integration.md) | Remote Agent Canvas Contract Engine Integration & Maestri IPC | Approved | 2026-10-01 |

---

## Quick Decisions

### 2026-10-01 Greenfield Baseline Scaffolding
- **Context:** Establishing the official repository foundation for `taskctl`.
- **Decision:** Adopt the ADD Greenfield template from `ye-sandbox/template-agent` (branch `greenfield`).
- **Consequences:** All task lifecycle and agent interactions adhere to standard ADD contracts (`.agent/TASK.md`, `.agent/ECOSYSTEM.md`, `.agent/skills/`).

### 2026-10-01 Non-Blocking Webhook Telemetry
- **Context:** Sending lifecycle notifications to external dashboards or vector sinks.
- **Decision:** Implement fail-safe background dispatching with strict 2-second timeout.
- **Consequences:** Developer or agent commits and task transitions are never blocked or aborted by telemetry network failures.

### 2026-10-01 Open Contract Engine & Explicit multigravity-cli Separation
- **Context:** Preventing domain bloat and overlap between `taskctl` and `multigravity-cli`.
- **Decision:** `taskctl` remains an open, generic CLI for task lifecycle governance (`TASK.md`, DoD, and scope audit). Quota monitoring, multi-profile switching, and worktree balancing belong exclusively to [`multigravity-cli`](https://github.com/yegear1/multigravity-cli). `taskctl` interfaces via a lightweight provider adapter (`taskctl.providers.multigravity`). Future TUI/dashboards in `taskctl` will focus strictly on task states and DoD checklist, avoiding quota dashboard duplication.
- **Consequences:** Clean separation of concerns; zero vendor lock-in for general open source users, with turn-key interoperability for the multigravity ecosystem.

### 2026-10-01 Automated Conventional Commits Policy & Scope Auditor Integration
- **Context:** Ensuring commit history consistency for changelog generators and release auditing without external npm/pip dependencies.
- **Decision:** Implement standard Conventional Commits 1.0.0 parser in `taskctl.core.commits`, wire `CommitConventionRule` into `ScopeAuditor`, add `taskctl lint-commit` CLI, and guard `taskctl done`.
- **Consequences:** Hermetic commit validation with zero external dependencies; full support for Git `commit-msg` hooks.

### 2026-10-01 Remote Agent Canvas Contract Engine Integration & Maestri IPC
- **Context:** Enabling bidirectional sync between local repository task contracts and remote spatial agent canvas (Maestri).
- **Decision:** Implement `MaestriIPCClient` using UNIX domain sockets with CLI fallback, supporting bidirectional note syncing (`taskctl sync [--push|--pull]`), remote canvas workspace provisioning (`taskctl ws`), agent planning delegation (`taskctl plan`), and fail-safe canvas notifications (`taskctl notify`).
- **Consequences:** Real-time visibility and control across agent canvas with zero risk of developer blocking if Maestri is offline.

---

## Active Contracts

| Channel / Route | Producer | Consumer | Payload |
|---|---|---|---|
| `.agent/TASK.md` | `taskctl` / Agent | `taskctl.core.parser` | Markdown AST task schema |
| `taskctl audit` | `taskctl` | CI / Git Pre-commit | Exit codes: `0: APPROVED`, `1: CHANGES REQUIRED`, `2: REJECTED` |
| `taskctl lint-commit` | `taskctl` | Git `commit-msg` / CI | Exit codes: `0: APPROVED`, `1: CHANGES REQUIRED` |
| `WebhookDispatcher` | `taskctl` | Telemetry Endpoint | JSON Task Lifecycle Event |
| `VectorSink` | `taskctl` | Vector HTTP Ingestion (`:8686/logs`) | Canonical VictoriaLogs NDJSON/JSON |
| `MaestriIPCClient` / CLI | `taskctl` | Maestri Spatial Canvas | JSON-RPC / CLI notes & workspace commands |

---

## Gotchas & Pitfalls

- **Parser Flexibility:** Section headers like `## Backlog` or `## Backlog (Upcoming, in priority order)` must be parsed robustly without failing on parenthesized comments.
- **Zero-Crash Telemetry:** Never raise exceptions if `TASKCTL_WEBHOOK_URL` is unreachable or returns 5xx.

---

## Deliberate Technical Debt

| Debt | Rationale | Revisit When |
|---|---|---|
| Basic `git diff --check` in audit | Fast initial gate for git hygiene without heavy linter setup | When custom domain lint rules are requested |
