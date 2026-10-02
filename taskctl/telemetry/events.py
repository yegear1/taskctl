"""Canonical telemetry event definitions conforming to the VictoriaLogs and Vector pipeline contract."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, Optional


def get_utc_iso_timestamp() -> str:
    """Generate ISO-8601 UTC timestamp with millisecond precision and 'Z' suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class TelemetryEvent:
    message: str
    level: str = "info"
    service: str = field(default_factory=lambda: os.environ.get("SERVICE_NAME", "taskctl"))
    app: str = field(default_factory=lambda: os.environ.get("APP_NAME", os.environ.get("SERVICE_NAME", "taskctl")))
    env: str = field(default_factory=lambda: os.environ.get("ENV", os.environ.get("ENVIRONMENT", "production")))
    timestamp: str = field(default_factory=get_utc_iso_timestamp)
    duration_ms: Optional[float] = None
    event_type: Optional[str] = None
    task_id: Optional[str] = None
    trace_id: Optional[str] = None
    request_id: Optional[str] = None
    http_status: Optional[int] = None
    stack_trace: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to a canonical dictionary for JSON emission.
        
        Canonical root fields are preserved at the top level.
        Event-specific metadata (task_id, event_type, details) are placed at the root
        as event attributes (never stream dimensions).
        """
        payload: Dict[str, Any] = {
            "timestamp": self.timestamp,
            "level": self.level.lower(),
            "service": self.service,
            "app": self.app,
            "env": self.env,
            "message": self.message,
        }
        if self.duration_ms is not None:
            payload["duration_ms"] = round(self.duration_ms, 2)
        if self.event_type is not None:
            payload["event_type"] = self.event_type
        if self.task_id is not None:
            payload["task_id"] = self.task_id
        if self.trace_id is not None:
            payload["trace_id"] = self.trace_id
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.stack_trace is not None:
            payload["stack_trace"] = self.stack_trace
        if self.details:
            payload["details"] = self.details
        return payload

    def to_ndjson(self) -> str:
        """Serialize as a single-line JSON string (NDJSON line)."""
        return json.dumps(self.to_dict(), ensure_ascii=False)
