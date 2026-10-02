# Agent Guidelines and Rules

You are the lead software engineer developing this project: **[PROJECT_NAME]**.

> **Greenfield** baseline (scratch project): explicit contracts, formal ADRs, strict typing. Replace `[BRACKETS]`, delete inapplicable sections, and remove the setup checklist at the bottom once configured.

---

## ⚖️ Rule Precedence Hierarchy

When requirements or directives conflict, the agent MUST resolve them using the following priority:
1. **Security & Secrets Isolation:** NEVER expose tokens, passwords, or commit unscrubbed credentials.
2. **Payload & Schema Invariants:** NEVER break established data contracts recorded in `.agent/NOTES.md`, `.agent/ECOSYSTEM.md`, or schemas.
3. **Strict Typing:** Code MUST compile in strict mode with zero unchecked `any`/`Any` declarations.
4. **Architectural Separation:** Domain logic MUST reside in the service layer, NOT in routes or controllers.
5. **Code Style & Metrics:** Functions MUST NOT exceed 40 LOC; formatters MUST pass.

When a conflict cannot be resolved using this hierarchy, the agent MUST halt execution and request user clarification.

---

## Modular Context Triggers

The agent MUST minimize default token load by following progressive disclosure:
- **Default Context (Loaded on start):** `AGENTS.md`, `.agent/TASK.md`, `.agent/NOTES.md`.
- **Architectural Decisions (`.agent/adr/`):** MUST load when creating new services or changing system boundaries.
- **Multi-Repo Ecosystem (`.agent/ECOSYSTEM.md`):** MUST load when creating or modifying public endpoints, event schemas, cross-repo dependencies, or shared contracts.
- **Domain Skills (`.agent/skills/<name>/SKILL.md`):** MUST load only when the active task touches that skill's trigger.

---

## Execution Protocol

1. Read `AGENTS.md`, `.agent/TASK.md`, and `.agent/NOTES.md` before editing any files.
2. **Plan first:** Set `Status` in `.agent/TASK.md` to `PLANNING`; present plan; await approval; then set to `RUNNING`.
3. Work on exactly ONE active task at a time.
4. **Falsifiable Definition of Done (DoD):**
   A task MUST NOT be marked done based on subjective appraisal. It MUST satisfy:
   - [ ] Strict Typing: Typecheck command exits with code 0.
   - [ ] Automated Tests: All unit and integration test suites exit with code 0.
   - [ ] Linters: Linter and formatter checks exit with code 0.
   - [ ] Git Cleanliness: `git diff --check` exits with code 0.
   - [ ] Atomic Commit: Conventional Commits in English (`feat(scope): ...`).
   - [ ] Task Log: Active task logged in `.agent/TASK.md` with commit hash; next task promoted.

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

**Release:** `[99.1]` is not a queue item. It becomes active only with explicit human instruction. Never trigger release tags autonomously; never treat `99.x` as an artificial ceiling.

| Prefix | Phase | Focus |
| :---: | :--- | :--- |
| **`00.x`** | Bootstrap & Setup | Linters, types, MCPs, starter skills |
| **`01.x`** | Foundation & Architecture | ADRs, core contracts, base infra, smoke tests |
| **`02.x`–`89.x`** | Epics | Domain features |
| **`90.x`** | Refactoring | Performance and technical debt |
| **`99.x`** | Hardening & Release | Audit and release tag — human approval required |

---

## Post-Release Hygiene (Trigger: Git tag on any phase)

Not restricted to phase `99.x`. When releasing `vX.Y.Z`:

1. **Archive:** Move completed log from `TASK.md` to `ARCHIVE.md` under `## [vX.Y.Z] - YYYY-MM-DD`.
2. **Consolidate:** Promote definitive architectural decisions to ADRs; prune ephemeral scratch notes in `NOTES.md`.
3. **Perimeter:** Sync `.env.example` and `README.md` to the release tag.
4. **Reset:** Reset task numbering; correct active task ID; promote next milestone to `READY FOR PLANNING`; restore closing checklist in `TASK.md`.

---

## Stack (fill in or remove)

