# [ADR-002] VictoriaLogs & Vector Direct Sink Integration with Provider Telemetry

- **Status:** Approved
- **Date:** 2026-10-01
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
In multi-agent environments, tasks transition through critical lifecycles (`task_started`, `audit`, `task_completed`), and external orchestrator provider calls (`multigravity`, `maestri`) incur variable latencies or sporadic daemon disconnects. Observability is essential to analyze agent performance, quota routing latencies, and scope audit verdicts without polluting commit history or risking CLI downtime when observability sinks are unreachable.

## 2. Decision Outcome
We implemented a dedicated telemetry subsystem in `taskctl.telemetry` featuring:
1. **Canonical Schema:** Strict adherence to the `ye-sandbox` VictoriaLogs contract (`timestamp` UTC ISO-8601 with millisecond precision, lowercase `level`, `service`, `app`, `env`, `message`, and `duration_ms`). High-cardinality values (`task_id`, `details`) are strictly kept as event attributes, preventing stream dimension explosions.
2. **Direct Vector Sink (`VectorSink`):** Connects to Vector's HTTP input endpoint (`:8686/logs` or configurable via `TASKCTL_VECTOR_URL`/`VECTOR_URL`) sending atomic JSON log objects.
3. **Fail-Safe & Non-Blocking Execution:** Strict 2-second timeout and exception encapsulation ensuring telemetry failures never interrupt CLI execution or block git operations (satisfying System Invariant 3).
4. **Provider Latency Tracing:** Instrumentation of `multigravity` and `maestri` providers to record `duration_ms`, execution status, and operation metadata.
5. **NDJSON Stream Support:** Optional stdout NDJSON emission (`TASKCTL_LOG_NDJSON=1`) for containerized or stream-piped environments.

## 3. Alternatives Considered
- **Direct VictoriaLogs Insertion (`:9428/insert/jsonline`):** Bypassing Vector was rejected because Vector provides edge aggregation, stream tagging, VRL validation, and compression across the homelab infrastructure.
- **Synchronous Telemetry Blocking:** Rejected to maintain absolute adherence to System Invariant 3 (fail-safe and non-blocking).

## 4. Consequences and Trade-offs
### Positive
- Unified observability across CLI lifecycle actions and provider operations.
- Zero network blocking when sinks are down or network is disconnected.
- Hermetic testability with standard library mocking.

### Negative / Accepted Risks
- Network timeouts up to 2 seconds if a configured endpoint hangs (mitigated by configuring `TASKCTL_TELEMETRY_TIMEOUT` and default non-configured state).

## 5. References and Links
- [ADR-001: Modular CLI Architecture](file:///home/yegear/github/taskctl/.agent/adr/001-modular-cli-architecture.md)
- [VictoriaLogs Integration Skill](file:///home/yegear/AntigravityProfiles/yegear/.gemini/config/skills/victorialogs-integration/SKILL.md)
- [.agent/INVARIANTS.md](file:///home/yegear/github/taskctl/.agent/INVARIANTS.md)
