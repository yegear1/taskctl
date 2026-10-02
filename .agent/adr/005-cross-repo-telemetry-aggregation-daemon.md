# [ADR-005] Cross-Repository Telemetry Aggregation Daemon & Status Broadcaster

- **Status:** Approved
- **Date:** 2026-10-02
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
When orchestrating multi-agent development workflows across distributed or mono-repo satellite repositories, engineers and orchestrators lack unified visibility into task states, criteria progress, active models, and git commits across workspaces. Observers require a cross-repo aggregation daemon and broadcasting CLI that continuously monitors local workspaces, identifies task lifecycle transitions, and emits structured summaries to Vector/VictoriaLogs, agent canvas (Maestri), and team webhooks without crashing or blocking.

## 2. Decision Outcome
We implemented a cross-repo aggregation engine and background broadcasting daemon in `taskctl.telemetry`:
- **Workspace Discovery & State Tracking (`CrossRepoAggregator`):**
  - Discovers repositories from explicit `--watch` directory paths, scanning immediate subdirectories for `.agent/TASK.md`, or reading `TASKCTL_WATCH_REPOS` env var (with fallback to current repository).
  - Extracts typed snapshots (`WorkspaceState`) including active task ID, title, status, runtime profile/model, systems, criteria checklist completion, completed task count, and short git commit hash.
- **State Transition & Event Detection (`WorkspaceEvent`):**
  - Detects contract transitions across polling cycles: initial snapshots (`workspace_snapshot`), new workspace discoveries (`workspace_added`), active task swaps (`task_switched`), status changes (`task_status_changed`), checklist progress (`criteria_updated`), completions (`task_completed`), and commit updates (`workspace_commit`).
- **Fail-Safe Multi-Sink Broadcaster (`TelemetryBroadcaster`):**
  - Emits canonical VictoriaLogs events via `TelemetryEmitter` / `VectorSink` (`:8686/logs`) with workspace attributes and task IDs.
  - Sends notifications to Maestri agent canvas via `send_canvas_notification`.
  - Dispatches formatted payloads to Discord/Slack webhooks when `TASKCTL_WEBHOOK_URL` is configured.
  - Non-blocking and fail-safe: catches all sink errors, preventing daemon crashes under network drops.
- **Daemon Lifecycle & CLI Commands (`TelemetryDaemon`):**
  - `taskctl daemon [--watch <path>...] [--interval <sec>] [--once] [--json] [--no-canvas] [--no-vector] [--no-webhook]`:
    Runs long-running daemon with POSIX signal handlers (`SIGINT`, `SIGTERM`) or executes a single aggregation sweep (`--once`).
  - `taskctl broadcast [msg] [--watch <path>...] [--json]`:
    Aggregates cross-repo health roll-up and broadcasts on-demand summary across all sinks.

## 3. Alternatives Considered
- **File System INotify Watchers (`pyinotify` / `watchdog`):** Rejected to maintain zero non-standard external dependencies and ensure seamless cross-platform operation across Linux, macOS, and Windows/WSL2.
- **Centralized Server Architecture:** Rejected in favor of local client/daemon architecture that operates entirely hermetically using local workspace directories and standard standard-library capabilities.

## 4. Consequences and Trade-offs
### Positive
- Unified cross-workspace visibility across multiple repositories.
- Zero-dependency implementation adhering to Python 3.10+ standard library.
- Fail-safe telemetry delivery with zero risk of blocking developer or agent workflows.
- Rich terminal tables and machine-parseable JSON modes.

### Negative / Accepted Risks
- Polling-based aggregation incurs lightweight I/O on interval, throttled to a minimum of 0.5s (default 5.0s).

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/ECOSYSTEM.md](file:///home/yegear/github/taskctl/.agent/ECOSYSTEM.md)
- [.agent/TASK.md](file:///home/yegear/github/taskctl/.agent/TASK.md)
- [ADR-002](file:///home/yegear/github/taskctl/.agent/adr/002-vector-telemetry-sink.md)
- [ADR-004](file:///home/yegear/github/taskctl/.agent/adr/004-remote-agent-canvas-contract-integration.md)
