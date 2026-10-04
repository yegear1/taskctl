# TASK.md — Current Task and Roadmap

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [01.2]: Publish a versioned JSON schema for webhook and Vector telemetry payloads

- **Description:** The generic webhook body (`event`, `task_id`, `title`, `status`, `details`) and the Vector sink body (`TelemetryEvent.to_dict()`) have no versioned schema. Publish JSON Schema documents that pin both contracts, and validate representative payloads in hermetic tests.
- **Systems Involved:** [webhooks, telemetry, docs, tests]
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash'
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** RUNNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [x] A versioned JSON Schema covers the generic webhook event object posted by `WebhookDispatcher` for non-Discord, non-Slack URLs.
- [x] A versioned JSON Schema covers the canonical Vector payload produced by `TelemetryEvent.to_dict()`, including required VictoriaLogs root fields and optional trace attributes.
- [x] Discord and Slack adapter bodies stay outside the canonical webhook schema.
- [x] Hermetic tests reject invalid payloads and accept current dispatcher and sink examples, with zero network calls.
- [x] Schema file paths and versions are documented next to the webhook and Vector variables in `.env.example` or the schema directory README.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [01.1] | Align webhook dispatcher with the fail-safe timeout contract | [`fbc9fe3`] | 2026-10-04 |
| [00.1] | Post-release perimeter sync and backlog roadmap planning | [`ef0e5b6`] | 2026-10-04 |

---

## Backlog (Upcoming, in priority order)

1. **[02.1]** Add opt-in domain lint rules to the Scope Auditor beyond `git diff --check`.

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
