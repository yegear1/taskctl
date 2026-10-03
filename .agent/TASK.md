# TASK.md — Current Task and Roadmap

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [00.1]: Post-release perimeter sync and backlog roadmap planning

- **Description:** Sync repository perimeter (.env.example, README.md, CI workflows) to v0.1.0 release baseline, plan upcoming milestone epics, and establish next release objectives.
- **Systems Involved:** [governance, docs, perimeter]
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash'
- **Action Type:**
  - [x] Read-only / Documentation
  - [ ] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] Audit repository perimeter files against published release v0.1.0.
- [ ] Formulate upcoming epics and populate backlog in `.agent/TASK.md`.
- [ ] Ensure all tests and governance policies remain passing with zero regressions.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|

---

## Backlog (Upcoming, in priority order)

*(Backlog empty - awaiting post-release roadmap planning)*

---

## Release / Cycle Wrap-up (Not the next task)

Release/tag only with explicit human request. When triggered, the ID is `[99.1]`. Do not number feature, hygiene, or CI tasks as `99.x`. Do not calculate next task ID from this section.

---

## Future Backlog / Ideas (Unprioritized)

*(Future backlog empty)*

---

## How to Keep this File Lean

1. Detail only in the active task. When complete $\rightarrow$ log one line and promote the next task.
2. Backlog is a list of titles. Full spec only when an item becomes the active task.
3. Next ID = last ID in log (or active task). Cycle wrap-up and `[99.1]`: see `AGENTS.md`.
