import io
import json
import os
import unittest
from unittest.mock import patch, MagicMock

from taskctl.telemetry.events import TelemetryEvent, get_utc_iso_timestamp
from taskctl.telemetry.sink import VectorSink, TelemetryEmitter, get_telemetry_emitter
from taskctl.providers.multigravity import get_profile_quotas
from taskctl.providers.maestri import run_maestri_cli


class TestTelemetryEvent(unittest.TestCase):
    def test_canonical_fields_defaults(self):
        with patch.dict(os.environ, {"SERVICE_NAME": "taskctl-test", "ENV": "staging"}, clear=False):
            event = TelemetryEvent(message="Task lifecycle event")
            data = event.to_dict()

            self.assertEqual(data["service"], "taskctl-test")
            self.assertEqual(data["app"], "taskctl-test")
            self.assertEqual(data["env"], "staging")
            self.assertEqual(data["level"], "info")
            self.assertEqual(data["message"], "Task lifecycle event")
            self.assertTrue(data["timestamp"].endswith("Z"))
            self.assertNotIn("duration_ms", data)
            self.assertNotIn("details", data)

    def test_full_event_ndjson_serialization(self):
        event = TelemetryEvent(
            message="Scope audit completed",
            level="WARN",
            duration_ms=142.856,
            event_type="audit",
            task_id="02.1",
            trace_id="tr-987",
            request_id="req-123",
            http_status=200,
            details={"rules_evaluated": 5, "status": "APPROVED"},
        )
        data = event.to_dict()
        self.assertEqual(data["level"], "warn")
        self.assertEqual(data["duration_ms"], 142.86)
        self.assertEqual(data["event_type"], "audit")
        self.assertEqual(data["task_id"], "02.1")
        self.assertEqual(data["trace_id"], "tr-987")
        self.assertEqual(data["request_id"], "req-123")
        self.assertEqual(data["http_status"], 200)
        self.assertEqual(data["details"]["rules_evaluated"], 5)

        ndjson = event.to_ndjson()
        self.assertNotIn("\n", ndjson)
        parsed = json.loads(ndjson)
        self.assertEqual(parsed["message"], "Scope audit completed")


class TestVectorSink(unittest.TestCase):
    def test_not_configured_when_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            sink = VectorSink()
            self.assertFalse(sink.is_configured())
            event = TelemetryEvent(message="test")
            self.assertFalse(sink.send_event(event))

    def test_endpoint_resolution_from_vector_url(self):
        with patch.dict(os.environ, {"TASKCTL_VECTOR_URL": "http://vector.internal:8686/logs"}):
            sink = VectorSink()
            self.assertTrue(sink.is_configured())
            self.assertEqual(sink.endpoint_url, "http://vector.internal:8686/logs")

    def test_endpoint_resolution_from_host_and_port(self):
        with patch.dict(os.environ, {"VECTOR_HOST": "mini-pc", "VECTOR_HTTP_PORT": "9000"}, clear=True):
            sink = VectorSink()
            self.assertTrue(sink.is_configured())
            self.assertEqual(sink.endpoint_url, "http://mini-pc:9000/logs")

    @patch("urllib.request.urlopen")
    def test_send_event_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        sink = VectorSink(endpoint_url="http://localhost:8686/logs", timeout=1.5)
        event = TelemetryEvent(message="Audit completed", task_id="02.1", duration_ms=45.2)

        ok = sink.send_event(event)
        self.assertTrue(ok)
        self.assertTrue(mock_urlopen.called)

        # Inspect request arguments
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "http://localhost:8686/logs")
        self.assertEqual(req.headers["Content-type"], "application/json")
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["message"], "Audit completed")
        self.assertEqual(body["duration_ms"], 45.2)

    @patch("urllib.request.urlopen", side_effect=Exception("Connection refused"))
    def test_send_event_fail_safe_non_blocking(self, mock_urlopen):
        sink = VectorSink(endpoint_url="http://localhost:8686/logs")
        event = TelemetryEvent(message="Dropped packet")

        # Must not raise exception
        ok = sink.send_event(event)
        self.assertFalse(ok)


