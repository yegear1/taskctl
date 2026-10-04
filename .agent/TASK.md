# TASK.md — Current Task and Roadmap

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [02.1]: Add opt-in domain lint rules to the Scope Auditor beyond `git diff --check`

- **Description:** `GitHygieneRule` only runs `git diff --check`. Add domain lint rules that stay off unless explicitly enabled, so the default `taskctl audit` verdict does not change.
- **Systems Involved:** [auditor, cli, tests, docs]
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash'
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** RUNNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [x] With domain lint disabled, `taskctl audit` still applies `GitHygieneRule` via `git diff --check` and keeps the current exit-code mapping.
- [x] An explicit opt-in (CLI flag or environment variable) enables at least one domain rule that inspects task-contract content beyond whitespace and conflict markers.
- [x] Hermetic tests cover the disabled path and the enabled path, including one failing domain finding.
- [x] The opt-in switch is documented in command help or `README.md`.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [01.2] | Publish a versioned JSON schema for webhook and Vector telemetry payloads | [`983b7a9`] | 2026-10-04 |
| [01.1] | Align webhook dispatcher with the fail-safe timeout contract | [`fbc9fe3`] | 2026-10-04 |
| [00.1] | Post-release perimeter sync and backlog roadmap planning | [`ef0e5b6`] | 2026-10-04 |

---

## Backlog (Upcoming, in priority order)

*(Backlog empty)*

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
