"""Unit tests for taskctl distributed tracing, spans, SLA analytics, and CLI trace command."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from taskctl.telemetry.tracing import (
    TraceContext,
    Span,
    Tracer,
    DurationAnalyzer,
    TracingAlertPolicy,
    generate_trace_id,
    generate_span_id,
    get_tracer,
)
from taskctl.telemetry.events import TelemetryEvent
from taskctl.telemetry.sink import TelemetryEmitter, VectorSink
from taskctl.cli import cmd_trace


class TestTraceContext(unittest.TestCase):
    def test_generate_ids(self):
        trace_id = generate_trace_id()
        span_id = generate_span_id()
        self.assertEqual(len(trace_id), 32)
        self.assertEqual(len(span_id), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in trace_id))
        self.assertTrue(all(c in "0123456789abcdef" for c in span_id))

    def test_new_root_context(self):
        ctx = TraceContext.new_root()
        self.assertEqual(len(ctx.trace_id), 32)
        self.assertEqual(len(ctx.span_id), 16)
        self.assertIsNone(ctx.parent_span_id)
        self.assertEqual(ctx.trace_flags, "01")
        tp = ctx.to_traceparent()
        self.assertTrue(tp.startswith("00-"))
        self.assertIn(ctx.trace_id, tp)
        self.assertIn(ctx.span_id, tp)

    def test_child_context_propagation(self):
        parent = TraceContext.new_root()
        child = parent.child_context()
        self.assertEqual(child.trace_id, parent.trace_id)
        self.assertEqual(child.parent_span_id, parent.span_id)
        self.assertNotEqual(child.span_id, parent.span_id)

    def test_parse_w3c_traceparent(self):
        valid = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ctx = TraceContext.from_traceparent(valid)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.trace_id, "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertEqual(ctx.span_id, "00f067aa0ba902b7")
        self.assertEqual(ctx.trace_flags, "01")

        # Invalid strings
        self.assertIsNone(TraceContext.from_traceparent(""))
        self.assertIsNone(TraceContext.from_traceparent("invalid-header"))
        self.assertIsNone(TraceContext.from_traceparent("00-00000000000000000000000000000000-00f067aa0ba902b7-01"))


class TestSpanAndTracer(unittest.TestCase):
    def setUp(self):
        self.tracer = Tracer(service_name="test-service")

    def test_start_and_end_span(self):
        with self.tracer.start_span("root_op", tags={"task_id": "01.1"}) as span:
            self.assertEqual(span.name, "root_op")
            self.assertEqual(span.tags.get("task_id"), "01.1")
            self.assertEqual(span.status, "OK")
            span.add_event("marker", {"step": 1})
            span.set_tag("custom", "val")

        self.assertIsNotNone(span.end_time_ns)
        self.assertGreaterEqual(span.duration_ms, 0.0)
        completed = self.tracer.get_completed_spans()
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].name, "root_op")
        self.assertEqual(completed[0].tags.get("custom"), "val")
        self.assertEqual(len(completed[0].events), 1)

    def test_nested_spans(self):
        with self.tracer.start_span("parent") as p:
            with self.tracer.start_span("child") as c:
                self.assertEqual(c.trace_id, p.trace_id)
                self.assertEqual(c.parent_span_id, p.span_id)

        spans = self.tracer.get_completed_spans()
        self.assertEqual(len(spans), 2)

    def test_exception_handling_in_span(self):
        try:
            with self.tracer.start_span("failing_op"):
                raise ValueError("Operation failed intentionally")
        except ValueError:
            pass

        spans = self.tracer.get_completed_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].status, "ERROR")
        self.assertIn("Operation failed intentionally", spans[0].status_message)
        self.assertEqual(spans[0].events[0].name, "exception")


class TestTracingAlertPolicy(unittest.TestCase):
    def test_sla_breach_detection(self):
        policy = TracingAlertPolicy(audit_duration_max_ms=10.0, provider_call_max_ms=5.0)
        ctx = TraceContext.new_root()
        span = Span(name="cli.audit", context=ctx, start_time_ns=0, end_time_ns=20_000_000) # 20ms
        alert = policy.check_span_duration(span)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["alert"], "SLA_BREACH")
        self.assertEqual(alert["category"], "audit")
        self.assertAlmostEqual(alert["threshold_ms"], 10.0)
        self.assertAlmostEqual(alert["exceeded_ms"], 10.0)

    def test_sla_within_limits(self):
        policy = TracingAlertPolicy(audit_duration_max_ms=5000.0)
        ctx = TraceContext.new_root()
        span = Span(name="cli.audit", context=ctx, start_time_ns=0, end_time_ns=1000_000_000) # 1000ms
        self.assertIsNone(policy.check_span_duration(span))


class TestDurationAnalyzer(unittest.TestCase):
    def test_analyze_spans(self):
        ctx = TraceContext.new_root()
        s1 = Span(name="git", context=ctx, start_time_ns=0, end_time_ns=10_000_000) # 10ms
        s2 = Span(name="git", context=ctx, start_time_ns=0, end_time_ns=20_000_000) # 20ms
        s3 = Span(name="audit", context=ctx, start_time_ns=0, end_time_ns=30_000_000) # 30ms

        res = DurationAnalyzer.analyze_spans([s1, s2, s3])
        self.assertEqual(res["total_spans"], 3)
        self.assertAlmostEqual(res["total_duration_ms"], 60.0)
        self.assertAlmostEqual(res["avg_duration_ms"], 20.0)
        self.assertEqual(res["by_name"]["git"]["count"], 2)
        self.assertAlmostEqual(res["by_name"]["git"]["total_ms"], 30.0)

    def test_render_tree(self):
        root_ctx = TraceContext.new_root()
        child_ctx = root_ctx.child_context()
        s1 = Span(name="root", context=root_ctx, start_time_ns=0, end_time_ns=50_000_000)
        s2 = Span(name="child", context=child_ctx, start_time_ns=0, end_time_ns=20_000_000)

        tree = DurationAnalyzer.render_tree([s1, s2])
        self.assertIn("[root]", tree)
        self.assertIn("[child]", tree)
        self.assertTrue("├──" in tree or "└──" in tree)


class TestTelemetryEventAndSinkTracing(unittest.TestCase):
    def test_event_serialization_with_tracing(self):
        event = TelemetryEvent(
            message="Test trace event",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            parent_span_id="1111222233334444",
            duration_ms=12.34,
        )
        d = event.to_dict()
        self.assertEqual(d["trace_id"], "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertEqual(d["span_id"], "00f067aa0ba902b7")
        self.assertEqual(d["parent_span_id"], "1111222233334444")
        self.assertEqual(d["duration_ms"], 12.34)

    def test_emitter_auto_inject_active_trace(self):
        tracer = get_tracer()
        emitter = TelemetryEmitter(emit_ndjson_stdout=False)
        with tracer.start_span("active_work") as span:
            event = TelemetryEvent(message="Inner message")
            emitter.emit(event)
            self.assertEqual(event.trace_id, span.trace_id)
            self.assertEqual(event.span_id, span.span_id)

    def test_emit_span_method(self):
        emitter = TelemetryEmitter(emit_ndjson_stdout=False)
        ctx = TraceContext.new_root()
        span = Span(name="unit_task", context=ctx, start_time_ns=0, end_time_ns=15_000_000)
        span.set_tag("task_id", "04.3")
        res = emitter.emit_span(span)
        self.assertTrue(res)


class TestCliTraceCommand(unittest.TestCase):
    def test_cmd_trace_empty(self):
        tracer = get_tracer()
        tracer.clear()
        ret = cmd_trace()
        self.assertEqual(ret, 0)

    def test_cmd_trace_with_spans(self):
        tracer = get_tracer()
        tracer.clear()
        with tracer.start_span("cli.audit", tags={"task_id": "04.3"}):
            with tracer.start_span("audit.rules"):
                pass
        ret = cmd_trace(last=True, analytics=True)
        self.assertEqual(ret, 0)

    def test_cmd_trace_json(self):
        tracer = get_tracer()
        tracer.clear()
        with tracer.start_span("sample"):
            pass
        ret = cmd_trace(json_output=True, analytics=True)
        self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
