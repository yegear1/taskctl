# ARCHIVE.md — Historical Log of Completed Tasks

> Batches archived after Git tag (or when `TASK.md` log exceeds ~15 entries).
> Canonical header: `## [vX.Y.Z] - YYYY-MM-DD`. Deep detail: `git log`.

---

## [v0.2.0] - 2026-10-18

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [99.1] | Release Wrap-up & Governance Alignment v0.2.0 (v1.0.0 Template Sync) | [`f2f9595`] | 2026-10-18 |
| [02.10] | TUI Split Cockpit: Real-Time DoD Invariant Checks & Token Telemetry | [`d37b09e`] | 2026-10-18 |
| [02.9] | CLI `taskctl trace [XX.Y]` (VictoriaLogs LogsQL Aggregation) | [`011263e`] | 2026-10-17 |
| [02.8] | Context Propagation & Trace Genesis (`MAESTRI_TRACE_ID` in `taskctl next` & `taskctl done` lifecycle spans to VictoriaLogs) | [`1cfdb28`] | 2026-10-17 |
| [02.7] | Knowledge Cards Engine (SQLite FTS5 / BM25) & CLI Subcommands | [`e97b9d2`] | 2026-10-17 |
| [02.6] | Dynamic worktree isolation and branch merge verification for DAG execution stages | [`96c47c2`] | 2026-10-14 |
| [02.5] | Export agnostic DAG execution plan (`taskctl graph --export-plan`) for concurrent worktree runners | [`e962fbd`] | 2026-10-14 |
| [02.4] | Abstract Runner Layer in `taskctl next` with pluggable runner adapters (`--runner <maestri|multigravity|codex|custom>`) | [`1257c73`] | 2026-10-14 |
| [02.3] | Decouple static profiles and dynamic routing in Multigravity provider (`route_target` dynamic discovery / `multigravity route` integration) | [`1bfe178`] | 2026-10-14 |
| [02.2] | Add `--repo <path|name>` flag across `taskctl` commands (`status`, `plan`, `next`, `audit`, `done`) for multi-repository context firewall and remote worktree auditing | [`2ab2b6c`] | 2026-10-14 |
| [02.1] | Add opt-in domain lint rules to the Scope Auditor beyond `git diff --check` | [`adc97f6`] | 2026-10-04 |
| [01.2] | Publish a versioned JSON schema for webhook and Vector telemetry payloads | [`983b7a9`] | 2026-10-04 |
| [01.1] | Align webhook dispatcher with the fail-safe timeout contract | [`fbc9fe3`] | 2026-10-04 |
| [00.1] | Post-release perimeter sync and backlog roadmap planning | [`ef0e5b6`] | 2026-10-04 |

---

## [v0.1.0] - 2026-10-03

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [99.1] | Release v0.1.0 and Post-Release Hygiene | [`3e2e1aa`] | 2026-10-03 |
| [04.3] | Task lifecycle distributed tracing & telemetry spans (trace IDs, task duration analytics, VictoriaLogs/Vector alerts) | [`8ff9acd`] | 2026-10-02 |
| [04.2] | Task dependency graph visualizer (CLI tree, Mermaid generator, TUI DAG viewer & cycle detector) | [`db34834`] | 2026-10-02 |
| [04.1] | Cross-repo telemetry aggregation daemon and status broadcaster | [`c41588f`] | 2026-10-02 |
| [03.7] | Interactive terminal dashboard enhancements (mouse scroll support, split-pane diff viewer) | [`eac2934`] | 2026-10-02 |
| [03.6] | GitHub Actions pre-commit and Scope Auditor CI workflow | [`5b7605f`] | 2026-10-02 |
| [03.5] | Interactive terminal dashboard prototype for active task and DoD checklist | [`e462d77`] | 2026-10-02 |
| [03.4] | Autonomous agent lifecycle hand-offs on task start (cmd_next) and task completion (cmd_done) | [`e33c6f8`] | 2026-10-02 |
| [03.2] | Canvas topology presets & workspace generator integration in Maestri provider | [`86b86fe`] | 2026-10-02 |
| [03.3] | Hybrid Scope Auditor with canvas agent delegation fallback | [`e239433`] | 2026-10-02 |
| [03.1] | Contract engine integration with remote agent canvas | [`9a51fe2`] | 2026-10-02 |
| [02.2] | Automated commit message Conventional Commits linter & policy | [`e3168c7`] | 2026-10-01 |
| [00.0] | Initial scaffolding (ADD greenfield template) | [`1d74dac`] | 2026-10-01 |
| [01.1] | Taskctl core engine, CLI, providers, and test suite | [`8875338`, `d3de1aa`] | 2026-10-01 |
| [01.2] | Scope auditor rule-based policy expansion | [`b07e582`] | 2026-10-01 |
| [02.1] | Advanced provider telemetry & Vector direct sink integration | [`c720980`] | 2026-10-01 |
