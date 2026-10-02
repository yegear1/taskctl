"""Cross-repo telemetry aggregation daemon and status broadcasting service."""

import json
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from taskctl.telemetry.aggregator import CrossRepoAggregator, WorkspaceEvent
from taskctl.telemetry.broadcaster import TelemetryBroadcaster


class TelemetryDaemon:
    """Daemon service that aggregates multi-workspace task events and broadcasts summaries."""

    def __init__(
        self,
        watch_paths: Optional[List[str]] = None,
        interval: float = 5.0,
        broadcast_vector: bool = True,
        broadcast_canvas: bool = True,
        broadcast_webhook: bool = True,
        summary_interval: float = 60.0,
        output_format: str = "text",
    ):
        self.aggregator = CrossRepoAggregator(watch_paths=watch_paths)
        self.broadcaster = TelemetryBroadcaster(
            broadcast_vector=broadcast_vector,
            broadcast_canvas=broadcast_canvas,
            broadcast_webhook=broadcast_webhook,
        )
        self.interval = max(0.5, float(interval))
        self.summary_interval = max(self.interval, float(summary_interval))
        self.output_format = output_format.lower()
        self._running = False
        self._last_summary_time = 0.0

    def stop(self) -> None:
        """Signal daemon to stop execution."""
        self._running = False

    def format_summary_table(self, summary: Dict[str, Any]) -> str:
        """Render a clean terminal table summarizing all monitored workspaces."""
        lines = [
            "==========================================================================================",
            " 🌐 CROSS-REPO WORKSPACE STATUS SUMMARY",
            "==========================================================================================",
        ]

        status_counts = summary.get("status_counts", {})
        status_str = " | ".join(f"{k}: {v}" for k, v in sorted(status_counts.items())) if status_counts else "None"
        lines.append(f" Total Workspaces: {summary.get('total_workspaces', 0)}  |  Statuses: {status_str}")
        lines.append("------------------------------------------------------------------------------------------")
        lines.append(f" {'WORKSPACE':<20} {'TASK ID':<10} {'STATUS':<20} {'PROGRESS':<10} {'COMMIT':<10}")
        lines.append("------------------------------------------------------------------------------------------")

        active_tasks = summary.get("active_tasks", [])
        if not active_tasks:
            lines.append(" (No active workspaces or tasks detected)")
        else:
            for task in active_tasks:
                ws_name = str(task.get("repo_name", ""))[:19]
                task_id = str(task.get("task_id", "-"))[:9]
                status = str(task.get("task_status", "UNKNOWN"))[:19]
                progress = str(task.get("progress", "0/0"))[:9]
                commit = str(task.get("commit", "-"))[:9]
                lines.append(f" {ws_name:<20} {task_id:<10} {status:<20} {progress:<10} {commit:<10}")

        lines.append("==========================================================================================")
        return "\n".join(lines)

    def run_once(self) -> Dict[str, Any]:
        """Execute a single aggregation sweep, broadcast summary, print output, and return."""
        summary = self.aggregator.get_summary()
        self.broadcaster.broadcast_summary(summary)

        if self.output_format == "json":
            print(json.dumps(summary, indent=2))
        else:
            print(self.format_summary_table(summary))

        return summary

    def run(self) -> None:
        """Start long-running aggregation daemon loop."""
        self._running = True

        def _handle_signal(signum: int, frame: Any) -> None:
            sys.stdout.write(f"\n[taskctl daemon] Received signal {signum}, stopping gracefully...\n")
            sys.stdout.flush()
            self._running = False

        # Register POSIX signal handlers
        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, AttributeError):
            pass

        discovered = self.aggregator.discover_repositories()
        print(f"[taskctl daemon] Monitoring {len(discovered)} workspace(s) at {self.interval}s interval:")
        for path in discovered:
            print(f"  - {os.path.basename(path)}: {path}")

        # Initial summary broadcast
        initial_summary = self.aggregator.get_summary()
        self.broadcaster.broadcast_summary(initial_summary)
        self._last_summary_time = time.time()

        if self.output_format != "json":
            print(self.format_summary_table(initial_summary))

        while self._running:
            try:
                events = self.aggregator.poll()
                for event in events:
                    # Print event to stdout
                    if self.output_format == "json":
                        print(json.dumps(event.to_dict()))
                    else:
                        timestamp = event.timestamp.split("T")[-1].replace("Z", "")
                        print(f"[{timestamp}] [{event.repo_name}] {event.message}")

                    # Broadcast event to configured sinks
                    self.broadcaster.broadcast_event(event)

                # Periodic roll-up summary
                now = time.time()
                if now - self._last_summary_time >= self.summary_interval:
                    summary = self.aggregator.get_summary()
                    self.broadcaster.broadcast_summary(summary)
                    self._last_summary_time = now

                # Sleep in small slices to remain interruptible
                sleep_chunk = 0.2
                elapsed = 0.0
                while self._running and elapsed < self.interval:
                    time.sleep(sleep_chunk)
                    elapsed += sleep_chunk

            except Exception as e:
                # Daemon must be resilient to runtime errors
                print(f"[WARN taskctl daemon] Loop iteration error: {e}", file=sys.stderr)
                time.sleep(self.interval)

        print("[taskctl daemon] Shutdown complete.")
