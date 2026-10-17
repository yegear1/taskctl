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

### 2026-10-04 Opt-in acceptance-criteria lint
- **Context:** `GitHygieneRule` only runs `git diff --check`. Domain checks on task-contract text must not change the default `taskctl audit` verdict.
- **Decision:** `AcceptanceCriteriaRule` (`dod-criteria`) runs only when `taskctl audit --domain-lint` is passed or `TASKCTL_DOMAIN_LINT` is `1`, `true`, `yes`, or `on`. It requires at least one non-empty acceptance criterion.
- **Consequences:** Default rule chain and exit-code mapping stay unchanged. Empty or blank criteria fail with `CHANGES REQUIRED` only on the opt-in path.

### 2026-10-04 Versioned webhook and Vector payload schemas
- **Context:** Generic webhook bodies and `TelemetryEvent.to_dict()` had no pinned contract for downstream listeners.
- **Decision:** Publish JSON Schema draft 2020-12 documents at `taskctl/schemas/v1/` (v1.0.0) and validate the keyword subset they use with the standard library. Discord and Slack bodies stay adapter-specific.
- **Consequences:** Contract tests remain hermetic with zero new dependencies. External tools can still consume the schema documents directly.

### 2026-10-02 Task Lifecycle Distributed Tracing & Telemetry Spans
- **Context:** Tracing multi-agent lifecycle phases, measuring operation latencies, and alerting on SLA violations without heavy external dependencies.
- **Decision:** Implement W3C-compatible `TraceContext`, `Span`, `Tracer`, and `DurationAnalyzer` in `taskctl.telemetry.tracing`, auto-enriching `TelemetryEvent` and `VectorSink` payloads with `trace_id`, `span_id`, and `parent_span_id`, while triggering fail-safe `sla_alert` events on threshold breach (`taskctl trace`).
- **Consequences:** Deterministic distributed tracing and SLA alerting across all CLI subcommands and agent hand-offs with zero third-party dependencies.

### 2026-10-14 Multi-Repository Context Firewall & Remote Worktree Auditing
- **Context:** Managing task lifecycles, plans, scope audits, and atomic commits across distributed satellite repositories without requiring callers to manually change working directories or risk polluting the calling workspace.
- **Decision:** Implement `resolve_repo_path(repo, base_dir)` in `taskctl.core.parser` supporting absolute paths, relative paths, current repo basename, sibling directories, and `TASKCTL_WATCH_REPOS` environment variable. Wire `--repo <path|name>` flag across `taskctl` commands (`status`, `plan`, `next`, `audit`, `done`). Ensure all Git invocations and file mutations execute hermetically in `cwd=target_repo`.
- **Consequences:** Safe multi-repo orchestration, remote worktree auditing, and double atomic commits without cross-repo pollution or directory context drift.

### 2026-10-14 Decoupled Profiles & Dynamic Multigravity Routing
- **Context:** `taskctl.providers.multigravity` had a hardcoded `MULTIGRAVITY_PROFILES` list and assumed a flat mock bucket schema, preventing discovery of newly added IDE profiles or consuming production nested quota structures.
- **Decision:** Implement `discover_profiles()` checking `TASKCTL_MULTIGRAVITY_PROFILES`, `multigravity list --json`, with fallback to `DEFAULT_PROFILES`. Normalize both flat buckets and rich Antigravity `data.response.groups`. Support dynamic routing via `query_multigravity_route()` (`multigravity route --json`) falling back to local quota-based dynamic calculation.
- **Consequences:** Turn-key integration with dynamic multi-profile environments; zero hardcoded profile coupling; full backward compatibility.

