"""Webhook Dispatcher for Discord and Slack notifications."""

import os
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List

_DEFAULT_TIMEOUT = 2.0


def _resolve_timeout(timeout: float) -> float:
    """Honor TASKCTL_TELEMETRY_TIMEOUT, falling back to a positive default."""
    raw = os.environ.get("TASKCTL_TELEMETRY_TIMEOUT")
    candidate = timeout
    if raw is not None and raw.strip():
        try:
            candidate = float(raw)
        except ValueError:
            candidate = timeout
    if candidate <= 0:
        return _DEFAULT_TIMEOUT
    return float(candidate)


def _bearer_token() -> Optional[str]:
    token = os.environ.get("TASKCTL_WEBHOOK_TOKEN")
    if token is None:
        return None
    token = token.strip()
    if not token:
        return None
    return token


class WebhookDispatcher:
    def __init__(self, webhook_url: Optional[str] = None, timeout: float = _DEFAULT_TIMEOUT):
        self.webhook_url = webhook_url or os.environ.get("TASKCTL_WEBHOOK_URL")
        self.timeout = _resolve_timeout(timeout)

    def is_configured(self) -> bool:
        return bool(self.webhook_url and self.webhook_url.strip().startswith("http"))

    def send_event(
        self,
        event_type: str,
        task_id: str,
        title: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.is_configured():
            return False

        details = details or {}
        url = self.webhook_url.strip()

        if "discord.com" in url:
            payload = self._build_discord_payload(event_type, task_id, title, status, details)
        elif "slack.com" in url:
            payload = self._build_slack_payload(event_type, task_id, title, status, details)
        else:
            payload = {
                "event": event_type,
                "task_id": task_id,
                "title": title,
                "status": status,
                "details": details,
            }

        return self._post_json(url, payload)

    def _build_discord_payload(
        self,
        event_type: str,
        task_id: str,
        title: str,
        status: str,
        details: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Color codes: Green (0x34C759) for APPROVED/DONE, Orange (0xFF9500) for CHANGES REQUIRED, Red (0xFF3B30) for REJECTED
        color_map = {
            "APPROVED": 0x34C759,
            "DONE": 0x34C759,
            "CHANGES REQUIRED": 0xFF9500,
            "REJECTED": 0xFF3B30,
            "RUNNING": 0x007AFF,
            "PLANNING": 0xAF52DE,
        }
        color = color_map.get(status.upper(), 0x5856D6)

        fields: List[Dict[str, Any]] = [
            {"name": "Task ID", "value": f"`[{task_id}]`", "inline": True},
            {"name": "Status", "value": f"**{status}**", "inline": True},
        ]

        if "commit" in details:
            fields.append({"name": "Commit", "value": f"`{details['commit']}`", "inline": True})
        if "actor" in details:
            fields.append({"name": "Actor / Model", "value": details["actor"], "inline": True})
        if "summary" in details:
            fields.append({"name": "Summary", "value": details["summary"][:1000], "inline": False})
        if "required_action" in details and details["required_action"]:
            fields.append({"name": "Required Action", "value": details["required_action"][:1000], "inline": False})

        embed = {
            "title": f"[{event_type.upper()}] {title}",
            "color": color,
            "fields": fields,
            "footer": {"text": "taskctl lifecycle orchestrator"},
        }
        return {"embeds": [embed]}

    def _build_slack_payload(
        self,
        event_type: str,
        task_id: str,
        title: str,
        status: str,
        details: Dict[str, Any],
    ) -> Dict[str, Any]:
        blocks: List[Dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"[{event_type.upper()}] Task [{task_id}]: {title}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Status:*\n{status}"},
                    {"type": "mrkdwn", "text": f"*Commit:*\n`{details.get('commit', 'N/A')}`"},
                ],
            }
        ]
        if "summary" in details:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Summary:*\n{details['summary']}"}
            })
        return {"blocks": blocks}

    def _post_json(self, url: str, payload: Dict[str, Any]) -> bool:
        try:
            data = json.dumps(payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "taskctl-cli/0.2.0",
            }
            token = _bearer_token()
            if token is not None:
                headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.status in (200, 204)
        except Exception as e:
            # Non-blocking by invariant 3
            print(f"[WARN] Failed to dispatch webhook notification: {e}")
            return False
