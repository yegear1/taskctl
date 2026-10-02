"""Unit tests for CrossRepoAggregator, TelemetryBroadcaster, and TelemetryDaemon."""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from taskctl.cli import main, cmd_daemon, cmd_broadcast
from taskctl.telemetry import (
    WorkspaceState,
    WorkspaceEvent,
    CrossRepoAggregator,
    TelemetryBroadcaster,
    TelemetryDaemon,
    TelemetryEvent,
)


SAMPLE_TASK_A = """# Tasks & Roadmap

### 📌 Task [01.1]: First Alpha Feature

- **Description:** Implement alpha feature in repo A
- **Systems Involved:** [core, cli]
- **Runtime Target:** Profile 'default' | Model: 'flash'
- **Status:** RUNNING

### Acceptance Criteria
- [x] Item 1
- [ ] Item 2

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [00.1] | Bootstrap setup | [`1234567`] | 2026-10-01 |

---

## Backlog

- [ ] **[01.2]** Next item
"""

SAMPLE_TASK_B = """# Tasks & Roadmap

### 📌 Task [02.1]: Second Beta Feature

- **Description:** Implement beta feature in repo B
- **Systems Involved:** [network]
- **Runtime Target:** Profile 'yegear' | Model: 'pro'
- **Status:** READY FOR PLANNING

### Acceptance Criteria
- [ ] Item B1

---

## Completed Tasks Log

(None)

---

## Backlog

- [ ] **[02.2]** Future item
"""


