# Architecture Decision Records — taskctl

Consolidated chronological log of architectural decisions for taskctl.

---

# [ADR-001] Modular CLI Architecture & Fail-Safe Webhook Dispatcher

- **Status:** Approved
- **Date:** 2026-10-01
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
Autonomous AI coding agents frequently degrade when executing long tasks or performing automated releases if tooling is monolithic, brittle, or fails abruptly due to network drops, missing daemon sockets, or schema drift in governance files (`.agent/TASK.md`). `taskctl` must serve as the hermetic task lifecycle engine, contract validator, and multi-agent dispatcher without blocking or aborting developer workflows.

## 2. Decision Outcome
We adopted a modular Python architecture partitioned into:
- `taskctl.core`: Strict Markdown AST parsing, `.agent/TASK.md` contract validation, and DoD evaluation.
- `taskctl.providers`: Resilient adapters for multi-agent platforms (Maestri IPC, Multigravity quota balancer) with graceful degradations when daemons are offline.
- `taskctl.webhooks`: Asynchronous, non-blocking telemetry event dispatching with circuit breakers and timeout guards.
- `taskctl.cli`: Ergonomic CLI entrypoint exposing semantic subcommands (`init`, `status`, `plan`, `next`, `audit`, `done`).

## 3. Alternatives Considered
- **Monolithic Single-File CLI (`taskctl.py`):** Rejected due to untestable side-effects, tightly coupled external dependencies, and poor maintainability.
- **Synchronous HTTP Webhooks:** Rejected because any network timeout or unreachable listener would block Git commits or crash `taskctl done`.

## 4. Consequences and Trade-offs
### Positive
- Strict typing and isolated unittests across core, providers, and webhooks.
- Zero side-effects when remote providers or webhook endpoints are offline.
- High compatibility across Linux, macOS, and Windows/WSL2.

