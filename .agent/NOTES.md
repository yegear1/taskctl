# NOTES.md — Project Decisions, Context, and Contracts

> Stores the WHY. The WHAT lives in `git log` / `TASK.md`. Record only entries that explain
> an architectural decision or gotcha; do not include changelogs.

---

## How to Use

1. Read before planning. Decisions here take precedence over "obvious defaults", unless explicitly revisited.
2. Record: trade-offs, contracts, gotchas, new skills, deliberate technical debt.
3. Lengthy entries $\rightarrow$ formal ADR in `.agent/adr/` and only one line + link here.

---

## Formal ADRs

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](adr/001-modular-cli-architecture.md) | Modular CLI Architecture & Fail-Safe Webhook Dispatcher | Approved | 2026-10-01 |

---

## Quick Decisions

### 2026-10-01 Greenfield Baseline Scaffolding
- **Context:** Establishing the official repository foundation for `taskctl`.
- **Decision:** Adopt the ADD Greenfield template from `ye-sandbox/template-agent` (branch `greenfield`).
- **Consequences:** All task lifecycle and agent interactions adhere to standard ADD contracts (`.agent/TASK.md`, `.agent/ECOSYSTEM.md`, `.agent/skills/`).

### 2026-10-01 Non-Blocking Webhook Telemetry
- **Context:** Sending lifecycle notifications to external dashboards or vector sinks.
- **Decision:** Implement fail-safe background dispatching with strict 2-second timeout.
- **Consequences:** Developer or agent commits and task transitions are never blocked or aborted by telemetry network failures.

---

## Active Contracts

| Channel / Route | Producer | Consumer | Payload |
|---|---|---|---|
| `.agent/TASK.md` | `taskctl` / Agent | `taskctl.core.parser` | Markdown AST task schema |
| `taskctl audit` | `taskctl` | CI / Git Pre-commit | Exit codes: `0: APPROVED`, `1: CHANGES REQUIRED`, `2: REJECTED` |
| `WebhookDispatcher` | `taskctl` | Telemetry Endpoint | JSON Task Lifecycle Event |

---

## Gotchas & Pitfalls

- **Parser Flexibility:** Section headers like `## Backlog` or `## Backlog (Upcoming, in priority order)` must be parsed robustly without failing on parenthesized comments.
- **Zero-Crash Telemetry:** Never raise exceptions if `TASKCTL_WEBHOOK_URL` is unreachable or returns 5xx.

---

## Deliberate Technical Debt

| Debt | Rationale | Revisit When |
|---|---|---|
| Basic `git diff --check` in audit | Fast initial gate for git hygiene without heavy linter setup | When custom domain lint rules are requested |