class TestCrossRepoAggregator(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="taskctl_test_daemon_")
        self.repo_a = os.path.join(self.test_dir, "repo_a")
        self.repo_b = os.path.join(self.test_dir, "repo_b")
        self.not_a_repo = os.path.join(self.test_dir, "other_dir")

        for r, content in [(self.repo_a, SAMPLE_TASK_A), (self.repo_b, SAMPLE_TASK_B)]:
            agent_dir = os.path.join(r, ".agent")
            os.makedirs(agent_dir, exist_ok=True)
            with open(os.path.join(agent_dir, "TASK.md"), "w", encoding="utf-8") as f:
                f.write(content)

        os.makedirs(self.not_a_repo, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_discover_repositories_from_parent_dir(self):
        aggregator = CrossRepoAggregator(watch_paths=[self.test_dir])
        repos = aggregator.discover_repositories()
        self.assertEqual(len(repos), 2)
        self.assertIn(os.path.abspath(self.repo_a), repos)
        self.assertIn(os.path.abspath(self.repo_b), repos)
        self.assertNotIn(os.path.abspath(self.not_a_repo), repos)

    def test_discover_repositories_explicit_paths(self):
        aggregator = CrossRepoAggregator(watch_paths=[self.repo_a])
        repos = aggregator.discover_repositories()
        self.assertEqual(repos, [os.path.abspath(self.repo_a)])

    @patch.dict(os.environ, {"TASKCTL_WATCH_REPOS": ""})
    def test_discover_from_env_var(self):
        env_val = f"{self.repo_a}:{self.repo_b}"
        with patch.dict(os.environ, {"TASKCTL_WATCH_REPOS": env_val}):
            aggregator = CrossRepoAggregator()
            repos = aggregator.discover_repositories()
            self.assertEqual(len(repos), 2)
            self.assertIn(os.path.abspath(self.repo_a), repos)

    def test_scan_workspace_state(self):
        aggregator = CrossRepoAggregator(watch_paths=[self.repo_a])
        state = aggregator.scan_workspace(self.repo_a)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.repo_name, "repo_a")
        self.assertEqual(state.task_id, "01.1")
        self.assertEqual(state.task_status, "RUNNING")
        self.assertEqual(state.criteria_total, 2)
        self.assertEqual(state.criteria_checked, 1)
        self.assertEqual(state.completed_count, 1)
        self.assertEqual(state.backlog_count, 1)

    def test_poll_initial_snapshot(self):
        aggregator = CrossRepoAggregator(watch_paths=[self.repo_a, self.repo_b])
        events = aggregator.poll()
        self.assertEqual(len(events), 2)
        for ev in events:
            self.assertEqual(ev.event_type, "workspace_snapshot")
            self.assertIn(ev.repo_name, ["repo_a", "repo_b"])

    def test_poll_detects_status_change(self):
        aggregator = CrossRepoAggregator(watch_paths=[self.repo_a])
        _ = aggregator.poll()  # initial snapshot

        # Mutate status of repo A from RUNNING to DONE
        task_md_path = os.path.join(self.repo_a, ".agent", "TASK.md")
        with open(task_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("Status:** RUNNING", "Status:** DONE")
        with open(task_md_path, "w", encoding="utf-8") as f:
            f.write(content)

        events = aggregator.poll()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.event_type, "task_status_changed")
        self.assertEqual(ev.old_status, "RUNNING")
        self.assertEqual(ev.new_status, "DONE")
        self.assertEqual(ev.task_id, "01.1")

    def test_poll_detects_task_switch(self):
        aggregator = CrossRepoAggregator(watch_paths=[self.repo_a])
        _ = aggregator.poll()

        # Switch active task to [01.2]
        task_md_path = os.path.join(self.repo_a, ".agent", "TASK.md")
        with open(task_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("Task [01.1]: First Alpha Feature", "Task [01.2]: Promoted Next Item")
        content = content.replace("Status:** RUNNING", "Status:** PLANNING")
        with open(task_md_path, "w", encoding="utf-8") as f:
            f.write(content)

        events = aggregator.poll()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.event_type, "task_switched")
        self.assertEqual(ev.task_id, "01.2")
        self.assertEqual(ev.new_status, "PLANNING")

    def test_poll_detects_criteria_progress(self):
        aggregator = CrossRepoAggregator(watch_paths=[self.repo_a])
        _ = aggregator.poll()

        task_md_path = os.path.join(self.repo_a, ".agent", "TASK.md")
        with open(task_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("- [ ] Item 2", "- [x] Item 2")
        with open(task_md_path, "w", encoding="utf-8") as f:
            f.write(content)

        events = aggregator.poll()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.event_type, "criteria_updated")
        self.assertEqual(ev.details.get("criteria_checked"), 2)

    def test_get_summary(self):
        aggregator = CrossRepoAggregator(watch_paths=[self.test_dir])
        summary = aggregator.get_summary()
        self.assertEqual(summary["total_workspaces"], 2)
        self.assertEqual(summary["status_counts"].get("RUNNING"), 1)
        self.assertEqual(summary["status_counts"].get("READY FOR PLANNING"), 1)
        self.assertEqual(len(summary["active_tasks"]), 2)


class TestTelemetryBroadcaster(unittest.TestCase):
    def setUp(self):
        self.mock_emitter = MagicMock()
        self.mock_webhook = MagicMock()
        self.mock_webhook.is_configured.return_value = True

    @patch("taskctl.telemetry.broadcaster.send_canvas_notification", return_value=True)
    def test_broadcast_event_all_sinks(self, mock_notify):
        broadcaster = TelemetryBroadcaster(
            emitter=self.mock_emitter,
            webhook_dispatcher=self.mock_webhook,
            broadcast_vector=True,
            broadcast_canvas=True,
            broadcast_webhook=True,
        )

        event = WorkspaceEvent(
            event_type="task_status_changed",
            repo_path="/tmp/repo",
            repo_name="repo",
            task_id="01.1",
            task_title="Test Task",
            old_status="PLANNING",
            new_status="RUNNING",
            message="Status changed to RUNNING",
        )

        results = broadcaster.broadcast_event(event)
        self.assertTrue(results["vector"])
        self.assertTrue(results["canvas"])
        self.assertTrue(results["webhook"])

        self.mock_emitter.emit.assert_called_once()
        mock_notify.assert_called_once()
        self.mock_webhook.send_event.assert_called_once()

    @patch("taskctl.telemetry.broadcaster.send_canvas_notification", side_effect=RuntimeError("canvas socket down"))
    def test_broadcast_fail_safe_on_sink_error(self, mock_notify):
        self.mock_emitter.emit.side_effect = Exception("network down")
        self.mock_webhook.send_event.side_effect = Exception("webhook 500")

        broadcaster = TelemetryBroadcaster(
            emitter=self.mock_emitter,
            webhook_dispatcher=self.mock_webhook,
        )
        event = WorkspaceEvent(
            event_type="test",
            repo_path="/tmp/repo",
            repo_name="repo",
            message="Test msg",
        )
        # Invariant 3: Never raise exceptions
        results = broadcaster.broadcast_event(event)
        self.assertFalse(results["vector"])
        self.assertFalse(results["canvas"])
        self.assertFalse(results["webhook"])

    @patch("taskctl.telemetry.broadcaster.send_canvas_notification", return_value=True)
    def test_broadcast_summary(self, mock_notify):
        broadcaster = TelemetryBroadcaster(
            emitter=self.mock_emitter,
            webhook_dispatcher=self.mock_webhook,
        )
        summary = {
            "total_workspaces": 3,
            "status_counts": {"RUNNING": 2, "DONE": 1},
        }
        results = broadcaster.broadcast_summary(summary)
        self.assertTrue(results["vector"])
        self.assertTrue(results["canvas"])
        self.assertTrue(results["webhook"])


