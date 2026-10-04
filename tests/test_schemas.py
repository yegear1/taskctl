import json
import unittest
from unittest.mock import MagicMock, patch

from taskctl.schemas import ContractValidationError, load_schema, validate_instance
from taskctl.telemetry.events import TelemetryEvent
from taskctl.telemetry.sink import VectorSink
from taskctl.webhooks.dispatcher import WebhookDispatcher


def _posted_body(mock_urlopen: MagicMock) -> dict:
    req = mock_urlopen.call_args[0][0]
    loaded = json.loads(req.data.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise AssertionError("posted body must be a JSON object")
    return loaded


class TestPayloadSchemas(unittest.TestCase):
    def test_schema_documents_are_versioned(self):
        webhook = load_schema("v1/webhook-event")
        vector = load_schema("v1/vector-event")
        self.assertEqual(webhook["x-taskctl-schema-version"], "1.0.0")
        self.assertEqual(vector["x-taskctl-schema-version"], "1.0.0")
        self.assertIn("webhook-event.schema.json", webhook["$id"])
        self.assertIn("vector-event.schema.json", vector["$id"])

    @patch("urllib.request.urlopen")
    def test_generic_webhook_body_matches_schema(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        dispatcher = WebhookDispatcher(webhook_url="https://example.test/hooks")
        self.assertTrue(
            dispatcher.send_event(
                event_type="audit",
                task_id="01.2",
                title="Schema pin",
                status="APPROVED",
                details={"commit": "abc1234"},
            )
        )
        validate_instance(_posted_body(mock_urlopen), load_schema("v1/webhook-event"))

    def test_webhook_schema_rejects_invalid_payloads(self):
        schema = load_schema("v1/webhook-event")
        with self.assertRaises(ContractValidationError):
            validate_instance({"task_id": "01.2", "title": "t", "status": "DONE", "details": {}}, schema)
        with self.assertRaises(ContractValidationError):
            validate_instance(
                {
                    "event": "audit",
                    "task_id": "01.2",
                    "title": "t",
                    "status": "DONE",
                    "details": {},
                    "embeds": [],
                },
                schema,
            )

    @patch("urllib.request.urlopen")
    def test_discord_and_slack_bodies_are_outside_webhook_schema(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp
        schema = load_schema("v1/webhook-event")

        discord = WebhookDispatcher(webhook_url="https://discord.com/api/webhooks/123/token")
        self.assertTrue(discord.send_event("audit", "01.2", "Title", "APPROVED", {"commit": "abc"}))
        with self.assertRaises(ContractValidationError):
            validate_instance(_posted_body(mock_urlopen), schema)

        slack = WebhookDispatcher(webhook_url="https://hooks.slack.com/services/T00/B00/X00")
        self.assertTrue(slack.send_event("task_completed", "01.2", "Title", "DONE", {"commit": "def"}))
        with self.assertRaises(ContractValidationError):
            validate_instance(_posted_body(mock_urlopen), schema)

    def test_vector_event_examples_match_schema(self):
        schema = load_schema("v1/vector-event")
        minimal = TelemetryEvent(message="Task lifecycle event")
        validate_instance(minimal.to_dict(), schema)

        full = TelemetryEvent(
            message="Scope audit completed",
            level="WARN",
            duration_ms=142.856,
            event_type="audit",
            task_id="01.2",
            workspace="/tmp/repo",
            trace_id="tr-987",
            span_id="span-1",
            parent_span_id="span-0",
            request_id="req-123",
            http_status=200,
            stack_trace="Traceback\nline",
            details={"rules_evaluated": 5},
        )
        validate_instance(full.to_dict(), schema)

    def test_vector_schema_rejects_invalid_payloads(self):
        schema = load_schema("v1/vector-event")
        valid = TelemetryEvent(message="ok").to_dict()
        missing = dict(valid)
        del missing["message"]
        with self.assertRaises(ContractValidationError):
            validate_instance(missing, schema)

        bad_level = dict(valid)
        bad_level["level"] = "ERROR"
        with self.assertRaises(ContractValidationError):
            validate_instance(bad_level, schema)

        extra = dict(valid)
        extra["userId"] = "123"
        with self.assertRaises(ContractValidationError):
            validate_instance(extra, schema)

        bad_time = dict(valid)
        bad_time["timestamp"] = "yesterday"
        with self.assertRaises(ContractValidationError):
            validate_instance(bad_time, schema)

    @patch("urllib.request.urlopen")
    def test_vector_sink_body_matches_schema(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        sink = VectorSink(endpoint_url="http://127.0.0.1:8686/logs")
        self.assertTrue(
            sink.send_event(TelemetryEvent(message="Audit completed", task_id="01.2", duration_ms=45.2))
        )
        validate_instance(_posted_body(mock_urlopen), load_schema("v1/vector-event"))


if __name__ == "__main__":
    unittest.main()
