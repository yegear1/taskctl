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
from taskctl.telemetry.broadcaster import TelemetryBroadcaster
from taskctl.telemetry.daemon import TelemetryDaemon

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
]