class TestTelemetryDaemon(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="taskctl_daemon_unit_")
        self.repo = os.path.join(self.test_dir, "my_repo")
        agent_dir = os.path.join(self.repo, ".agent")
        os.makedirs(agent_dir, exist_ok=True)
        with open(os.path.join(agent_dir, "TASK.md"), "w", encoding="utf-8") as f:
            f.write(SAMPLE_TASK_A)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_format_summary_table(self):
        daemon = TelemetryDaemon(watch_paths=[self.repo])
        summary = daemon.aggregator.get_summary()
        table_str = daemon.format_summary_table(summary)
        self.assertIn("CROSS-REPO WORKSPACE STATUS SUMMARY", table_str)
        self.assertIn("my_repo", table_str)
        self.assertIn("01.1", table_str)

    @patch("taskctl.telemetry.broadcaster.send_canvas_notification", return_value=True)
    def test_run_once(self, mock_notify):
        daemon = TelemetryDaemon(
            watch_paths=[self.repo],
            output_format="json",
        )
        summary = daemon.run_once()
        self.assertEqual(summary["total_workspaces"], 1)

    def test_daemon_stop(self):
        daemon = TelemetryDaemon(watch_paths=[self.repo], interval=1.0)
        daemon.stop()
        self.assertFalse(daemon._running)


class TestCLIIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="taskctl_cli_daemon_")
        self.repo = os.path.join(self.test_dir, "cli_repo")
        agent_dir = os.path.join(self.repo, ".agent")
        os.makedirs(agent_dir, exist_ok=True)
        with open(os.path.join(agent_dir, "TASK.md"), "w", encoding="utf-8") as f:
            f.write(SAMPLE_TASK_A)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("taskctl.telemetry.broadcaster.send_canvas_notification", return_value=True)
    def test_cmd_daemon_once(self, mock_notify):
        code = cmd_daemon(watch_paths=[self.repo], once=True, json_output=True)
        self.assertEqual(code, 0)

    @patch("taskctl.telemetry.broadcaster.send_canvas_notification", return_value=True)
    def test_cmd_broadcast(self, mock_notify):
        code = cmd_broadcast(msg="Manual cross-repo ping", watch_paths=[self.repo], json_output=False)
        self.assertEqual(code, 0)

    @patch("taskctl.telemetry.broadcaster.send_canvas_notification", return_value=True)
    def test_cli_main_daemon_once(self, mock_notify):
        with patch("sys.argv", ["taskctl", "daemon", "--watch", self.repo, "--once", "--json"]):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)

    @patch("taskctl.telemetry.broadcaster.send_canvas_notification", return_value=True)
    def test_cli_main_broadcast(self, mock_notify):
        with patch("sys.argv", ["taskctl", "broadcast", "Test broadcast message", "--watch", self.repo, "--json"]):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
