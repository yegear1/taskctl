"""Unit tests for VictoriaLogs client, TaskTraceAggregator, and rendering helpers."""

import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from taskctl.telemetry.tracing import Span, TraceContext, Tracer
from taskctl.telemetry.victorialogs import (
    TaskCycleSummary,
    TaskTraceAggregator,
    VictoriaLogsClient,
    render_cycle_summary,
    render_cycle_waterfall,
)


class TestVictoriaLogsClient(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)

    def test_endpoint_resolution_default(self):
        os.environ.pop("TASKCTL_VICTORIALOGS_URL", None)
        os.environ.pop("VICTORIALOGS_URL", None)
        os.environ.pop("VICTORIALOGS_HTTP_HOST", None)
        os.environ.pop("VICTORIALOGS_HOST", None)
        client = VictoriaLogsClient()
        self.assertEqual(client.endpoint_url, "http://localhost:9428")

    def test_endpoint_resolution_env_vars(self):
        os.environ["VICTORIALOGS_URL"] = "http://victoria.homelab:9428/"
        client = VictoriaLogsClient()
        self.assertEqual(client.endpoint_url, "http://victoria.homelab:9428")

        os.environ["TASKCTL_VICTORIALOGS_URL"] = "http://override.local:9428"
        client2 = VictoriaLogsClient()
        self.assertEqual(client2.endpoint_url, "http://override.local:9428")

    def test_endpoint_resolution_host_port(self):
        os.environ.pop("TASKCTL_VICTORIALOGS_URL", None)
        os.environ.pop("VICTORIALOGS_URL", None)
        os.environ["VICTORIALOGS_HTTP_HOST"] = "192.168.1.50"
        os.environ["VICTORIALOGS_HTTP_PORT"] = "9429"
        client = VictoriaLogsClient()
        self.assertEqual(client.endpoint_url, "http://192.168.1.50:9429")

    @patch("urllib.request.urlopen")
    def test_is_healthy_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = VictoriaLogsClient("http://localhost:9428")
        self.assertTrue(client.is_healthy())

    @patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused"))
    def test_is_healthy_fail_safe(self, mock_urlopen):
        client = VictoriaLogsClient("http://localhost:9428")
        self.assertFalse(client.is_healthy())

    @patch("urllib.request.urlopen")
    def test_query_logsql_ndjson_parsing(self, mock_urlopen):
        records = [
            {"event_type": "span", "message": "Span [cli.next] completed", "duration_ms": 120.5, "trace_id": "abc"},
            {"event_type": "span", "message": "Span [cli.audit] completed", "duration_ms": 340.2, "trace_id": "abc"},
        ]
        ndjson_body = "\n".join(json.dumps(r) for r in records).encode("utf-8")

        mock_resp = io.BytesIO(ndjson_body)
        mock_resp.status = 200  # type: ignore[attr-defined]
        mock_resp.__enter__ = lambda s: s  # type: ignore[assignment]
        mock_resp.__exit__ = lambda s, *args: None  # type: ignore[assignment]
        mock_urlopen.return_value = mock_resp

        client = VictoriaLogsClient("http://localhost:9428")
        results = client.query_logsql('task_id:"02.8"', limit=10, time_range="24h")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["duration_ms"], 120.5)
        self.assertEqual(results[1]["message"], "Span [cli.audit] completed")

    @patch("urllib.request.urlopen", side_effect=TimeoutError("timed out"))
    def test_query_logsql_timeout_fail_safe(self, mock_urlopen):
        client = VictoriaLogsClient("http://localhost:9428")
        results = client.query_logsql('task_id:"02.8"')
        self.assertEqual(results, [])


