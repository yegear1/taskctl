# TASK.md — Current Task and Roadmap

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [XX.Y]: [Short descriptive title]

- **Description:** [Awaiting next planned task]
- **Systems Involved:** []
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash-medium'
- **Action Type:**
  - [ ] Read-only / Documentation
  - [ ] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] [Awaiting next planned task criteria]

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
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

---

## Backlog (Upcoming, in priority order)

*(Backlog empty — awaiting new roadmap planning)*

---

## Release / Cycle Wrap-up (Not the next task)

Release/tag only with explicit human request. When triggered, the ID is `[99.1]`. Do not number feature, hygiene, or CI tasks as `99.x`. Do not calculate next task ID from this section.

---

## Future Backlog / Ideas (Unprioritized)

- [ ] Interactive task dependency graph visualizer

---

## How to Keep this File Lean

1. Detail only in the active task. When complete $\rightarrow$ log one line and promote the next task.
2. Backlog is a list of titles. Full spec only when an item becomes the active task.
3. Next ID = last ID in log (or active task). Cycle wrap-up and `[99.1]`: see `AGENTS.md`.
