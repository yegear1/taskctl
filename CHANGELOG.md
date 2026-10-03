# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
