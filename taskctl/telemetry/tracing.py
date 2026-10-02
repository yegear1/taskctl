"""Distributed tracing, spans, and SLA threshold duration analytics for taskctl.

Adheres to W3C TraceContext standards (128-bit hex trace ID, 64-bit hex span ID).
Supports nested hierarchical spans, duration analytics, and fail-safe alerts.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import re
import secrets
import sys
import time
from typing import Any, Callable, Dict, List, Optional


_W3C_TRACEPARENT_REGEX = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def generate_trace_id() -> str:
    """Generate a random 128-bit trace ID formatted as a 32-character lower-hex string."""
    return secrets.token_hex(16)


def generate_span_id() -> str:
    """Generate a random 64-bit span ID formatted as a 16-character lower-hex string."""
    return secrets.token_hex(8)


@dataclass(frozen=True)
class TraceContext:
    """Immutable W3C TraceContext container."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    trace_flags: str = "01"  # "01" indicates sampled

    @classmethod
    def new_root(cls, trace_flags: str = "01") -> TraceContext:
        """Create a new root trace context with fresh IDs."""
        return cls(
            trace_id=generate_trace_id(),
            span_id=generate_span_id(),
            parent_span_id=None,
            trace_flags=trace_flags,
        )

    def child_context(self) -> TraceContext:
        """Derive a child context sharing trace_id, with self.span_id as parent_span_id."""
        return TraceContext(
            trace_id=self.trace_id,
            span_id=generate_span_id(),
            parent_span_id=self.span_id,
            trace_flags=self.trace_flags,
        )

    def to_traceparent(self) -> str:
        """Format as standard W3C traceparent header: 00-{trace_id}-{span_id}-{flags}."""
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"

    @classmethod
    def from_traceparent(cls, header: Optional[str]) -> Optional[TraceContext]:
        """Parse W3C traceparent header. Returns None if invalid or missing."""
        if not header:
            return None
        match = _W3C_TRACEPARENT_REGEX.match(header.strip().lower())
        if not match:
            return None
        _, trace_id, span_id, flags = match.groups()
        if trace_id == "0" * 32 or span_id == "0" * 16:
            return None
        return cls(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            trace_flags=flags,
        )


@dataclass
class SpanEvent:
    name: str
    timestamp: str
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    """Execution span representing a timed lifecycle phase or unit of work."""
    name: str
    context: TraceContext
    start_time_ns: int = field(default_factory=time.perf_counter_ns)
    end_time_ns: Optional[int] = None
    status: str = "OK"  # "OK", "ERROR", "TIMEOUT", "CANCELLED"
    status_message: Optional[str] = None
    tags: Dict[str, Any] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)
    _tracer: Optional[Tracer] = field(default=None, repr=False)

    @property
    def trace_id(self) -> str:
        return self.context.trace_id

    @property
    def span_id(self) -> str:
        return self.context.span_id

    @property
    def parent_span_id(self) -> Optional[str]:
        return self.context.parent_span_id

    @property
    def duration_ms(self) -> float:
        end = self.end_time_ns if self.end_time_ns is not None else time.perf_counter_ns()
        return round((end - self.start_time_ns) / 1_000_000.0, 2)

    def set_tag(self, key: str, value: Any) -> Span:
        self.tags[key] = value
        return self

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> Span:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        self.events.append(SpanEvent(name=name, timestamp=now_iso, attributes=attributes or {}))
        return self

    def set_status(self, status: str, message: Optional[str] = None) -> Span:
        self.status = status.upper()
        if message:
            self.status_message = message
        return self

    def end(self, status: Optional[str] = None, message: Optional[str] = None) -> None:
        if self.end_time_ns is None:
            self.end_time_ns = time.perf_counter_ns()
        if status:
            self.set_status(status, message)
        if self._tracer:
            self._tracer._on_span_ended(self)

    def __enter__(self) -> Span:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self.set_status("ERROR", str(exc_val))
            self.add_event("exception", {"type": exc_type.__name__, "message": str(exc_val)})
        self.end()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "status_message": self.status_message,
            "tags": self.tags,
            "events": [
                {"name": e.name, "timestamp": e.timestamp, "attributes": e.attributes}
                for e in self.events
            ],
        }


# Context variable tracking currently active span in thread/async execution
_CURRENT_SPAN: contextvars.ContextVar[Optional[Span]] = contextvars.ContextVar(
    "_CURRENT_SPAN", default=None
)


