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
    ):
        from taskctl.telemetry import tracing
        return getattr(tracing, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

