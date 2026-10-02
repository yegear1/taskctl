# TASK.md — Current Task and Roadmap

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [XX.Y]: [Short descriptive title]

- **Description:** [Awaiting next planned task or instructions]
- **Systems Involved:** [taskctl, core, cli]
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash-medium'
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] Criteria pending next task promotion

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [00.0] | Initial scaffolding (ADD greenfield template) | [`1d74dac`] | 2026-10-01 |
| [01.1] | Taskctl core engine, CLI, providers, and test suite | [`8875338`] | 2026-10-01 |

---

## Backlog (Upcoming, in priority order)

- [ ] **[01.2]** [Scope auditor rule-based policy expansion] — `[core]`
- [ ] **[02.1]** [Advanced provider telemetry & Vector direct sink integration] — `[telemetry]`

---

## Release / Cycle Wrap-up (Not the next task)

Release/tag only with explicit human request. When triggered, the ID is `[99.1]`. Do not number feature, hygiene, or CI tasks as `99.x`. Do not calculate next task ID from this section.

---

## Future Backlog / Ideas (Unprioritized)

- [ ] Interactive terminal dashboard with `rich` or `curses`
- [ ] GitHub Actions pre-commit check workflow

---

## How to Keep this File Lean

1. Detail only in the active task. When complete $\rightarrow$ log one line and promote the next task.
2. Backlog is a list of titles. Full spec only when an item becomes the active task.
3. Next ID = last ID in log (or active task). Cycle wrap-up and `[99.1]`: see `AGENTS.md`.