class TracingAlertPolicy:
    """Configurable duration thresholds triggering SLA alerts."""

    def __init__(
        self,
        audit_duration_max_ms: float = 8000.0,
        provider_call_max_ms: float = 3000.0,
        command_max_ms: float = 10000.0,
        task_duration_warning_hours: float = 24.0,
    ):
        self.audit_duration_max_ms = float(
            os.environ.get("TASKCTL_SLA_AUDIT_MS", audit_duration_max_ms)
        )
        self.provider_call_max_ms = float(
            os.environ.get("TASKCTL_SLA_PROVIDER_MS", provider_call_max_ms)
        )
        self.command_max_ms = float(
            os.environ.get("TASKCTL_SLA_COMMAND_MS", command_max_ms)
        )
        self.task_duration_warning_hours = float(
            os.environ.get("TASKCTL_SLA_TASK_HOURS", task_duration_warning_hours)
        )

    def check_span_duration(self, span: Span) -> Optional[Dict[str, Any]]:
        """Evaluate if span duration exceeds SLA limits, returning alert details if breached."""
        name = span.name.lower()
        dur = span.duration_ms

        limit = None
        category = "general"

        if "audit" in name:
            limit = self.audit_duration_max_ms
            category = "audit"
        elif "provider" in name:
            limit = self.provider_call_max_ms
            category = "provider"
        elif "cli." in name or "cmd_" in name:
            limit = self.command_max_ms
            category = "command"

        if limit is not None and dur > limit:
            return {
                "alert": "SLA_BREACH",
                "category": category,
                "span_name": span.name,
                "duration_ms": dur,
                "threshold_ms": limit,
                "exceeded_ms": round(dur - limit, 2),
                "severity": "warn" if dur < (limit * 2) else "error",
            }
        return None


class Tracer:
    """Manages active span stack, trace context propagation, and span lifecycle."""

    def __init__(
        self,
        service_name: str = "taskctl",
        alert_policy: Optional[TracingAlertPolicy] = None,
        exporter: Optional[Callable[[Span], None]] = None,
    ):
        self.service_name = service_name
        self.alert_policy = alert_policy or TracingAlertPolicy()
        self.exporter = exporter
        self._completed_spans: List[Span] = []
        self._max_history = int(os.environ.get("TASKCTL_TRACE_HISTORY", "500"))

    def get_current_span(self) -> Optional[Span]:
        """Return the currently active span in context."""
        return _CURRENT_SPAN.get()

    def get_current_context(self) -> Optional[TraceContext]:
        """Return the current active TraceContext if one exists."""
        span = self.get_current_span()
        return span.context if span else None

    def start_span(
        self,
        name: str,
        parent: Optional[Span | TraceContext] = None,
        tags: Optional[Dict[str, Any]] = None,
    ) -> Span:
        """Start a new span.
        
        If parent is not specified, attempts to use the active span context,
        or looks up external TRACEPARENT / TASKCTL_TRACE_ID env vars,
        otherwise creates a new root context.
        """
        active_span = self.get_current_span()
        ctx: TraceContext

        if isinstance(parent, Span):
            ctx = parent.context.child_context()
        elif isinstance(parent, TraceContext):
            ctx = parent.child_context()
        elif active_span is not None:
            ctx = active_span.context.child_context()
        else:
            env_tp = os.environ.get("TRACEPARENT") or os.environ.get("TASKCTL_TRACEPARENT")
            parsed_tp = TraceContext.from_traceparent(env_tp)
            if parsed_tp:
                ctx = parsed_tp.child_context()
            else:
                explicit_trace_id = os.environ.get("TASKCTL_TRACE_ID")
                if explicit_trace_id and len(explicit_trace_id.strip()) == 32:
                    ctx = TraceContext(
                        trace_id=explicit_trace_id.strip(),
                        span_id=generate_span_id(),
                        parent_span_id=None,
                    )
                else:
                    ctx = TraceContext.new_root()

        span = Span(
            name=name,
            context=ctx,
            tags=dict(tags or {}),
            _tracer=self,
        )
        span.set_tag("service", self.service_name)
        _CURRENT_SPAN.set(span)
        return span

    def _on_span_ended(self, span: Span) -> None:
        """Called when a span completes."""
        active = _CURRENT_SPAN.get()
        if active is span:
            # Pop active span or reset
            _CURRENT_SPAN.set(None)

        self._completed_spans.append(span)
        if len(self._completed_spans) > self._max_history:
            self._completed_spans.pop(0)

        # SLA threshold check
        alert = self.alert_policy.check_span_duration(span)
        if alert:
            span.set_tag("sla_alert", alert)
            # Emit telemetry alert if emitter is available
            self._emit_alert_event(span, alert)

        # Notify exporter if registered
        if self.exporter:
            try:
                self.exporter(span)
            except Exception as e:
                if os.environ.get("TASKCTL_TELEMETRY_DEBUG") == "1":
                    print(f"[DEBUG Tracer] Exporter failed: {e}", file=sys.stderr)

    def _emit_alert_event(self, span: Span, alert: Dict[str, Any]) -> None:
        """Fail-safe emission of SLA alert to VectorSink."""
        try:
            from taskctl.telemetry.events import TelemetryEvent
            from taskctl.telemetry.sink import get_telemetry_emitter

            emitter = get_telemetry_emitter()
            msg = (
                f"SLA Alert: Span '{span.name}' took {span.duration_ms:.2f}ms "
                f"(threshold: {alert['threshold_ms']:.2f}ms, exceeded by {alert['exceeded_ms']:.2f}ms)"
            )
            event = TelemetryEvent(
                message=msg,
                level=alert.get("severity", "warn"),
                duration_ms=span.duration_ms,
                event_type="sla_alert",
                task_id=str(span.tags.get("task_id", "") or ""),
                trace_id=span.trace_id,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                details={
                    "span_id": span.span_id,
                    "parent_span_id": span.parent_span_id,
                    "span_name": span.name,
                    **alert,
                },
            )
            emitter.emit(event)
        except Exception:
            pass

    def get_completed_spans(self, trace_id: Optional[str] = None) -> List[Span]:
        """Return completed spans, optionally filtered by trace_id."""
        if trace_id:
            return [s for s in self._completed_spans if s.trace_id == trace_id]
        return list(self._completed_spans)

    def clear(self) -> None:
        """Clear span buffer."""
        self._completed_spans.clear()