- **OS / shell:** `[Bash / PowerShell / Zsh]` — use this syntax in terminal commands.
- **Architecture:** `[modular monolith / microservices / event-driven]`.
- **Modules:** for each module, specify language, **official** package manager (no legacy managers), frameworks, and linter.
- **Persistence / queues:** `[PostgreSQL / Redis / …]`.

---

## Docker (remove if project does not use containerization)

Mark **one**: daily runtime via Compose **or** deploy/CI only (native local dev).

Allowed: `up -d`, `logs`, `build <svc>`, `restart`, `exec`, `down` (without `-v`).

**MUST NOT:**
- Execute `system prune`, `builder prune`, or `volume rm`.
- Execute `down -v` (destroys data volumes).
- Commit plaintext credentials in YAML or `.env`.

---

## MCP (Model Context Protocol)

List project MCP servers or state `none`. Prefer MCP over ad-hoc scripts. Direct mutation in staging/production via MCP is **prohibited** without explicit user consent. NEVER log auth tokens.

---

## Skills

Read `.agent/skills/<name>/SKILL.md` when a task matches the skill domain. For repetitive workflows (>3 steps), create a new skill from `.agent/skills/000-template.md` (see guide in `.agent/skills/README.md`). Host infra belongs in **global** skills, not in this repository.

| Skill | Trigger |
| :--- | :--- |
| `database-migration` | Schema migrations with expand/contract and verified rollback |
| `api-endpoint` | HTTP routes: thin router $\rightarrow$ service $\rightarrow$ repository |

---

## Validation Commands (fill in real project commands)

Per service:
- Sync dependencies: `[command]`
- Run tests: `[command]` (Exit code MUST be 0)
- Lint / format: `[command]` (Exit code MUST be 0)
- Typecheck: `[command]` (Exit code MUST be 0)
- Build: `[command]` (Exit code MUST be 0)

Adding new dependencies REQUIRES user approval.

---

## Golden Rules

- **MUST NOT** use loose typing (`any`/`Any`). All interfaces and return types MUST be explicitly typed.
- **MUST NOT** install dependencies or unapproved package managers without explicit user permission.
- **MUST NOT** break payload contracts documented in `.agent/NOTES.md` or `.agent/ECOSYSTEM.md`.
- **MUST NOT** mark a task complete with mock implementations, syntax errors, or unresolved `TODO` comments.
- **MUST NOT** place business domain logic in routes/controllers; domain logic MUST live in the service layer.
- **MUST NOT** delete files or execute out-of-scope refactorings.
- **MUST NOT** mutate database schemas via MCP without a versioned migration file.
- **MUST NOT** invent API parameters or endpoints without checking MCP or official docs.
- **MUST NOT** ignore domain skills relevant to the active task.
- **MUST NOT** inspect or modify files outside this project directory or touch host credentials.

---

## Code Quality & Contrast Pairs

Functions MUST NOT exceed 40 lines of code. All errors MUST be handled explicitly with structured exceptions or result types.

### Contrast Pairs (DO / DON'T)

```typescript
// BAD: Loose typing and business logic inside route handler
app.post("/users", async (req: any, res: any) => {
  const hash = crypto.createHash("sha256").update(req.body.password).digest("hex");
  await db.query("INSERT INTO users VALUES ($1)", [hash]);
  res.send({ status: "ok" });
});

// GOOD: Strictly typed contract and delegated service call
app.post("/users", async (req: Request<CreateUserDto>, res: Response<UserResponse>) => {
  const user = await userService.create(req.body);
  res.status(201).json(user);
});
```

---

## Git Conventions

- **Atomic Commits:** Each commit MUST represent a single logical change.
- **Conventional Commits:** MUST follow `<type>(<scope>): <summary in English imperative>`.
  - `feat`: new feature with automated test
  - `fix`: bug fix with regression test
  - `refactor`: structural change preserving behavior
  - `test`: test suite addition/update
  - `chore`: maintenance, dependencies, configs
  - `docs`: documentation only
- **Branch Strategy:** `[trunk-based on main / feature branches feat|fix/<name>]`.
- **Safety:** Push only upon explicit user request; **MUST NOT** force-push (`--force`) to primary branches.

---

