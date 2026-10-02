"""Telemetry package for taskctl - VictoriaLogs/Vector NDJSON telemetry."""

from taskctl.telemetry.events import TelemetryEvent, get_utc_iso_timestamp
from taskctl.telemetry.sink import (
    VectorSink,
    TelemetryEmitter,
    get_telemetry_emitter,
)

__all__ = [
    "TelemetryEvent",
    "get_utc_iso_timestamp",
    "VectorSink",
    "TelemetryEmitter",
    "get_telemetry_emitter",
]
