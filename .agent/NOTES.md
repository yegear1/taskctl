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
| | *(none yet)* | | |

---

## Quick Decisions

### [YYYY-MM-DD] [Title]

- **Context:** […]
- **Decision:** […]
- **Alternatives Considered:** […]
- **Consequences:** […]

---

## Active Contracts

Full schemas live in code (`[core/schemas/]`). This table maps high-level contracts:

| Channel / Route | Producer | Consumer | Payload |
|---|---|---|---|
| | | | |

Contract changes require updating schemas on both sides within the same task.

---

## Gotchas & Pitfalls

- **[Lib/Service]:** [unexpected behavior and mitigation]

---

## Deliberate Technical Debt

| Debt | Rationale | Revisit When |
|---|---|---|
| | | |
