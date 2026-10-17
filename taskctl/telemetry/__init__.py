"""Telemetry package for taskctl - VictoriaLogs/Vector NDJSON telemetry."""

from taskctl.telemetry.events import TelemetryEvent, get_utc_iso_timestamp
from taskctl.telemetry.sink import (
    VectorSink,
    TelemetryEmitter,
    get_telemetry_emitter,
)
from taskctl.telemetry.aggregator import (
    WorkspaceState,
    WorkspaceEvent,
    CrossRepoAggregator,
)

__all__ = [
    "TelemetryEvent",
    "get_utc_iso_timestamp",
    "VectorSink",
    "TelemetryEmitter",
    "get_telemetry_emitter",
    "WorkspaceState",
    "WorkspaceEvent",
    "CrossRepoAggregator",
    "TelemetryBroadcaster",
    "TelemetryDaemon",
    "TraceContext",
    "Span",
    "Tracer",
    "get_tracer",
    "DurationAnalyzer",
    "TracingAlertPolicy",
    "normalize_trace_id",
    "save_active_trace",
    "load_active_trace",
    "clear_active_trace",
    "SessionTokenRecord",
    "RoleTokenAggregation",
    "collect_token_telemetry",
    "VictoriaLogsClient",
    "TaskTraceAggregator",
    "TaskCycleSummary",
    "render_cycle_summary",
    "render_cycle_waterfall",
]


def __getattr__(name: str):
    if name == "TelemetryBroadcaster":
        from taskctl.telemetry.broadcaster import TelemetryBroadcaster
        return TelemetryBroadcaster
    if name == "TelemetryDaemon":
        from taskctl.telemetry.daemon import TelemetryDaemon
        return TelemetryDaemon
    if name in (
        "TraceContext",
        "Span",
        "Tracer",
        "get_tracer",
        "DurationAnalyzer",
        "TracingAlertPolicy",
        "normalize_trace_id",
        "save_active_trace",
        "load_active_trace",
        "clear_active_trace",
    ):
        from taskctl.telemetry import tracing
        return getattr(tracing, name)
    if name in (
        "SessionTokenRecord",
        "RoleTokenAggregation",
        "collect_token_telemetry",
    ):
        from taskctl.telemetry import tokens
        return getattr(tokens, name)
    if name in (
        "VictoriaLogsClient",
        "TaskTraceAggregator",
        "TaskCycleSummary",
        "render_cycle_summary",
        "render_cycle_waterfall",
    ):
        from taskctl.telemetry import victorialogs
        return getattr(victorialogs, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
