# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-18

### Added
- **TUI Split Cockpit Enhancements**: Real-time Definition of Done (DoD) checks, system invariant inspection (ephemeral sockets, exposed credentials), diff hygiene scanner, role & model token telemetry breakdown, and recent event stream.
- **VictoriaLogs LogsQL Distributed Tracing**: CLI `taskctl trace [XX.Y]` command querying VictoriaLogs, lifecycle context propagation (`MAESTRI_TRACE_ID` in `taskctl next` & `taskctl done`), and span duration timeline breakdown.
- **Knowledge Cards Engine**: SQLite FTS5 / BM25 knowledge engine and CLI subcommands (`taskctl knowledge index/search/query`) with `.agent/knowledge/` scaffolding (`000-schema.md`, `k-000-template.md`).
- **DAG Stage Merge & Dynamic Worktree Isolation**: Automated worktree provisioning (`.taskctl/worktrees/`), multi-task merge conflict verification (`taskctl graph --verify-stages`), and agnostic execution plan export (`taskctl graph --export-plan`).
- **Pluggable Runner Architecture**: Abstract runner abstraction in `taskctl next --runner` with dedicated adapters for Maestri, Multigravity, Codex, and Custom runners.
- **Multi-Repository Context Firewall**: Global `--repo <path|name>` flag across all CLI subcommands (`status`, `plan`, `next`, `audit`, `done`) for remote worktree auditing and context boundary protection.
- **Dynamic Multigravity Routing**: Profile quota balancing, model target resolution, and dynamic discovery integration (`multigravity route`).
- **Upstream Governance v1.0.0 Alignment**: Fast-Path vs Plan-First execution workflows, Consultative Dependency & LTS/Stable Versioning policies, and Code Quality contrast pairs in `AGENTS.md`.

## [0.1.0] - 2026-10-03

### Added
- **Core Contract Engine & Markdown AST Parser**: Deterministic parser and serializer for `.agent/TASK.md` and `.agent/INVARIANTS.md` with section-agnostic flexibility.
- **CLI Subcommand Suite**: Comprehensive CLI commands including `init`, `status`, `plan`, `next`, `audit`, `done`, `sync`, `quota`, `ws`, `notify`, `daemon`, `broadcast`, `graph`, `trace`, `lint-commit`, and `ui`.
- **Scope Auditor & Conventional Commits Policy**: Automated pre-commit/CI verification engine (`taskctl audit`, `taskctl lint-commit`) enforcing Conventional Commits 1.0.0 standards and git cleanliness gates.
- **Distributed Tracing & SLA Alerting**: W3C-compatible `TraceContext`, `Span`, `Tracer`, and duration analytics (`taskctl trace`) with VictoriaLogs and Vector alerting thresholds.
- **Vector Direct Sink & Non-Blocking Webhook Telemetry**: Fail-safe background event dispatcher with circuit-breaker timeouts and direct HTTP streaming to Vector (`:8686/logs`) in VictoriaLogs NDJSON format.
- **Task Dependency Graph Engine**: Hierarchical DAG parser supporting explicit dependencies and implicit sequential flows, cycle detection via DFS coloring, ASCII waterfall tree, Mermaid generator, and interactive TUI DAG view (`taskctl graph`).
- **Remote Agent Canvas Integration**: Maestri IPC domain socket client and workspace provisioning (`taskctl ws`, `taskctl sync`) with fail-safe remote delegation.
- **Autonomous Agent Lifecycle Hand-offs**: Automated transition hooks and notification payloads on task start (`taskctl next`) and task completion (`taskctl done`).
- **Interactive Terminal Dashboard**: Textual TUI dashboard for active task monitoring, mouse scrolling, split-pane diff viewer, and falsifiable Definition of Done (DoD) verification.
- **CI/CD Quality Automation**: GitHub Actions workflow for automated test discovery and Scope Auditor gating.
