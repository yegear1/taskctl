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
| [ADR-005](adr/005-cross-repo-telemetry-aggregation-daemon.md) | Cross-Repository Telemetry Aggregation Daemon & Status Broadcaster | Approved | 2026-10-02 |
| [ADR-006](adr/006-task-dependency-graph-engine.md) | Task Dependency Graph Engine, Visualizers, and Cycle Detection Policy | Approved | 2026-10-02 |
| [ADR-007](adr/007-task-lifecycle-distributed-tracing.md) | Task Lifecycle Distributed Tracing, Telemetry Spans & SLA Alerting | Approved | 2026-10-02 |

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

### 2026-10-02 Cross-Repository Telemetry Aggregation Daemon & Status Broadcaster
- **Context:** Providing continuous cross-workspace visibility and real-time status broadcasting across local satellite repositories without crashing or blocking.
- **Decision:** Implement `CrossRepoAggregator`, `TelemetryBroadcaster`, and `TelemetryDaemon` in `taskctl.telemetry`, along with CLI commands `taskctl daemon` and `taskctl broadcast`.
- **Consequences:** Hermetic, fail-safe polling and broadcasting of task lifecycle events and summaries to Vector, Canvas, and Webhooks.

### 2026-10-02 Task Dependency Graph Engine & Cycle Detection
- **Context:** Preventing execution deadlocks, cycle loops, and visualizing project progression across active, backlog, and completed tasks.
- **Decision:** Implement `TaskDependencyGraph` in `taskctl.core.graph` supporting explicit markdown prerequisites (`- **Depends On:**`, `(deps: ...)`), implicit sequential fallback for epics/subtasks, cycle detection via DFS coloring, ASCII tree visualization, Mermaid generation, and interactive TUI DAG view (`taskctl graph`, `taskctl ui --dag`).
- **Consequences:** 100% hermetic DAG validation and visualization with zero non-standard external dependencies.

### 2026-10-02 Task Lifecycle Distributed Tracing & Telemetry Spans
- **Context:** Tracing multi-agent lifecycle phases, measuring operation latencies, and alerting on SLA violations without heavy external dependencies.
- **Decision:** Implement W3C-compatible `TraceContext`, `Span`, `Tracer`, and `DurationAnalyzer` in `taskctl.telemetry.tracing`, auto-enriching `TelemetryEvent` and `VectorSink` payloads with `trace_id`, `span_id`, and `parent_span_id`, while triggering fail-safe `sla_alert` events on threshold breach (`taskctl trace`).
- **Consequences:** Deterministic distributed tracing and SLA alerting across all CLI subcommands and agent hand-offs with zero third-party dependencies.

---

## Active Contracts

| Channel / Route | Producer | Consumer | Payload |
|---|---|---|---|
| `.agent/TASK.md` | `taskctl` / Agent | `taskctl.core.parser` | Markdown AST task schema |
| `taskctl audit` | `taskctl` | CI / Git Pre-commit | Exit codes: `0: APPROVED`, `1: CHANGES REQUIRED`, `2: REJECTED` |
| `taskctl lint-commit` | `taskctl` | Git `commit-msg` / CI | Exit codes: `0: APPROVED`, `1: CHANGES REQUIRED` |
| `taskctl graph` | `taskctl` | CLI / CI / Markdown Docs | ASCII Tree, Mermaid `graph TD`, JSON, or Exit Code (`0: Clean`, `1: Cycle`) |
| `taskctl trace` | `taskctl` | CLI / CI / Developer | ASCII Waterfall Tree, Trace Spans JSON, or SLA duration analytics |
| `taskctl daemon` / `broadcast` | `taskctl` | Vector / Canvas / Webhook | Aggregated Cross-Repo Workspace Events & Status Summary |
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