class TestTelemetryEmitter(unittest.TestCase):
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_emit_ndjson_stdout_when_configured(self, mock_stdout):
        sink = VectorSink()  # Unconfigured
        emitter = TelemetryEmitter(vector_sink=sink, emit_ndjson_stdout=True)
        event = TelemetryEvent(message="CLI running", task_id="01.1")

        emitter.emit(event)
        output = mock_stdout.getvalue()
        self.assertTrue(output.endswith("\n"))
        data = json.loads(output.strip())
        self.assertEqual(data["task_id"], "01.1")

    def test_emit_lifecycle_event(self):
        mock_sink = MagicMock()
        mock_sink.is_configured.return_value = True
        mock_sink.send_event.return_value = True

        emitter = TelemetryEmitter(vector_sink=mock_sink, emit_ndjson_stdout=False)
        ok = emitter.emit_lifecycle_event(
            event_type="task_started",
            task_id="02.1",
            message="Task active",
            status="RUNNING",
            duration_ms=12.5,
            details={"actor": "yegear"},
        )
        self.assertTrue(ok)
        self.assertTrue(mock_sink.send_event.called)
        sent_event = mock_sink.send_event.call_args[0][0]
        self.assertEqual(sent_event.event_type, "task_started")
        self.assertEqual(sent_event.details["status"], "RUNNING")
        self.assertEqual(sent_event.details["actor"], "yegear")

    def test_record_provider_call(self):
        mock_sink = MagicMock()
        mock_sink.is_configured.return_value = True
        mock_sink.send_event.return_value = True

        emitter = TelemetryEmitter(vector_sink=mock_sink, emit_ndjson_stdout=False)
        emitter.record_provider_call(
            provider="multigravity",
            operation="quota",
            duration_ms=88.4,
            success=True,
            metadata={"profiles": 3},
            task_id="02.1",
        )
        self.assertTrue(mock_sink.send_event.called)
        event = mock_sink.send_event.call_args[0][0]
        self.assertEqual(event.event_type, "provider_call")
        self.assertEqual(event.duration_ms, 88.4)
        self.assertEqual(event.details["provider"], "multigravity")
        self.assertEqual(event.details["operation"], "quota")
        self.assertTrue(event.details["success"])


class TestProviderLatencyTelemetry(unittest.TestCase):
    @patch("shutil.which", return_value="/bin/multigravity")
    @patch("subprocess.run")
    def test_multigravity_latency_telemetry(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([{"profile": "yegear", "buckets": {}}]),
        )
        with patch.object(TelemetryEmitter, "record_provider_call") as mock_record:
            quotas = get_profile_quotas()
            self.assertIn("yegear", quotas)
            self.assertTrue(mock_record.called)
            args, kwargs = mock_record.call_args
            self.assertEqual(kwargs.get("provider", args[1] if len(args) > 1 else None), "multigravity")
            self.assertEqual(kwargs.get("operation", args[2] if len(args) > 2 else None), "quota")
            self.assertTrue(kwargs.get("success", args[4] if len(args) > 4 else None))
            self.assertGreaterEqual(kwargs.get("duration_ms", args[3] if len(args) > 3 else 0.0), 0.0)

    @patch("taskctl.providers.maestri.resolve_maestri_cli", return_value="/bin/maestri")
    @patch("taskctl.providers.maestri.resolve_maestri_socket", return_value="/tmp/test.sock")
    @patch("subprocess.run")
    def test_maestri_latency_telemetry(self, mock_run, mock_sock, mock_cli):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        with patch.object(TelemetryEmitter, "record_provider_call") as mock_record:
            res = run_maestri_cli(["note", "update", "task-note", "content"])
            self.assertIsNotNone(res)
            self.assertTrue(mock_record.called)
            args, kwargs = mock_record.call_args
            self.assertEqual(kwargs.get("provider", args[1] if len(args) > 1 else None), "maestri")
            self.assertTrue(kwargs.get("success", args[4] if len(args) > 4 else None))


if __name__ == "__main__":
    unittest.main()
