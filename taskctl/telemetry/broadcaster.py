"""Fail-safe multi-sink broadcaster for cross-repo task lifecycle telemetry."""

import os
from typing import Any, Dict, Optional

from taskctl.telemetry.aggregator import WorkspaceEvent
from taskctl.telemetry.events import TelemetryEvent
from taskctl.telemetry.sink import TelemetryEmitter, get_telemetry_emitter
from taskctl.providers.maestri import send_canvas_notification
from taskctl.webhooks.dispatcher import WebhookDispatcher


class TelemetryBroadcaster:
    """Dispatches cross-repo lifecycle events and status summaries to Vector, Canvas, and Webhooks."""

    def __init__(
        self,
        emitter: Optional[TelemetryEmitter] = None,
        webhook_dispatcher: Optional[WebhookDispatcher] = None,
        broadcast_vector: bool = True,
        broadcast_canvas: bool = True,
        broadcast_webhook: bool = True,
    ):
        self.emitter = emitter or get_telemetry_emitter()
        self.webhook = webhook_dispatcher or WebhookDispatcher()
        self.broadcast_vector = broadcast_vector
        self.broadcast_canvas = broadcast_canvas
        self.broadcast_webhook = broadcast_webhook

    def broadcast_event(self, event: WorkspaceEvent) -> Dict[str, bool]:
        """Broadcast a WorkspaceEvent to all configured sinks.

        Guaranteed non-blocking and fail-safe by System Invariant 3.
        """
        results: Dict[str, bool] = {
            "vector": False,
            "canvas": False,
            "webhook": False,
        }

        # 1. Vector / VictoriaLogs sink
        if self.broadcast_vector:
            try:
                level = "info"
                if "REJECTED" in (event.new_status or "").upper():
                    level = "error"
                elif "CHANGES REQUIRED" in (event.new_status or "").upper():
                    level = "warn"

                telemetry_event = TelemetryEvent(
                    message=f"[{event.event_type.upper()}] {event.message}",
                    level=level,
                    event_type=f"cross_repo_{event.event_type}",
                    task_id=event.task_id,
                    workspace=event.repo_name,
                    details={
                        "repo_path": event.repo_path,
                        "repo_name": event.repo_name,
                        "old_status": event.old_status,
                        "new_status": event.new_status,
                        **event.details,
                    },
                )
                results["vector"] = bool(self.emitter.emit(telemetry_event))
            except Exception:
                pass

        # 2. Agent Canvas sink (Maestri)
        if self.broadcast_canvas:
            try:
                canvas_msg = f"[{event.repo_name}] {event.message}"
                results["canvas"] = bool(send_canvas_notification(canvas_msg))
            except Exception:
                pass

        # 3. Webhook sink (Slack / Discord)
        if self.broadcast_webhook and self.webhook.is_configured():
            try:
                status_str = event.new_status or "INFO"
                task_id_str = event.task_id or "CROSS-REPO"
                title_str = f"[{event.repo_name}] {event.message}"
                results["webhook"] = bool(
                    self.webhook.send_event(
                        event_type=event.event_type,
                        task_id=task_id_str,
                        title=title_str,
                        status=status_str,
                        details=event.details,
                    )
                )
            except Exception:
                pass

        return results

    def broadcast_summary(
        self,
        summary: Dict[str, Any],
        custom_msg: Optional[str] = None,
    ) -> Dict[str, bool]:
        """Broadcast an aggregated roll-up summary to configured sinks."""
        results: Dict[str, bool] = {
            "vector": False,
            "canvas": False,
            "webhook": False,
        }

        total = summary.get("total_workspaces", 0)
        status_counts = summary.get("status_counts", {})
        status_desc = ", ".join(f"{k}: {v}" for k, v in status_counts.items()) if status_counts else "idle"
        msg = custom_msg or f"Cross-repo summary: {total} workspaces monitored ({status_desc})"

        # 1. Vector sink
        if self.broadcast_vector:
            try:
                event = TelemetryEvent(
                    message=msg,
                    level="info",
                    event_type="cross_repo_summary",
                    details=summary,
                )
                results["vector"] = bool(self.emitter.emit(event))
            except Exception:
                pass

        # 2. Canvas sink
        if self.broadcast_canvas:
            try:
                canvas_line = f"🌐 {msg}"
                results["canvas"] = bool(send_canvas_notification(canvas_line))
            except Exception:
                pass

        # 3. Webhook sink
        if self.broadcast_webhook and self.webhook.is_configured():
            try:
                results["webhook"] = bool(
                    self.webhook.send_event(
                        event_type="summary",
                        task_id="CROSS-REPO",
                        title=msg,
                        status="SUMMARY",
                        details={
                            "summary": msg,
                            "total_workspaces": total,
                            "status_breakdown": status_counts,
                        },
                    )
                )
            except Exception:
                pass

        return results
