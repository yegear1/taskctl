---
name: cli-command
description: Author, test, and maintain CLI subcommands in taskctl with strict argument typing, semantic exit codes, and non-blocking telemetry.
---

# CLI Command Authoring & Maintenance

## 1. Context and Objective
`taskctl` provides the developer and agent interface for lifecycle management (`init`, `status`, `plan`, `next`, `audit`, `done`). Every command must adhere to strict typing, deterministic exit codes, and fail-safe side effects.

---

## 2. When to Use (Triggers)
Activate this skill whenever the task involves:
- Adding a new CLI command to `taskctl/cli.py`.
- Modifying command argument parsing or return codes.
- Updating Scope Auditor (`taskctl audit`) or lifecycle transitions (`taskctl done`).

---

## 3. Associated Tools and MCP Servers
- **CLI Tools:** `python3 -m unittest discover tests`, `python3 -m py_compile $(find taskctl -name "*.py")`, `git diff --check`.
- **MCP Servers:** None (pure Python standard library + modular architecture).

---

## 4. Step-by-Step Operational Procedure

### Step 1: Interface Design
Define command name, arguments, flags, and help text in `taskctl/cli.py`.

### Step 2: Implement Handler
Implement `cmd_<name>` ensuring:
- Markdown AST parsing uses `taskctl.core.parser`.
- Any external notification uses `WebhookDispatcher`.
- Provider integrations gracefully handle missing dependencies.

### Step 3: Automated Testing
Add unit tests in `tests/` verifying exit codes, edge cases, and file mutations.

---

## 5. Known Gotchas and Anti-Patterns
- ⚠️ **DO NOT:** Raise uncaught exceptions to user standard error for expected failures; format clean error messages with non-zero exit codes.
- ⚠️ **DO NOT:** Block on external webhooks or network calls during command execution.
- 💡 **DO:** Always verify `git diff --check` and run tests before committing.