class TestTaskTraceAggregator(unittest.TestCase):
    def test_build_summary_from_remote_records(self):
        client = MagicMock()
        client.is_healthy.return_value = True
        aggregator = TaskTraceAggregator(client=client)

        records = [
            {
                "event_type": "span",
                "message": "Span [cli.next] completed in 150.00ms (OK)",
                "duration_ms": 150.0,
                "trace_id": "11112222333344441111222233334444",
                "span_id": "s1",
                "timestamp": "2026-10-17T12:00:00.000Z",
                "details": {"status": "OK"},
            },
            {
                "event_type": "command_blocked",
                "message": "Dangerous command intercepted",
                "details": {
                    "command": "rm -rf /",
                    "risk_level": "CRITICAL",
                    "score": 98.0,
                    "reason": "Root deletion forbidden",
                    "decision": "DENY",
                },
                "timestamp": "2026-10-17T12:00:01.000Z",
            },
            {
                "event_type": "span",
                "message": "Span [cli.audit] completed in 320.00ms (OK)",
                "duration_ms": 320.0,
                "trace_id": "11112222333344441111222233334444",
                "span_id": "s2",
                "timestamp": "2026-10-17T12:00:02.000Z",
                "details": {"status": "OK"},
            },
            {
                "event_type": "span",
                "message": "Span [cli.done] completed in 210.00ms (OK)",
                "duration_ms": 210.0,
                "trace_id": "11112222333344441111222233334444",
                "span_id": "s3",
                "timestamp": "2026-10-17T12:00:03.000Z",
                "details": {"status": "OK"},
            },
            {
                "event_type": "token_telemetry_summary",
                "details": {
                    "summary": {
                        "total_tokens": 15000,
                        "prompt_tokens": 10000,
                        "completion_tokens": 5000,
                        "thinking_tokens": 1200,
                        "turns": 12,
                        "tool_calls": 6,
                        "role_breakdown": [
                            {"role": "Scope Auditor", "tokens": 6000, "turns": 4, "tools": 2},
                            {"role": "Developer", "tokens": 9000, "turns": 8, "tools": 4},
                        ],
                    }
                },
            },
        ]
        client.query_logsql.return_value = records

        summary = aggregator.aggregate_task_cycle(task_id="02.8", trace_id="11112222333344441111222233334444")
        self.assertEqual(summary.task_id, "02.8")
        self.assertEqual(summary.status, "COMPLETED")
        self.assertEqual(len(summary.timeline), 3)
        self.assertEqual(summary.timeline[0]["name"], "cli.next")
        self.assertEqual(summary.timeline[1]["name"], "cli.audit")
        self.assertEqual(summary.timeline[2]["name"], "cli.done")
        self.assertEqual(len(summary.blocked_commands), 1)
        self.assertEqual(summary.blocked_commands[0]["command"], "rm -rf /")
        self.assertEqual(summary.blocked_commands[0]["risk_level"], "CRITICAL")
        self.assertEqual(summary.tokens["total_tokens"], 15000)

    def test_local_fallback_when_offline(self):
        client = MagicMock()
        client.is_healthy.return_value = False
        tracer = Tracer(service_name="test_tracer")
        tracer.clear()

        ctx = TraceContext.new_root()
        span1 = tracer.start_span("cli.next", parent=ctx, tags={"task_id": "02.8"})
        span1.end()
        span2 = tracer.start_span("runner.execute", parent=ctx, tags={"task_id": "02.8"})
        span2.add_event("command_blocked", {"command": "mkfs.ext4 /dev/sda", "risk_level": "CRITICAL", "score": 90.0, "reason": "Disk format prohibited"})
        span2.end()

        aggregator = TaskTraceAggregator(client=client, tracer=tracer)
        summary = aggregator.aggregate_task_cycle(task_id="02.8", trace_id=ctx.trace_id)

        self.assertEqual(summary.task_id, "02.8")
        self.assertEqual(summary.trace_id, ctx.trace_id)
        self.assertEqual(len(summary.timeline), 2)
        self.assertEqual(summary.timeline[0]["name"], "cli.next")
        self.assertEqual(summary.timeline[1]["name"], "runner.execute")
        self.assertEqual(len(summary.blocked_commands), 1)
        self.assertEqual(summary.blocked_commands[0]["command"], "mkfs.ext4 /dev/sda")

    def test_render_cycle_summary_formatting(self):
        summary = TaskCycleSummary(
            task_id="02.8",
            trace_id="4e962325383081638ff876c2fa566890",
            status="COMPLETED",
            total_duration_ms=680.5,
            timeline=[
                {"name": "cli.next", "duration_ms": 120.0, "offset": "+0.00s", "status": "OK"},
                {"name": "cli.audit", "duration_ms": 350.0, "offset": "+0.12s", "status": "OK"},
                {"name": "cli.done", "duration_ms": 210.5, "offset": "+0.47s", "status": "OK"},
            ],
            blocked_commands=[
                {"command": "rm -rf /", "risk_level": "CRITICAL", "score": 95.0, "reason": "Root wipe denied", "timestamp": "2026-10-17T12:00:00Z"},
            ],
            tokens={
                "total_tokens": 12450,
                "prompt_tokens": 8200,
                "completion_tokens": 4250,
                "thinking_tokens": 1100,
                "turns": 14,
                "tool_calls": 8,
                "role_breakdown": [
                    {"role": "Scope Auditor", "tokens": 4500, "turns": 5, "tools": 2},
                    {"role": "Developer", "tokens": 7950, "turns": 9, "tools": 6},
                ],
            },
        )
        rendered = render_cycle_summary(summary)
        self.assertIn("TASK CYCLE LIFECYCLE TRACE: [02.8] (COMPLETED)", rendered)
        self.assertIn("Trace ID: 4e962325383081638ff876c2fa566890", rendered)
        self.assertIn("[cli.next]", rendered)
        self.assertIn("[cli.audit]", rendered)
        self.assertIn("[cli.done]", rendered)
        self.assertIn("rm -rf /", rendered)
        self.assertIn("12,450", rendered)
        self.assertIn("Scope Auditor", rendered)


if __name__ == "__main__":
    unittest.main()