class DurationAnalyzer:
    """Calculates lifecycle and provider metrics and aggregations."""

    @staticmethod
    def analyze_spans(spans: List[Span]) -> Dict[str, Any]:
        """Aggregate total, average, min, max durations across a span set."""
        if not spans:
            return {
                "total_spans": 0,
                "total_duration_ms": 0.0,
                "avg_duration_ms": 0.0,
                "max_duration_ms": 0.0,
                "min_duration_ms": 0.0,
                "by_name": {},
            }

        total_dur = sum(s.duration_ms for s in spans)
        by_name: Dict[str, List[float]] = {}
        for s in spans:
            by_name.setdefault(s.name, []).append(s.duration_ms)

        stats_by_name = {
            name: {
                "count": len(durs),
                "total_ms": round(sum(durs), 2),
                "avg_ms": round(sum(durs) / len(durs), 2),
                "max_ms": round(max(durs), 2),
                "min_ms": round(min(durs), 2),
            }
            for name, durs in by_name.items()
        }

        return {
            "total_spans": len(spans),
            "total_duration_ms": round(total_dur, 2),
            "avg_duration_ms": round(total_dur / len(spans), 2),
            "max_duration_ms": round(max(s.duration_ms for s in spans), 2),
            "min_duration_ms": round(min(s.duration_ms for s in spans), 2),
            "by_name": stats_by_name,
        }

    @staticmethod
    def render_tree(spans: List[Span]) -> str:
        """Render an ASCII waterfall / hierarchy tree of spans."""
        if not spans:
            return "No spans recorded."

        roots: List[Span] = [s for s in spans if not s.parent_span_id or not any(x.span_id == s.parent_span_id for x in spans)]
        children_map: Dict[str, List[Span]] = {}
        for s in spans:
            if s.parent_span_id:
                children_map.setdefault(s.parent_span_id, []).append(s)

        lines: List[str] = []

        def _print_node(span: Span, prefix: str, is_last: bool):
            connector = "└── " if is_last else "├── "
            status_icon = "✅" if span.status == "OK" else "❌"
            sla_tag = " ⚠️ [SLA BREACH]" if "sla_alert" in span.tags else ""
            line = f"{prefix}{connector}{status_icon} [{span.name}] {span.duration_ms:.2f}ms (span: {span.span_id[:8]}){sla_tag}"
            lines.append(line)
            child_prefix = prefix + ("    " if is_last else "│   ")
            kids = children_map.get(span.span_id, [])
            for idx, kid in enumerate(kids):
                _print_node(kid, child_prefix, idx == len(kids) - 1)

        for i, root in enumerate(roots):
            _print_node(root, "", i == len(roots) - 1)

        return "\n".join(lines)


_GLOBAL_TRACER: Optional[Tracer] = None


def get_tracer() -> Tracer:
    """Retrieve or initialize the global Tracer instance."""
    global _GLOBAL_TRACER
    if _GLOBAL_TRACER is None:
        _GLOBAL_TRACER = Tracer()
    return _GLOBAL_TRACER
