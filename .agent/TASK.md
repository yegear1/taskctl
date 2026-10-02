# TASK.md — Current Task and Roadmap

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [03.4]: Autonomous agent lifecycle hand-offs on task start (`cmd_next`) and task completion (`cmd_done`)

- **Description:** Implement automated agent lifecycle coordination hooks and hand-offs during task start (`taskctl next`) and completion (`taskctl done`), notifying and dispatching context across connected canvas agents.
- **Systems Involved:** [taskctl/cli.py, taskctl/providers/maestri.py, tests/test_maestri.py]
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash-medium'
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] Automated hand-off hooks triggered when promoting tasks via `cmd_next` and completing tasks via `cmd_done`.
- [ ] Context hand-off dispatches task contract updates and instructions to relevant canvas agent roles.
- [ ] Non-blocking fail-safe execution when canvas or agents are offline.
- [ ] Automated tests cover lifecycle hand-off transitions.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [03.3] | Hybrid Scope Auditor with canvas agent delegation fallback | [`e239433`] | 2026-10-02 |
| [03.2] | Canvas topology presets & workspace generator integration in Maestri provider | [`86b86fe`] | 2026-10-02 |
| [03.1] | Contract engine integration with remote agent canvas | [`9a51fe2`] | 2026-10-02 |
| [02.2] | Automated commit message Conventional Commits linter & policy | [`e3168c7`] | 2026-10-01 |
| [00.0] | Initial scaffolding (ADD greenfield template) | [`1d74dac`] | 2026-10-01 |
| [01.1] | Taskctl core engine, CLI, providers, and test suite | [`8875338`, `d3de1aa`] | 2026-10-01 |
| [01.2] | Scope auditor rule-based policy expansion | [`b07e582`] | 2026-10-01 |
| [02.1] | Advanced provider telemetry & Vector direct sink integration | [`c720980`] | 2026-10-01 |

---

## Backlog (Upcoming, in priority order)

- [ ] **[03.5]** Interactive terminal dashboard prototype for active task and DoD checklist

---

## Release / Cycle Wrap-up (Not the next task)

Release/tag only with explicit human request. When triggered, the ID is `[99.1]`. Do not number feature, hygiene, or CI tasks as `99.x`. Do not calculate next task ID from this section.

---

## Future Backlog / Ideas (Unprioritized)

- [ ] Interactive terminal dashboard (`taskctl tui` / `rich` or `curses`) focused strictly on task lifecycle (active task, DoD checklist, and audit diffs) — leaving quota/profile views to [`multigravity-cli`](https://github.com/yegear1/multigravity-cli)
- [ ] GitHub Actions pre-commit check workflow

---

## How to Keep this File Lean

1. Detail only in the active task. When complete $\rightarrow$ log one line and promote the next task.
2. Backlog is a list of titles. Full spec only when an item becomes the active task.
3. Next ID = last ID in log (or active task). Cycle wrap-up and `[99.1]`: see `AGENTS.md`.
