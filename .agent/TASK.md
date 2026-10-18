# TASK.md — Current Task and Roadmap

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [03.1]: Epic 03 Planning & Architecture Alignment

- **Description:** Plan initial capabilities for Epic 03, incorporating template-agent v1.0.0 standards and defining domain roadmap milestones.
- **Systems Involved:** taskctl.core, taskctl.cli
- **Action Type:**
  - [x] Read-only / Documentation
  - [ ] Source code changes
- **Status:** READY FOR PLANNING

### Acceptance Criteria
- [ ] Align backlog goals with multi-agent orchestration roadmap.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [99.1] | Release Wrap-up & Governance Alignment v0.2.0 (v1.0.0 Template Sync) | [`f2f9595`] | 2026-10-18 |

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