### 2026-10-14 Abstract Runner Layer & Pluggable Runner Adapters
- **Context:** `taskctl next` execution and dispatch was hardcoded to Maestri canvas agent hand-offs, preventing execution in headless worktrees, direct Multigravity execution, OpenAI Codex agent runners, or custom script commands.
- **Decision:** Implement abstract `TaskRunner` base class, structured `RunnerResult`, and pluggable registry in `taskctl.runners`. Built-in adapters support `maestri` (canvas hand-off with offline fallback), `multigravity` (profile worktree dispatch), `codex` (headless agent CLI), and `custom` (template command interpolation via `TASKCTL_RUNNER_COMMAND`). Support `--runner` (`-R`) flag in `taskctl next` and `taskctl done --promote`, falling back to `TASKCTL_DEFAULT_RUNNER` or defaulting to `maestri`.
- **Consequences:** Extensible multi-agent execution with zero vendor lock-in; complete backward compatibility with existing canvas workflows.

### 2026-10-14 Agnostic DAG Execution Plan Export for Concurrent Worktree Runners
- **Context:** Concurrent and multi-agent worktree dispatchers (e.g. Multigravity orchestrator, Codex runners, parallel CI workers) need topological stage gating and concurrency boundaries without being coupled to a specific runner protocol or requiring live agent sockets.
- **Decision:** Implement `export_execution_plan(only_pending=True, repo=...)` on `TaskDependencyGraph` in `taskctl.core.graph`. Group executable tasks into sequential execution waves/stages where all tasks within each stage can be executed concurrently in isolated worktrees. Compute comprehensive metadata (stages, concurrency, suggested git branch names, cycle detection, and blocked task isolation). Expose via `taskctl graph --export-plan [<file>]` (`-p`), supporting `--out` (`-o`) and `--repo` (`-r`). If cycles exist, return exit code 1 with non-executable diagnostic plan.

### 2026-10-14 Dynamic Worktree Isolation & Stage Merge Verification
- **Context:** Parallel tasks in DAG execution stages need isolated worktree environments, verification of disjoint file scopes, and dry-run merge verification before changes are merged into the target repository branch.
- **Decision:** Implement `WorktreeManager` in `taskctl.core.worktree` with automatic `.git/info/exclude` safety, ephemeral worktree lifecycle management (`create_worktree`, `list_worktrees`, `remove_worktree`, `prune_worktrees`), disjoint file scope detection (`check_disjoint_scopes`), in-memory dry-run merge verification (`verify_branch_merge` using `git merge-tree --write-tree` with 3-way simulation fallback), and stage verification (`verify_stage` / `verify_plan`). Expose via CLI subcommands `taskctl worktree` (`list`, `create`, `remove`, `prune`) and `taskctl stage verify` (`--stage`, `--plan`, `--base`, `--repo`, `--json`).
- **Consequences:** Safe, automated concurrent worktree provisioning and conflict-free DAG stage verification with semantic exit codes (`0: APPROVED`, `1: CHANGES REQUIRED`, `2: ERROR`) and zero third-party dependencies.

### 2026-10-17 Knowledge Cards Engine (SQLite FTS5 / BM25) & CLI Subcommands
- **Context:** Managing agent lessons learned, gotchas, failure signatures, and immediate solutions across repositories in sub-millisecond (<0.5ms) lookup time without external dependencies.
- **Decision:** Implement `KnowledgeEngine` and `parse_knowledge_card` in `taskctl.core.knowledge` using SQLite FTS5 (`porter unicode61` tokenizer) and BM25 ranking (`.agent/.cache/knowledge.db`). Support incremental mtime synchronization, graceful fail-open when `.agent/knowledge/` is absent, and error signature reflex evaluation against stack traces. Expose CLI subcommands `taskctl recall` (FTS5 BM25 search) and `taskctl reflex` (headless error analysis).
- **Consequences:** Sub-millisecond knowledge lookup (<0.2ms), zero third-party dependencies, and automated remediation guidance for developers and future `agent-guard` interception.

