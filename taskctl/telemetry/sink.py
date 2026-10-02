"""Vector direct HTTP sink and Telemetry Emitter for taskctl."""

import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

from taskctl.telemetry.events import TelemetryEvent


class VectorSink:
    """Direct HTTP sink for Vector's HTTP source endpoint (:8686/logs).
    
    Accepts individual JSON events or batches conforming to the VictoriaLogs contract.
    Guarantees non-blocking and fail-safe behavior.
    """

    def __init__(self, endpoint_url: Optional[str] = None, timeout: float = 2.0):
        self.endpoint_url = endpoint_url or self._resolve_endpoint()
        self.timeout = float(os.environ.get("TASKCTL_TELEMETRY_TIMEOUT", timeout))

    @staticmethod
    def _resolve_endpoint() -> Optional[str]:
        explicit_url = os.environ.get("TASKCTL_VECTOR_URL") or os.environ.get("VECTOR_URL")
        if explicit_url and explicit_url.strip():
            return explicit_url.strip()

        vector_host = os.environ.get("VECTOR_HOST")
        if vector_host and vector_host.strip():
            port = os.environ.get("VECTOR_HTTP_PORT", "8686")
            return f"http://{vector_host.strip()}:{port.strip()}/logs"

        return None

    def is_configured(self) -> bool:
        return bool(self.endpoint_url and self.endpoint_url.startswith("http"))

    def send_event(self, event: TelemetryEvent) -> bool:
        """Send a single telemetry event to the Vector HTTP sink.
        
        Returns True if successfully received (HTTP 200/204), False otherwise.
        Never raises exceptions (fail-safe by system contract).
        """
        if not self.is_configured():
            return False

        payload = event.to_dict()
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint_url,  # type: ignore[arg-type]
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "taskctl-telemetry/0.2.1",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.status in (200, 204)
        except Exception as e:
            # System Invariant 3: Fail-safe, non-blocking telemetry
            if os.environ.get("TASKCTL_TELEMETRY_DEBUG") == "1":
                print(f"[DEBUG VectorSink] Telemetry delivery failed: {e}", file=sys.stderr)
            return False


class TelemetryEmitter:
    """Coordinates telemetry emission across sinks (Vector HTTP and NDJSON streams)."""

    def __init__(
        self,
        vector_sink: Optional[VectorSink] = None,
        emit_ndjson_stdout: Optional[bool] = None,
    ):
        self.vector_sink = vector_sink or VectorSink()
        if emit_ndjson_stdout is None:
            self.emit_ndjson_stdout = os.environ.get("TASKCTL_LOG_NDJSON") == "1"
        else:
            self.emit_ndjson_stdout = emit_ndjson_stdout

    def emit(self, event: TelemetryEvent) -> bool:
        """Emit event to all active sinks, propagating active trace context if missing."""
        if event.trace_id is None or event.span_id is None:
            try:
                from taskctl.telemetry.tracing import get_tracer
                ctx = get_tracer().get_current_context()
                if ctx:
                    if event.trace_id is None:
                        event.trace_id = ctx.trace_id
                    if event.span_id is None:
                        event.span_id = ctx.span_id
                    if event.parent_span_id is None:
                        event.parent_span_id = ctx.parent_span_id
            except Exception:
                pass

        if self.emit_ndjson_stdout:
            sys.stdout.write(event.to_ndjson() + "\n")
            sys.stdout.flush()

        if self.vector_sink.is_configured():
            return self.vector_sink.send_event(event)
        return True

    def emit_span(self, span: Any) -> bool:
        """Export a completed Span as a canonical TelemetryEvent."""
        level = "info" if span.status == "OK" else "warn"
        msg = f"Span [{span.name}] completed in {span.duration_ms:.2f}ms ({span.status})"
        if span.status_message:
            msg += f": {span.status_message}"

        event = TelemetryEvent(
            message=msg,
            level=level,
            duration_ms=span.duration_ms,
            event_type="span",
            task_id=str(span.tags.get("task_id", "") or "") or None,
            trace_id=span.trace_id,
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            details={
                "span_name": span.name,
                "status": span.status,
                "tags": span.tags,
                "events": [
                    {"name": e.name, "timestamp": e.timestamp, "attributes": e.attributes}
                    for e in span.events
                ],
            },
        )
        return self.emit(event)

    def emit_lifecycle_event(
        self,
        event_type: str,
        task_id: Optional[str],
        message: str,
        status: Optional[str] = None,
        duration_ms: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        level: str = "info",
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
    ) -> bool:
        """Helper to create and emit a lifecycle event."""
        event_details = dict(details or {})
        if status:
            event_details["status"] = status

        event = TelemetryEvent(
            message=message,
            level=level,
            duration_ms=duration_ms,
            event_type=event_type,
            task_id=task_id,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            details=event_details,
        )
        return self.emit(event)

    def record_provider_call(
        self,
        provider: str,
        operation: str,
        duration_ms: float,
        success: bool,
        metadata: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> bool:
        """Capture provider call duration, status, and metadata."""
        level = "info" if success else "warn"
        details: Dict[str, Any] = {
            "provider": provider,
            "operation": operation,
            "success": success,
        }
        if metadata:
            details.update(metadata)

        event = TelemetryEvent(
            message=f"Provider [{provider}] executed '{operation}' in {duration_ms:.2f}ms (success={success})",
            level=level,
            duration_ms=duration_ms,
            event_type="provider_call",
            task_id=task_id,
            details=details,
        )
        return self.emit(event)


_GLOBAL_EMITTER: Optional[TelemetryEmitter] = None


def get_telemetry_emitter() -> TelemetryEmitter:
    """Retrieve or initialize the global TelemetryEmitter instance."""
    global _GLOBAL_EMITTER
    if _GLOBAL_EMITTER is None:
        _GLOBAL_EMITTER = TelemetryEmitter()
    return _GLOBAL_EMITTER
