import os
import unittest
import urllib.error
from unittest.mock import patch, MagicMock
from taskctl.webhooks.dispatcher import WebhookDispatcher

class TestWebhookDispatcher(unittest.TestCase):
    def test_not_configured_returns_false(self):
        dispatcher = WebhookDispatcher(webhook_url="")
        self.assertFalse(dispatcher.is_configured())
        self.assertFalse(dispatcher.send_event("test", "01.1", "Title", "DONE"))

    @patch("urllib.request.urlopen")
    def test_discord_payload_formatting(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        dispatcher = WebhookDispatcher(webhook_url="https://discord.com/api/webhooks/123/token")
        self.assertTrue(dispatcher.is_configured())
        res = dispatcher.send_event(
            event_type="audit",
            task_id="01.1",
            title="Scope Audit Test",
            status="APPROVED",
            details={"commit": "abc1234", "summary": "Diff is clean"}
        )
        self.assertTrue(res)
        self.assertTrue(mock_urlopen.called)

    @patch("urllib.request.urlopen")
    def test_slack_payload_formatting(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        dispatcher = WebhookDispatcher(webhook_url="https://hooks.slack.com/services/T00/B00/X00")
        self.assertTrue(dispatcher.is_configured())
        res = dispatcher.send_event(
            event_type="task_completed",
            task_id="01.2",
            title="Completed Feature",
            status="DONE",
            details={"commit": "def5678"}
        )
        self.assertTrue(res)
        self.assertTrue(mock_urlopen.called)

    @patch("urllib.request.urlopen")
    def test_default_timeout_is_two_seconds(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with patch.dict(os.environ, {}, clear=True):
            dispatcher = WebhookDispatcher(webhook_url="https://example.test/hooks")
            self.assertEqual(dispatcher.timeout, 2.0)
            self.assertTrue(dispatcher.send_event("audit", "01.1", "Title", "DONE"))

        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 2.0)

    @patch("urllib.request.urlopen")
    def test_timeout_honors_telemetry_env(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with patch.dict(os.environ, {"TASKCTL_TELEMETRY_TIMEOUT": "0.5"}, clear=True):
            dispatcher = WebhookDispatcher(webhook_url="https://example.test/hooks")
            self.assertEqual(dispatcher.timeout, 0.5)
            self.assertTrue(dispatcher.send_event("audit", "01.1", "Title", "DONE"))

        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 0.5)

    def test_invalid_timeout_falls_back_to_default(self):
        with patch.dict(os.environ, {"TASKCTL_TELEMETRY_TIMEOUT": "nope"}, clear=True):
            dispatcher = WebhookDispatcher(webhook_url="https://example.test/hooks")
            self.assertEqual(dispatcher.timeout, 2.0)
        with patch.dict(os.environ, {"TASKCTL_TELEMETRY_TIMEOUT": "-1"}, clear=True):
            dispatcher = WebhookDispatcher(webhook_url="https://example.test/hooks")
            self.assertEqual(dispatcher.timeout, 2.0)

    @patch("urllib.request.urlopen")
    def test_bearer_header_when_token_set(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        env = {"TASKCTL_WEBHOOK_TOKEN": "secret-token"}
        with patch.dict(os.environ, env, clear=True):
            dispatcher = WebhookDispatcher(webhook_url="https://example.test/hooks")
            self.assertTrue(dispatcher.send_event("audit", "01.1", "Title", "DONE"))

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_header("Authorization"), "Bearer secret-token")

    @patch("urllib.request.urlopen")
    def test_bearer_header_omitted_when_token_unset(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with patch.dict(os.environ, {}, clear=True):
            dispatcher = WebhookDispatcher(webhook_url="https://example.test/hooks")
            self.assertTrue(dispatcher.send_event("audit", "01.1", "Title", "DONE"))

        req = mock_urlopen.call_args[0][0]
        self.assertIsNone(req.get_header("Authorization"))

    @patch("urllib.request.urlopen", side_effect=TimeoutError("timed out"))
    def test_timeout_returns_false(self, mock_urlopen):
        dispatcher = WebhookDispatcher(webhook_url="https://example.test/hooks")
        self.assertFalse(dispatcher.send_event("audit", "01.1", "Title", "DONE"))
        self.assertTrue(mock_urlopen.called)

    @patch("urllib.request.urlopen", side_effect=OSError("unreachable"))
    def test_unreachable_url_returns_false(self, mock_urlopen):
        dispatcher = WebhookDispatcher(webhook_url="https://example.test/hooks")
        self.assertFalse(dispatcher.send_event("audit", "01.1", "Title", "DONE"))
        self.assertTrue(mock_urlopen.called)

    def test_non_http_url_returns_false(self):
        dispatcher = WebhookDispatcher(webhook_url="ftp://example.test/hooks")
        self.assertFalse(dispatcher.is_configured())
        with patch("urllib.request.urlopen") as mock_urlopen:
            self.assertFalse(dispatcher.send_event("audit", "01.1", "Title", "DONE"))
            mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_http_error_returns_false(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://example.test/hooks",
            500,
            "Server Error",
            hdrs=None,
            fp=None,
        )
        dispatcher = WebhookDispatcher(webhook_url="https://example.test/hooks")
        self.assertFalse(dispatcher.send_event("audit", "01.1", "Title", "DONE"))


if __name__ == "__main__":
    unittest.main()
