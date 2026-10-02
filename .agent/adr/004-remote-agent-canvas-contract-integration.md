# [ADR-004] Remote Agent Canvas Contract Engine Integration & Maestri IPC

- **Status:** Approved
- **Date:** 2026-10-01
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
Autonomous multi-agent orchestration frameworks (such as Maestri) feature a 2D spatial canvas with interconnected agent terminals, notes, and browser portals. While `taskctl` maintains the source of truth for task contracts, invariants, and Definition of Done in local markdown (`.agent/TASK.md`), remote canvas agents and human observers require real-time visibility into the active task cockpit, bidirectional synchronization with canvas notes, workspace provisioning, and non-blocking inter-agent notification and delegation.

## 2. Decision Outcome
We implemented a resilient, non-blocking remote agent canvas provider adapter in `taskctl.providers.maestri`:
- **Dual Transport Discovery (UNIX Domain Socket IPC & CLI Fallback):**
  - `MaestriIPCClient` manages low-latency communication via UNIX domain sockets, discovering paths through `MAESTRI_SOCKET_PATH`, `MAESTRI_SOCKET`, and uid-based socket matching (`/tmp/maestri-{uid}/maestri.sock`).
  - Graceful fallback to `maestri` CLI (`MAESTRI_CLI`, `~/.local/bin/maestri`, `/usr/local/bin/maestri`, or PATH) when the domain socket is unavailable.
- **Fail-Safe & Non-Blocking Resilience:**
  - All socket operations enforce strict 2.0-second timeouts and catch all socket exceptions (`ConnectionRefusedError`, `FileNotFoundError`, etc.).
  - Maestri unavailability never blocks local git commands, task promotions, or task completions.
  - Duration and success metrics are emitted to VictoriaLogs / Vector telemetry sinks via `record_provider_call(provider="maestri", ...)`.
- **Bidirectional Note Synchronization:**
  - Pushing (`taskctl sync` / `--push`) writes or creates the pinned `task-cockpit-agent-task-md` note on the canvas.
  - Pulling (`taskctl sync --pull`) reads the canvas note and validates the markdown schema prior to updating local `.agent/TASK.md`.
  - Line prefix normalization (`strip_note_line_numbers`) safely parses line-numbered outputs from CLI `note read`.
- **Remote Canvas Workspace & Agent Delegation:**
  - `taskctl ws [name]`: Provisions a dedicated Maestri workspace rooted at the repository directory and initializes the canvas cockpit note.
  - `taskctl plan "<prompt>"`: Sets active task status to `PLANNING` and delegates decomposition to the connected `Planner` agent on the canvas.
  - `taskctl notify <msg>`: Dispatches notifications to the Maestri canvas alongside configured Webhooks and Vector sinks.

## 3. Alternatives Considered
- **Direct Filesystem Manipulation of Maestri State:** Rejected because Maestri manages internal canvas geometry, ropes, and session states. Direct socket/CLI contracts ensure high fidelity and safety.
- **Synchronous Blocking Remote Calls:** Rejected because any network latency or daemon downtime would violate Rule 3 of the Rule Precedence Hierarchy (Fail-Safe & Non-Blocking Execution).

## 4. Consequences and Trade-offs
### Positive
- Real-time bidirectional synchronization between local repository governance and the spatial agent canvas.
- Zero-crash fallback when Maestri is not installed or when running in headless CI environments.
- 100% hermetically testable using standard Python mocks.

### Negative / Accepted Risks
- Canvas note pulls require valid TASK.md markdown schemas; corrupt notes are rejected to prevent local file damage.

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/ECOSYSTEM.md](file:///home/yegear/github/taskctl/.agent/ECOSYSTEM.md)
- [.agent/TASK.md](file:///home/yegear/github/taskctl/.agent/TASK.md)
- [.agent/skills/provider-adapter/SKILL.md](file:///home/yegear/github/taskctl/.agent/skills/provider-adapter/SKILL.md)
