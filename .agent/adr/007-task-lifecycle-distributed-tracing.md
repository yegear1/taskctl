# [ADR-007] Task Lifecycle Distributed Tracing, Telemetry Spans & SLA Alerting

- **Status:** Approved
- **Date:** 2026-10-02
- **Author(s):** yegear / lead systems engineer

---

## 1. Context and Problem Statement
As autonomous AI agents, background daemons, and human operators execute complex multi-step workflows (`next`, `audit`, `done`, `daemon`, `ws`, `plan`), correlating events and diagnosing performance bottlenecks across distributed systems (local CLI, Maestri canvas IPC, and VictoriaLogs/Vector pipeline) is difficult without standardized trace and span context. Operations require:
1. Deterministic trace IDs and parent-child span hierarchy conforming to standard W3C `traceparent` specifications.
2. Direct correlation in VictoriaLogs with canonical root attributes (`trace_id`, `span_id`, `parent_span_id`, `duration_ms`).
3. Automated SLA threshold checks and alerts when critical operations (scope audits, provider RPCs, commands) exceed performance targets.
4. An ergonomic CLI inspector (`taskctl trace`) for local development and post-run analysis.

## 2. Decision Outcome
We implemented a lightweight, hermetic distributed tracing subsystem in `taskctl.telemetry.tracing`:

- **W3C TraceContext & Identifiers (`TraceContext`):**
  - Adheres strictly to the W3C TraceContext recommendation.
  - Generates 128-bit trace IDs (32 lowercase hex characters) and 64-bit span IDs (16 lowercase hex characters).
  - Formats and parses `00-{trace_id}-{span_id}-{flags}` headers, supporting interoperability with external APM agents and HTTP payloads.
  - Automatically derives child contexts maintaining trace ID invariance and linking `parent_span_id`.

- **Hierarchical Spans & Context Management (`Span`, `Tracer`):**
  - Spans represent timed units of work using high-resolution monotonic nanosecond timers (`time.perf_counter_ns`), computing precise `duration_ms`.
  - Python context manager support (`with tracer.start_span("cli.audit") as span:`) for clean scoping and automatic exception trapping.
  - Asynchronous and thread-safe active span propagation via `contextvars.ContextVar`.

- **VictoriaLogs & Vector Schema Integration:**
  - `TelemetryEvent` and `VectorSink` now natively support `trace_id`, `span_id`, and `parent_span_id` as top-level event attributes.
  - `TelemetryEmitter.emit` automatically enriches outbound events with the active trace/span context if omitted.
  - `TelemetryEmitter.emit_span(span)` exports completed spans as structured `event_type="span"` records.

- **SLA Duration Analytics & Threshold Alerting (`TracingAlertPolicy`, `DurationAnalyzer`):**
  - Configurable duration boundaries via environment variables (`TASKCTL_SLA_AUDIT_MS`, `TASKCTL_SLA_PROVIDER_MS`, `TASKCTL_SLA_COMMAND_MS`).
  - Triggers automated fail-safe VictoriaLogs events (`event_type="sla_alert"`, level `warn` or `error`) when operations exceed thresholds.
  - `DurationAnalyzer` provides aggregate statistical metrics (`count`, `total_ms`, `avg_ms`, `max_ms`, `min_ms`) and renders ASCII waterfall tree visualizers.

- **CLI Trace Inspection (`taskctl trace`):**
  - `taskctl trace [--id <trace_id>] [--last] [--json] [--analytics]` displays live in-memory trace trees or machine-readable JSON metrics.

## 3. Alternatives Considered
- **OpenTelemetry Python SDK (`opentelemetry-api`, `opentelemetry-sdk`):** Rejected to preserve the core architectural invariant of zero non-standard runtime dependencies. `taskctl` operates with standard library Python 3.10+ while remaining schema-compatible with OpenTelemetry collectors via Vector.
- **AsyncIO-Only Tracing:** Rejected because `taskctl` CLI is synchronous standard-library Python, needing robust context tracking that works across both synchronous and multi-threaded/daemon executions.

## 4. Consequences and Trade-offs
### Positive
- Zero external dependencies.
- Standard W3C `traceparent` compatibility for multi-agent workflows.
- Rich observability in VictoriaLogs and Vector without risk of process abortion.
- Immediate developer feedback on execution bottlenecks and SLA violations.

### Negative / Accepted Risks
- In-memory trace buffer defaults to 500 completed spans; long-running daemons prune older spans to prevent memory leaks.

## 5. References and Links
- [AGENTS.md](file:///home/yegear/github/taskctl/AGENTS.md)
- [.agent/TASK.md](file:///home/yegear/github/taskctl/.agent/TASK.md)
- [ADR-002: Vector Telemetry Sink](file:///home/yegear/github/taskctl/.agent/adr/002-vector-telemetry-sink.md)
- [ADR-005: Cross-Repo Telemetry Aggregation Daemon](file:///home/yegear/github/taskctl/.agent/adr/005-cross-repo-telemetry-aggregation-daemon.md)
