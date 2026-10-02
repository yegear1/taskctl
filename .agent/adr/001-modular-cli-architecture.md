# [ADR-001] Modular CLI Architecture & Fail-Safe Webhook Dispatcher

- **Status:** Approved
- **Date:** 2026-10-01
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
Autonomous AI coding agents frequently degrade when executing long tasks or performing automated releases if tooling is monolithic, brittle, or fails abruptly due to network drops, missing daemon sockets, or schema drift in governance files (`.agent/TASK.md`). `taskctl` must serve as the hermetic task lifecycle engine, contract validator, and multi-agent dispatcher without blocking or aborting developer workflows.

## 2. Decision Outcome
We adopted a modular Python architecture partitioned into:
- `taskctl.core`: Strict Markdown AST parsing, `.agent/TASK.md` contract validation, and DoD evaluation.
- `taskctl.providers`: Resilient adapters for multi-agent platforms (Maestri IPC, Multigravity quota balancer) with graceful degradations when daemons are offline.
- `taskctl.webhooks`: Asynchronous, non-blocking telemetry event dispatching with circuit breakers and timeout guards.
- `taskctl.cli`: Ergonomic CLI entrypoint exposing semantic subcommands (`init`, `status`, `plan`, `next`, `audit`, `done`).

## 3. Alternatives Considered
- **Monolithic Single-File CLI (`taskctl.py`):** Rejected due to untestable side-effects, tightly coupled external dependencies, and poor maintainability.
- **Synchronous HTTP Webhooks:** Rejected because any network timeout or unreachable listener would block Git commits or crash `taskctl done`.

## 4. Consequences and Trade-offs
### Positive
- Strict typing and isolated unittests across core, providers, and webhooks.
- Zero side-effects when remote providers or webhook endpoints are offline.
- High compatibility across Linux, macOS, and Windows/WSL2.

### Negative / Accepted Risks
- Multi-file distribution requires `pyproject.toml` packaging (`pip install -e .` or package distribution).

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/INVARIANTS.md](file:///home/yegear/github/taskctl/.agent/INVARIANTS.md)
