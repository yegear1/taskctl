import unittest
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

if __name__ == "__main__":
    unittest.main()