### 2026-10-17 Context Propagation & Trace Genesis (MAESTRI_TRACE_ID in Lifecycle Spans)
- **Context:** Ensuring end-to-end distributed trace continuity and W3C TraceContext adherence across multi-agent cycles between `taskctl next` ($t_0$) and `taskctl done` ($t_1$), canvas agents, and runner subprocesses.
- **Decision:** Implement trace genesis and ID normalization (`normalize_trace_id`) supporting standard 32-hex, UUID (36 chars with dashes), and arbitrary strings. Support `MAESTRI_TRACE_ID` and `MAESTRI_TRACEPARENT` env vars. Persist active task trace context to `.agent/.cache/active_trace.json` and optional `- **Trace ID:**` in `TASK.md`. Forward trace context in task data, canvas hand-off prompts, and runner subprocess environments (Codex, Custom). Automatically export all completed lifecycle spans to VictoriaLogs via `TelemetryEmitter`.
- **Consequences:** Deterministic, continuous distributed tracing across distributed multi-agent handoffs and CLI sessions with zero external dependencies.

---

## Active Contracts

| Channel / Route | Producer | Consumer | Payload |
|---|---|---|---|
| `.agent/TASK.md` | `taskctl` / Agent | `taskctl.core.parser` | Markdown AST task schema |
| `.agent/.cache/active_trace.json` | `taskctl next` | `taskctl done` / CLI | Ephemeral W3C active trace context |
| `taskctl audit` | `taskctl` | CI / Git Pre-commit | Exit codes: `0: APPROVED`, `1: CHANGES REQUIRED`, `2: REJECTED` |
| `taskctl lint-commit` | `taskctl` | Git `commit-msg` / CI | Exit codes: `0: APPROVED`, `1: CHANGES REQUIRED` |
| `taskctl graph` | `taskctl` | CLI / CI / Worktree Runners / Docs | ASCII Tree, Mermaid `graph TD`, JSON, Agnostic Execution Plan (`--export-plan`), Exit Code (`0: Clean`, `1: Cycle`) |
| `taskctl worktree` | `taskctl` | CLI / Agents / Worktree Runners | Ephemeral worktree lifecycle (list, create, remove, prune) |
| `taskctl stage verify` | `taskctl` | CI / Worktree Runners / Multi-Agent | Stage merge & disjoint scope verification; Exit codes: `0: APPROVED`, `1: CHANGES REQUIRED`, `2: ERROR` |
| `taskctl recall` | `taskctl` | CLI / Developer / Agents | FTS5 BM25 Ranked Knowledge Cards (terminal card list, `--detailed`, or JSON) |
| `taskctl reflex` | `taskctl` | CLI / `agent-guard` / CI | Error signature matching & immediate solution prescription |
| `taskctl trace` | `taskctl` | CLI / CI / Developer | ASCII Waterfall Tree, Trace Spans JSON, or SLA duration analytics |
| `taskctl daemon` / `broadcast` | `taskctl` | Vector / Canvas / Webhook | Aggregated Cross-Repo Workspace Events & Status Summary |
| `WebhookDispatcher` | `taskctl` | Telemetry Endpoint | Generic JSON `taskctl/schemas/v1/webhook-event.schema.json` v1.0.0; Discord and Slack adapters are separate |
| `VectorSink` | `taskctl` | Vector HTTP Ingestion (`:8686/logs`) | Canonical VictoriaLogs JSON (`taskctl/schemas/v1/vector-event.schema.json` v1.0.0) |
| `MaestriIPCClient` / CLI | `taskctl` | Maestri Spatial Canvas | JSON-RPC / CLI notes & workspace commands |
| `TaskRunner` Registry | `taskctl next` / `done -p` | Maestri / Multigravity / Codex / Custom | Pluggable runner execution, structured `RunnerResult`, trace span `runner.execute` |

---

## Gotchas & Pitfalls

- **Parser Flexibility:** Section headers like `## Backlog` or `## Backlog (Upcoming, in priority order)` must be parsed robustly without failing on parenthesized comments.
- **Zero-Crash Telemetry:** Never raise exceptions if `TASKCTL_WEBHOOK_URL` is unreachable or returns 5xx.

---

## Deliberate Technical Debt

| Debt | Rationale | Revisit When |
|---|---|---|
| Hand-rolled argv parsing in `taskctl/cli.py` | Keeps the CLI on the standard library | When a typed parser refactor is explicitly requested |
