---
name: provider-adapter
description: Author and extend multi-agent orchestration provider adapters (Maestri, Multigravity, etc.) with fail-safe degradations and zero hardcoded credentials.
---

# Provider Adapter Development

## 1. Context and Objective
Adapters in `taskctl/providers/` connect the task engine with external agent orchestration platforms such as Maestri (canvas terminals and sticky notes) and Multigravity (isolated profiles, quota balancing, worktree management).

---

## 2. When to Use (Triggers)
Activate this skill whenever the task involves:
- Integrating a new agent runtime, canvas, or orchestrator.
- Updating IPC socket discovery or CLI fallback logic in `taskctl/providers/`.
- Changing quota routing or target profile selection logic.

---

## 3. Associated Tools and MCP Servers
- **MCP Servers:** `multigravity` (optional fallback for inspection), `maestri` (optional canvas inspection).
- **CLI Tools:** `maestri --version`, `agy profile status`.

---

## 4. Operational Guardrails
- **Graceful Fallback:** If a provider daemon or socket is not running, adapter calls MUST degrade gracefully and return sensible defaults without aborting the CLI.
- **Secrets Isolation:** Never pass secrets through CLI flags or socket paths that could leak in process listings.

---

## 5. Skill Completion Checklist
- [ ] Provider function returns typing-compliant types (dicts/tuples/dataclasses).
- [ ] Safe fallback when socket or binary is missing.
- [ ] Syntax check and test suite exit with 0.
