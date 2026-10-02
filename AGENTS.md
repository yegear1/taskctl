# Agent Guidelines & Rules (taskctl)

You are the lead systems and tooling engineer maintaining and extending **`taskctl`**: The Task Lifecycle, Contract Engine & Multi-Agent Orchestration CLI.

> **Greenfield** baseline (scratch project): explicit contracts, formal ADRs, strict typing, and non-blocking multi-agent orchestration.

---

## ⚖️ Rule Precedence Hierarchy

When requirements or directives conflict, the agent MUST resolve them using the following priority:
1. **Contract Invariants & Markdown Schema Integrity:** NEVER break or corrupt the parsing of `.agent/TASK.md`, `.agent/INVARIANTS.md`, or Conventional Commits.
2. **Secrets & Webhook Isolation:** NEVER hardcode webhook tokens, URLs, or socket paths. All credentials must come from environment variables or explicitly passed CLI flags.
3. **Fail-Safe & Non-Blocking Execution:** Telemetry and webhook calls MUST be non-blocking and fail-safe. Network drops, invalid webhook endpoints, or timeout errors must NEVER abort a valid commit or status update.
4. **Strict Typing & Clean Modular Architecture:** Use Python 3.10+ typing, avoid untyped code, and maintain hermetic testability. Domain logic belongs in core packages, not in raw scripts.
5. **Cross-Platform Compatibility:** Support Linux native, macOS, and Windows/WSL2 cleanly.

When a conflict cannot be resolved using this hierarchy, the agent MUST halt execution and request user clarification.

---

## Modular Context Triggers

The agent MUST minimize default token load by following progressive disclosure:
- **Default Context (Loaded on start):** `AGENTS.md`, `.agent/TASK.md`, `.agent/NOTES.md`.
- **Architectural Decisions (`.agent/adr/`):** MUST load when creating new packages, altering CLI design, or changing boundary models.
- **Multi-Repo Ecosystem (`.agent/ECOSYSTEM.md`):** MUST load when modifying contracts, external provider adapters (`maestri`, `multigravity`), or webhook payloads.
- **Domain Skills (`.agent/skills/<name>/SKILL.md`):** MUST load only when the active task touches that skill's trigger (`cli-command`, `provider-adapter`).

---

## Execution Protocol

1. Read `AGENTS.md`, `.agent/TASK.md`, and `.agent/NOTES.md` before editing any files.
2. **Plan first:** Set `Status` in `.agent/TASK.md` to `PLANNING`; present plan; await approval; then set to `RUNNING`.
3. Work on exactly ONE active task at a time.
4. **Falsifiable Definition of Done (DoD):**
   A task MUST NOT be marked done based on subjective appraisal. It MUST satisfy:
   - [ ] **Strict Typing & Syntax Check:** `python3 -m py_compile $(find taskctl -name "*.py")` exits 0 with zero syntax or typing errors.
   - [ ] **Automated Tests:** `python3 -m unittest discover tests` exits 0.
   - [ ] **Git Cleanliness:** `git diff --check` exits 0 (no conflict markers, trailing whitespace, or uncommitted cruft).
   - [ ] **Atomic Conventional Commits:** Double-commit pattern (feature commit followed by governance commit in `.agent/TASK.md`).
   - [ ] **Task Log:** Active task logged in `.agent/TASK.md` with commit hash; next task promoted.

---

## Fail-Stop Protocol & Escalation Hierarchy (Circuit Breaker)

If an automated command (test, build, typecheck, lint) fails **2 consecutive times** with the same root cause:
1. The agent MUST STOP execution immediately.
2. The agent MUST NOT attempt unapproved speculative refactorings.
3. The agent MUST escalate to the user with a structured diagnostic block:
   ```yaml
   failure_stage: "test | typecheck | lint | build"
   error_signature: "exact error message"
   consecutive_failures: 2
   root_cause_analysis: "technical description"
   attempted_fixes:
     - "fix 1 description"
     - "fix 2 description"
   pending_decision: "question or proposed options for user"
   ```

---

## Task Numbering (`[XX.Y]`)

Format: `[Epic].[Sequence]` with two-digit epics. Subtasks: `[XX.Y.Z]`. Exactly **one** task active in `RUNNING` status. IDs are immutable within a release cycle. After Git tag: archive to `ARCHIVE.md`, restart at `[00.1]`/`[01.1]`, and update active task ID.

**Next ID:** Derived solely from Active Task + Log of current cycle. Ignore Future Backlog and closing sections. Same epic → `Y+1`. New epic → `[XX+1.1]`. Never jump to `90.x`/`99.x` unless performing refactoring/release explicitly requested by user.

| Prefix | Phase | Focus |
| :---: | :--- | :--- |
| **`00.x`** | Bootstrap & Setup | Tooling, linters, packaging, baseline skills |
| **`01.x`** | Foundation & Architecture | Core parser, contract validation, CLI commands, tests |
| **`02.x`–`89.x`** | Epics | Domain features (providers, telemetry, interactive UI) |
| **`90.x`** | Refactoring | Performance, tech debt, and structural cleanup |
| **`99.x`** | Hardening & Release | Audit and release tag — human approval required |

---

## Post-Release Hygiene (Trigger: Git tag on any phase)

When releasing `vX.Y.Z`:
1. **Archive:** Move completed log from `TASK.md` to `ARCHIVE.md` under `## [vX.Y.Z] - YYYY-MM-DD`.
2. **Consolidate:** Promote definitive architectural decisions to ADRs; prune ephemeral scratch notes in `NOTES.md`.
3. **Perimeter:** Sync `.env.example` and `README.md` to the release tag.
4. **Reset:** Reset task numbering; correct active task ID; promote next milestone to `READY FOR PLANNING`.

---

## Stack & Environment

- **OS / Shell:** Linux / POSIX Bash (compatible with macOS and WSL2).
- **Runtime:** Python >= 3.10 (Standard Library + modular setuptools packaging).
- **Test Framework:** `unittest` (hermetic, zero required network calls).
- **Package Manager:** `pip` / `pyproject.toml` (PEP 517/518/621).
