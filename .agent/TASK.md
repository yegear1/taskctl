# TASK.md — Current Task and Roadmap

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [99.1]: Release Wrap-up & Governance Alignment v0.2.0 (v1.0.0 Template Sync)

- **Description:** Execute release wrap-up for cycle v0.2.0: archive completed tasks to ARCHIVE.md, sync .agent/knowledge scaffolding and AGENTS.md operational clauses from template-agent v1.0.0, sync perimeter files, and reset task numbering for Epic 03.
- **Systems Involved:** AGENTS.md, .agent/TASK.md, .agent/ARCHIVE.md, .agent/knowledge/, CHANGELOG.md
- **Action Type:**
  - [x] Read-only / Documentation
  - [x] Source code changes
- **Status:** RUNNING

### Acceptance Criteria
- [ ] Add `.agent/knowledge/000-schema.md` and `.agent/knowledge/k-000-template.md` from `template-agent` v1.0.0.
- [ ] Update `AGENTS.md` with Fast-Path vs Plan-First, Consultative Dependencies & LTS/Stable versioning, and Code Quality contrast pairs.
- [ ] Archive completed tasks from `TASK.md` to `ARCHIVE.md` under `## [v0.2.0] - 2026-10-18`.
- [ ] Update `CHANGELOG.md` with v0.2.0 release notes.
- [ ] Tag git commit `v0.2.0`.
- [ ] Reset `TASK.md` active task to `[03.1]: READY FOR PLANNING`.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
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

## Backlog (Upcoming, in priority order)

*(Backlog empty. All Epic 02 tasks scheduled or completed.)*

---

## Release / Cycle Wrap-up (Not the next task)

Release/tag only with explicit human request. When triggered, the ID is `[99.1]`. Do not number feature, hygiene, or CI tasks as `99.x`. Do not calculate next task ID from this section.

---

## Future Backlog / Ideas (Unprioritized)

- Replace hand-rolled argv parsing in `taskctl/cli.py` with a typed parser (refactor epic only when requested).

---

## How to Keep this File Lean

1. Detail only in the active task. When complete $\rightarrow$ log one line and promote the next task.
2. Backlog is a list of titles. Full spec only when an item becomes the active task.
3. Next ID = last ID in log (or active task). Cycle wrap-up and `[99.1]`: see `AGENTS.md`.
