# TASK.md — Current Task and Roadmap

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [XX.Y]: [Short descriptive title]

- **Description:** Implement distributed tracing context and telemetry spans across taskctl lifecycle transitions and provider operations, including trace propagation (TraceContext / W3C traceparent compatible), span hierarchy, task duration analytics, and alerting thresholds for VictoriaLogs/Vector.
- **Systems Involved:** [core, telemetry, cli]
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash'
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [x] Implement `TraceContext` and `Span` / `Tracer` abstraction in `taskctl.telemetry` with deterministic 128-bit trace ID and 64-bit span ID generation (hex formatted, W3C traceparent / OpenTelemetry compatible).
- [x] Support root spans and nested child spans for lifecycle phases (`next`, `audit`, `done`, `daemon`, `graph`, and provider adapter calls) with duration tracking in milliseconds.
- [x] Connect tracing context to `TelemetryEvent`, `VectorSink`, and `TelemetryEmitter` so trace_id, span_id, and parent_span_id are preserved in canonical VictoriaLogs payloads.
- [x] Add task duration analytics and threshold checks (e.g., alert trigger if task duration or provider execution exceeds SLA thresholds).
- [x] Expose trace inspection via CLI (e.g. `taskctl trace` or flags) and ensure hermetic unit tests with 100% pass rate.
- [x] Verify DoD: syntax compile, unittest suite pass, `git diff --check`, and ADR-007 documentation.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [04.3] | Task lifecycle distributed tracing & telemetry spans (trace IDs, task duration analytics, VictoriaLogs/Vector alerts) | [`8ff9acd`] | 2026-10-02 |
| [04.2] | Task dependency graph visualizer (CLI tree, Mermaid generator, TUI DAG viewer & cycle detector) | [`db34834`] | 2026-10-02 |
| [04.1] | Cross-repo telemetry aggregation daemon and status broadcaster | [`c41588f`] | 2026-10-02 |
| [03.7] | Interactive terminal dashboard enhancements (mouse scroll support, split-pane diff viewer) | [`eac2934`] | 2026-10-02 |
| [03.6] | GitHub Actions pre-commit and Scope Auditor CI workflow | [`5b7605f`] | 2026-10-02 |
| [03.5] | Interactive terminal dashboard prototype for active task and DoD checklist | [`e462d77`] | 2026-10-02 |
| [03.4] | Autonomous agent lifecycle hand-offs on task start (cmd_next) and task completion (cmd_done) | [`e33c6f8`] | 2026-10-02 |
| [03.2] | Canvas topology presets & workspace generator integration in Maestri provider | [`86b86fe`] | 2026-10-02 |
| [03.3] | Hybrid Scope Auditor with canvas agent delegation fallback | [`e239433`] | 2026-10-02 |
| [03.1] | Contract engine integration with remote agent canvas | [`9a51fe2`] | 2026-10-02 |
| [02.2] | Automated commit message Conventional Commits linter & policy | [`e3168c7`] | 2026-10-01 |
| [00.0] | Initial scaffolding (ADD greenfield template) | [`1d74dac`] | 2026-10-01 |
| [01.1] | Taskctl core engine, CLI, providers, and test suite | [`8875338`, `d3de1aa`] | 2026-10-01 |
| [01.2] | Scope auditor rule-based policy expansion | [`b07e582`] | 2026-10-01 |
| [02.1] | Advanced provider telemetry & Vector direct sink integration | [`c720980`] | 2026-10-01 |

---

## Backlog (Upcoming, in priority order)

*(Backlog empty - all milestone epics through [04.3] scheduled or complete)*

---

## Release / Cycle Wrap-up (Not the next task)

Release/tag only with explicit human request. When triggered, the ID is `[99.1]`. Do not number feature, hygiene, or CI tasks as `99.x`. Do not calculate next task ID from this section.

---

## Future Backlog / Ideas (Unprioritized)

*(Future backlog empty)*

---

## How to Keep this File Lean

1. Detail only in the active task. When complete $\rightarrow$ log one line and promote the next task.
2. Backlog is a list of titles. Full spec only when an item becomes the active task.
3. Next ID = last ID in log (or active task). Cycle wrap-up and `[99.1]`: see `AGENTS.md`.