### Negative / Accepted Risks
- Multi-file distribution requires `pyproject.toml` packaging (`pip install -e .` or package distribution).

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/INVARIANTS.md](file:///home/yegear/github/taskctl/.agent/INVARIANTS.md)

---

# [ADR-002] VictoriaLogs & Vector Direct Sink Integration with Provider Telemetry

- **Status:** Approved
- **Date:** 2026-10-01
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
In multi-agent environments, tasks transition through critical lifecycles (`task_started`, `audit`, `task_completed`), and external orchestrator provider calls (`multigravity`, `maestri`) incur variable latencies or sporadic daemon disconnects. Observability is essential to analyze agent performance, quota routing latencies, and scope audit verdicts without polluting commit history or risking CLI downtime when observability sinks are unreachable.

## 2. Decision Outcome
We implemented a dedicated telemetry subsystem in `taskctl.telemetry` featuring:
1. **Canonical Schema:** Strict adherence to the `ye-sandbox` VictoriaLogs contract (`timestamp` UTC ISO-8601 with millisecond precision, lowercase `level`, `service`, `app`, `env`, `message`, and `duration_ms`). High-cardinality values (`task_id`, `details`) are strictly kept as event attributes, preventing stream dimension explosions.
2. **Direct Vector Sink (`VectorSink`):** Connects to Vector's HTTP input endpoint (`:8686/logs` or configurable via `TASKCTL_VECTOR_URL`/`VECTOR_URL`) sending atomic JSON log objects.
3. **Fail-Safe & Non-Blocking Execution:** Strict 2-second timeout and exception encapsulation ensuring telemetry failures never interrupt CLI execution or block git operations (satisfying System Invariant 3).
4. **Provider Latency Tracing:** Instrumentation of `multigravity` and `maestri` providers to record `duration_ms`, execution status, and operation metadata.
5. **NDJSON Stream Support:** Optional stdout NDJSON emission (`TASKCTL_LOG_NDJSON=1`) for containerized or stream-piped environments.

## 3. Alternatives Considered
- **Direct VictoriaLogs Insertion (`:9428/insert/jsonline`):** Bypassing Vector was rejected because Vector provides edge aggregation, stream tagging, VRL validation, and compression across the homelab infrastructure.
- **Synchronous Telemetry Blocking:** Rejected to maintain absolute adherence to System Invariant 3 (fail-safe and non-blocking).

## 4. Consequences and Trade-offs
### Positive
- Unified observability across CLI lifecycle actions and provider operations.
- Zero network blocking when sinks are down or network is disconnected.
- Hermetic testability with standard library mocking.

### Negative / Accepted Risks
- Network timeouts up to 2 seconds if a configured endpoint hangs (mitigated by configuring `TASKCTL_TELEMETRY_TIMEOUT` and default non-configured state).

## 5. References and Links
- [ADR-001: Modular CLI Architecture](file:///home/yegear/github/taskctl/.agent/adr/001-modular-cli-architecture.md)
- [VictoriaLogs Integration Skill](file:///home/yegear/AntigravityProfiles/yegear/.gemini/config/skills/victorialogs-integration/SKILL.md)
- [.agent/INVARIANTS.md](file:///home/yegear/github/taskctl/.agent/INVARIANTS.md)

---

# [ADR-003] Conventional Commits Policy Engine & Scope Auditor Integration

- **Status:** Approved
- **Date:** 2026-10-01
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
In autonomous multi-agent development and CI/CD pipelines, inconsistent or unstructured git commit messages degrade automated changelog generation, SemVer release calculations, and release auditing. Furthermore, non-standard commit messages violate repository engineering standards (`AGENTS.md`). An automated, hermetic policy engine is required to validate Conventional Commits both during git hooks (`commit-msg`), during Scope Auditor verification (`taskctl audit`), and before completing task lifecycle transitions (`taskctl done`).

## 2. Decision Outcome
We implemented a dedicated Conventional Commits parser and policy engine in `taskctl.core.commits` compliant with the Conventional Commits 1.0.0 specification:
- **Core Parser & AST:** `parse_conventional_commit` validates type, scope, breaking indicators (`!`, `BREAKING CHANGE:`), subject/description non-emptiness, maximum 100-character header length, and blank line separation before message body and footers.
- **Scope Auditor Rule:** `CommitConventionRule` is added to `ScopeAuditor` default verification chain, inspecting the repository's HEAD commit message on every `taskctl audit`.
- **CLI Subcommand:** `taskctl lint-commit [msg] [--file <path>]` provides turn-key integration for Git's `commit-msg` hook or manual message linting, returning semantic exit codes (`0: APPROVED`, `1: CHANGES REQUIRED`).
- **Atomic Transition Guard:** `taskctl done [custom_msg]` enforces Conventional Commits validation on custom commit messages prior to executing git commits, aborting if violations are found.

## 3. Alternatives Considered
- **External Node.js / Python Linters (`commitlint`, `gitlint`):** Rejected because `taskctl` must remain hermetic and lightweight with zero external runtime dependencies.
- **Audit-only Verification:** Rejected because catching formatting errors only after commit creation causes unnecessary git amends or rollback cycles. Adding `lint-commit` enables pre-commit and hook-level enforcement.

## 4. Consequences and Trade-offs
### Positive
- Zero external package dependencies (pure Python standard library).
- Immediate feedback in Git `commit-msg` hooks, CI runners, and Scope Auditor.
- Prevents non-standard commits from entering repository history.

### Negative / Accepted Risks
- Enforces strict Conventional Commit types (`feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`), requiring contributors and agents to adhere strictly to the convention.

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/TASK.md](file:///home/yegear/github/taskctl/.agent/TASK.md)
- [.agent/NOTES.md](file:///home/yegear/github/taskctl/.agent/NOTES.md)
- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)

---

# [ADR-004] Remote Agent Canvas Contract Engine Integration & Maestri IPC

- **Status:** Approved
- **Date:** 2026-10-01
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
Autonomous multi-agent orchestration frameworks (such as Maestri) feature a 2D spatial canvas with interconnected agent terminals, notes, and browser portals. While `taskctl` maintains the source of truth for task contracts, invariants, and Definition of Done in local markdown (`.agent/TASK.md`), remote canvas agents and human observers require real-time visibility into the active task cockpit, bidirectional synchronization with canvas notes, workspace provisioning, and non-blocking inter-agent notification and delegation.

## 2. Decision Outcome
We implemented a resilient, non-blocking remote agent canvas provider adapter in `taskctl.providers.maestri`:
- **Dual Transport Discovery (UNIX Domain Socket IPC & CLI Fallback):**
  - `MaestriIPCClient` manages low-latency communication via UNIX domain sockets, discovering paths through `MAESTRI_SOCKET_PATH`, `MAESTRI_SOCKET`, and uid-based socket matching (`/tmp/maestri-{uid}/maestri.sock`).
  - Graceful fallback to `maestri` CLI (`MAESTRI_CLI`, `~/.local/bin/maestri`, `/usr/local/bin/maestri`, or PATH) when the domain socket is unavailable.
- **Fail-Safe & Non-Blocking Resilience:**
  - All socket operations enforce strict 2.0-second timeouts and catch all socket exceptions (`ConnectionRefusedError`, `FileNotFoundError`, etc.).
  - Maestri unavailability never blocks local git commands, task promotions, or task completions.
  - Duration and success metrics are emitted to VictoriaLogs / Vector telemetry sinks via `record_provider_call(provider="maestri", ...)`.
- **Bidirectional Note Synchronization:**
  - Pushing (`taskctl sync` / `--push`) writes or creates the pinned `task-cockpit-agent-task-md` note on the canvas.
  - Pulling (`taskctl sync --pull`) reads the canvas note and validates the markdown schema prior to updating local `.agent/TASK.md`.
  - Line prefix normalization (`strip_note_line_numbers`) safely parses line-numbered outputs from CLI `note read`.
- **Remote Canvas Workspace & Agent Delegation:**
  - `taskctl ws [name]`: Provisions a dedicated Maestri workspace rooted at the repository directory and initializes the canvas cockpit note.
  - `taskctl plan "<prompt>"`: Sets active task status to `PLANNING` and delegates decomposition to the connected `Planner` agent on the canvas.
  - `taskctl notify <msg>`: Dispatches notifications to the Maestri canvas alongside configured Webhooks and Vector sinks.

## 3. Alternatives Considered
- **Direct Filesystem Manipulation of Maestri State:** Rejected because Maestri manages internal canvas geometry, ropes, and session states. Direct socket/CLI contracts ensure high fidelity and safety.
- **Synchronous Blocking Remote Calls:** Rejected because any network latency or daemon downtime would violate Rule 3 of the Rule Precedence Hierarchy (Fail-Safe & Non-Blocking Execution).

## 4. Consequences and Trade-offs
### Positive
- Real-time bidirectional synchronization between local repository governance and the spatial agent canvas.
- Zero-crash fallback when Maestri is not installed or when running in headless CI environments.
- 100% hermetically testable using standard Python mocks.

### Negative / Accepted Risks
- Canvas note pulls require valid TASK.md markdown schemas; corrupt notes are rejected to prevent local file damage.

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/ECOSYSTEM.md](file:///home/yegear/github/taskctl/.agent/ECOSYSTEM.md)
- [.agent/TASK.md](file:///home/yegear/github/taskctl/.agent/TASK.md)
- [.agent/skills/provider-adapter/SKILL.md](file:///home/yegear/github/taskctl/.agent/skills/provider-adapter/SKILL.md)

---

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

---

# [ADR-006] Task Dependency Graph Engine, Visualizers, and Cycle Detection Policy

- **Status:** Approved
- **Date:** 2026-10-02
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
In multi-agent and complex engineering lifecycles, tasks across active contracts, completed logs, and upcoming backlogs frequently have strict topological ordering constraints. Without an automated dependency engine:
1. Agents risk executing dependent tasks out of order or creating circular prerequisite deadlocks.
2. Humans and orchestrators cannot easily visualize project pipelines or DAG progression in terminal or documentation.
3. Contract specifications lacked a standardized, flexible Markdown schema for declaring prerequisites across active, backlog, and completed states.

## 2. Decision Outcome
We implemented a hermetic task dependency graph engine in `taskctl.core.graph`, enhanced markdown parsing in `taskctl.core.parser`, provided CLI visualization commands in `taskctl.cli`, and integrated an interactive DAG viewer into the terminal user interface:

- **Dependency Contract & Flexible Markdown Schema:**
  - **Active Task:** Supports `- **Depends On:** [04.1], [03.7]` or `- **Dependencies:** [04.1]`.
  - **Backlog & Log Items:** Supports annotations such as `(deps: [04.1])`, `(depends: [04.1])`, `(after: [04.1])`, and flexible formatting (`**[ID]**`, `` `[ID]` ``, or `[ID]`).
  - **Implicit Sequential Inference:** If no explicit dependencies are specified, tasks within an epic (`[XX.Y]`) sequentially depend on the preceding sequence item (`[XX.Y-1]`), and subtasks (`[XX.Y.Z]`) depend on their parent task (`[XX.Y]`), establishing natural DAG progression without redundant boilerplate.
- **Graph Engine & Cycle Detector (`taskctl.core.graph`):**
  - `TaskDependencyGraph`: Directed graph representation of `TaskNode` models (`id`, `title`, `status`, `section`, `dependencies`, `dependents`).
  - `find_cycles()` / `has_cycle()`: Deterministic cycle detection using DFS recursion coloring (white/gray/black), extracting normalized cycle paths to prevent infinite loops.
  - `topological_sort()`: Kahn's algorithm producing deterministic execution sequences, raising `CycleDetectedError` when cycles exist.
  - `render_ascii_tree()`: Unicode multi-root forest tree visualizer (`├── `, `└── `, `│   `) with status tags (`[DONE]`, `[RUNNING]`, `[PLANNING]`, `[BACKLOG]`) and cyclic edge protection (`(CYCLE -> [ID])`).
  - `render_mermaid()`: Valid Mermaid `graph TD` diagrams with subgraphs (`Completed`, `Active`, `Backlog`), dependency arrows, and CSS styling classes.
  - `to_dict()`: JSON serialization for external orchestrators and pipelines.
- **CLI Subcommand (`taskctl graph`):**
  - `taskctl graph [--tree] [--mermaid] [--json] [--check-cycles] [--file <path>] [--no-infer]`:
    Provides formatted ASCII tree by default, raw Mermaid diagram with `--mermaid`, JSON with `--json`, and CI-compatible cycle verification with `--check-cycles` (exit code `0` on clean DAG, `1` on cycle).
- **TUI DAG Visualizer (`taskctl ui --dag` / `taskctl dashboard`):**
  - Integrated `render_dag_view` into TUI renderer.
  - Keyboard toggle `v` switches seamlessly between cockpit dashboard and DAG dependency visualizer.

## 3. Alternatives Considered
- **External Graphviz / NetworkX Library:** Rejected to preserve strict zero non-standard runtime dependencies in `taskctl` (standard library only).
- **Separate `.agent/DAG.yaml` File:** Rejected in favor of maintaining `.agent/TASK.md` as the single source of truth for task contracts and metadata.

## 4. Consequences and Trade-offs
### Positive
- Strict cycle detection prevents agent deadlock and broken execution orders.
- Native Mermaid diagram generation embeds directly in GitHub/GitLab markdown documentation.
- Zero external dependencies with 100% test coverage.
- Fully backwards compatible with existing `.agent/TASK.md` formats.

### Negative / Accepted Risks
- Very large task histories (>1000 tasks) may require pagination or depth limiting in ASCII tree displays.

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/TASK.md](file:///home/yegear/github/taskctl/.agent/TASK.md)
- [ADR-001](file:///home/yegear/github/taskctl/.agent/adr/001-modular-cli-architecture.md)
- [ADR-005](file:///home/yegear/github/taskctl/.agent/adr/005-cross-repo-telemetry-aggregation-daemon.md)

---

# [ADR-007] Task Lifecycle Distributed Tracing, Telemetry Spans & SLA Alerting

- **Status:** Approved
- **Date:** 2026-10-02
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
As autonomous AI agents, background daemons, and human operators execute complex multi-step workflows (`next`, `audit`, `done`, `daemon`, `ws`, `plan`), correlating events and diagnosing performance bottlenecks across distributed systems (local CLI, Maestri canvas IPC, and VictoriaLogs/Vector pipeline) is difficult without standardized trace and span context. Operations require:
1. Deterministic trace IDs and parent-child span hierarchy conforming to standard W3C `traceparent` specifications.
2. Direct correlation in VictoriaLogs with canonical root attributes (`trace_id`, `span_id`, `parent_span_id`, `duration_ms`).
3. Automated SLA threshold checks and alerts when critical operations (scope audits, provider RPCs, commands) exceed performance targets.
4. An ergonomic CLI inspector (`taskctl trace`) for local development and post-run analysis.

## 2. Decision Outcome
We implemented a lightweight, hermetic distributed tracing subsystem in `taskctl.telemetry.tracing`:

- **W3C TraceContext & Identifiers (`TraceContext`):**
  - Adheres strictly to the W3C TraceContext recommendation.
  - Generates 128-bit trace IDs (32 lowercase hex characters) and 64-bit span IDs (16 lowercase hex characters).
  - Formats and parses `00-{trace_id}-{span_id}-{flags}` headers, supporting interoperability with external APM agents and HTTP payloads.
  - Automatically derives child contexts maintaining trace ID invariance and linking `parent_span_id`.

- **Hierarchical Spans & Context Management (`Span`, `Tracer`):**
  - Spans represent timed units of work using high-resolution monotonic nanosecond timers (`time.perf_counter_ns`), computing precise `duration_ms`.
  - Python context manager support (`with tracer.start_span("cli.audit") as span:`) for clean scoping and automatic exception trapping.
  - Asynchronous and thread-safe active span propagation via `contextvars.ContextVar`.

- **VictoriaLogs & Vector Schema Integration:**
  - `TelemetryEvent` and `VectorSink` now natively support `trace_id`, `span_id`, and `parent_span_id` as top-level event attributes.
  - `TelemetryEmitter.emit` automatically enriches outbound events with the active trace/span context if omitted.
  - `TelemetryEmitter.emit_span(span)` exports completed spans as structured `event_type="span"` records.

- **SLA Duration Analytics & Threshold Alerting (`TracingAlertPolicy`, `DurationAnalyzer`):**
  - Configurable duration boundaries via environment variables (`TASKCTL_SLA_AUDIT_MS`, `TASKCTL_SLA_PROVIDER_MS`, `TASKCTL_SLA_COMMAND_MS`).
  - Triggers automated fail-safe VictoriaLogs events (`event_type="sla_alert"`, level `warn` or `error`) when operations exceed thresholds.
  - `DurationAnalyzer` provides aggregate statistical metrics (`count`, `total_ms`, `avg_ms`, `max_ms`, `min_ms`) and renders ASCII waterfall tree visualizers.

- **CLI Trace Inspection (`taskctl trace`):**
  - `taskctl trace [--id <trace_id>] [--last] [--json] [--analytics]` displays live in-memory trace trees or machine-readable JSON metrics.

## 3. Alternatives Considered
- **OpenTelemetry Python SDK (`opentelemetry-api`, `opentelemetry-sdk`):** Rejected to preserve the core architectural invariant of zero non-standard runtime dependencies. `taskctl` operates with standard library Python 3.10+ while remaining schema-compatible with OpenTelemetry collectors via Vector.
- **AsyncIO-Only Tracing:** Rejected because `taskctl` CLI is synchronous standard-library Python, needing robust context tracking that works across both synchronous and multi-threaded/daemon executions.

## 4. Consequences and Trade-offs
### Positive
- Zero external dependencies.
- Standard W3C `traceparent` compatibility for multi-agent workflows.
- Rich observability in VictoriaLogs and Vector without risk of process abortion.
- Immediate developer feedback on execution bottlenecks and SLA violations.

### Negative / Accepted Risks
- In-memory trace buffer defaults to 500 completed spans; long-running daemons prune older spans to prevent memory leaks.

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/TASK.md](file:///home/yegear/github/taskctl/.agent/TASK.md)
- [ADR-002: Vector Telemetry Sink](file:///home/yegear/github/taskctl/.agent/adr/002-vector-telemetry-sink.md)
- [ADR-005: Cross-Repo Telemetry Aggregation Daemon](file:///home/yegear/github/taskctl/.agent/adr/005-cross-repo-telemetry-aggregation-daemon.md)
