"""Tests for autonomous agent lifecycle hand-offs on task start and completion."""

import io
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from taskctl.providers.maestri import (
    AgentHandoffResult,
    dispatch_agent_handoff,
    handoff_task_start,
    handoff_task_done,
)
from taskctl.cli import cmd_next, cmd_done


class TestDispatchAgentHandoff(unittest.TestCase):
    @patch("taskctl.providers.maestri.send_canvas_notification")
    @patch("taskctl.providers.maestri.ask_agent")
    def test_handoff_start_success(self, mock_ask, mock_notify):
        mock_ask.return_value = "Acknowledged. Beginning implementation of [04.1]."
        task_data = {
            "task_id": "04.1",
            "title": "New feature implementation",
            "status": "RUNNING",
            "description": "Implement core feature",
            "systems": "[taskctl/core]",
            "criteria": [{"text": "Pass tests", "checked": False}],
            "runtime_target": "Profile 'yegear' | Model: 'gemini-3.8-flash-medium'",
        }

        res = handoff_task_start(task_data)

        self.assertIsInstance(res, AgentHandoffResult)
        self.assertEqual(res.phase, "start")
        self.assertEqual(res.task_id, "04.1")
        self.assertEqual(res.target_agent, "Builder")
        self.assertTrue(res.delivered)
        self.assertEqual(res.response, "Acknowledged. Beginning implementation of [04.1].")
        self.assertIsNone(res.error)
        mock_notify.assert_called_once()
        self.assertIn("04.1", mock_notify.call_args[0][0])

    @patch("taskctl.providers.maestri.send_canvas_notification")
    @patch("taskctl.providers.maestri.ask_agent")
    def test_handoff_completion_success(self, mock_ask, mock_notify):
        mock_ask.return_value = "Audit verification complete. All DoD checks passed."
        task_data = {
            "task_id": "04.1",
            "title": "New feature implementation",
            "status": "DONE",
            "commit_hash": "a1b2c3d",
            "governance_commit": "e4f5a6b",
        }

        res = handoff_task_done(task_data)

        self.assertIsInstance(res, AgentHandoffResult)
        self.assertEqual(res.phase, "completion")
        self.assertEqual(res.task_id, "04.1")
        self.assertEqual(res.target_agent, "Auditor")
        self.assertTrue(res.delivered)
        self.assertEqual(res.response, "Audit verification complete. All DoD checks passed.")
        self.assertIsNone(res.error)
        mock_notify.assert_called_once()
        self.assertIn("a1b2c3d", mock_notify.call_args[0][0])

    @patch("taskctl.providers.maestri.send_canvas_notification")
    @patch("taskctl.providers.maestri.ask_agent")
    def test_handoff_explicit_target_agent(self, mock_ask, mock_notify):
        mock_ask.return_value = "Task received by custom agent."
        task_data = {"task_id": "04.2", "title": "Specialized job"}

        res = dispatch_agent_handoff("start", task_data, target_agent="SwarmWorker-4")

        self.assertTrue(res.delivered)
        self.assertEqual(res.target_agent, "SwarmWorker-4")
        mock_ask.assert_called_once()
        self.assertEqual(mock_ask.call_args[0][0], "SwarmWorker-4")

    @patch("taskctl.providers.maestri.send_canvas_notification")
    @patch("taskctl.providers.maestri.ask_agent")
    def test_handoff_candidate_fallback(self, mock_ask, mock_notify):
        mock_ask.side_effect = [None, "Implementer standing by."]
        task_data = {"task_id": "04.3", "title": "Fallback test"}

        res = handoff_task_start(task_data)

        self.assertTrue(res.delivered)
        self.assertEqual(res.target_agent, "Implementer")
        self.assertEqual(mock_ask.call_count, 2)

    @patch("taskctl.providers.maestri.send_canvas_notification")
    @patch("taskctl.providers.maestri.ask_agent", return_value=None)
    def test_handoff_degraded_offline(self, mock_ask, mock_notify):
        task_data = {"task_id": "04.4", "title": "Offline test"}

        res = handoff_task_start(task_data)

        self.assertFalse(res.delivered)
        self.assertIsNone(res.target_agent)
        self.assertIsNone(res.response)
        self.assertIsNotNone(res.error)
        self.assertIn("No responsive canvas agent found", res.error)


class TestCLILifecycleHandoff(unittest.TestCase):
    @patch("taskctl.cli.handoff_task_start")
    @patch("taskctl.cli.sync_task_cockpit_note")
    @patch("taskctl.cli.get_task_file")
    def test_cmd_next_triggers_handoff(self, mock_get_file, mock_sync, mock_handoff):
        mock_handoff.return_value = AgentHandoffResult(
            phase="start",
            task_id="03.5",
            target_agent="Builder",
            delivered=True,
            response="Ready.",
        )
        task_content = """# Tasks

### 📌 Task [03.4]: Current Task
- **Status:** RUNNING

### Acceptance Criteria
- [ ] Done

---

## Backlog

- [ ] **[03.5]** Next queued task

---

## Completed Tasks Log
"""
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(task_content)
            temp_path = f.name

        try:
            mock_get_file.return_value = temp_path
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                cmd_next(target_agent="Builder")
                out = mock_out.getvalue()
                self.assertIn("Promoted [03.5] 'Next queued task'", out)
                self.assertIn("[Hand-off] Successfully dispatched context to canvas agent 'Builder'", out)
                mock_handoff.assert_called_once()
                call_args = mock_handoff.call_args[0]
                task_data = call_args[0]
                self.assertEqual(task_data["task_id"], "03.5")
                self.assertEqual(task_data["title"], "Next queued task")
                self.assertEqual(mock_handoff.call_args[1].get("target_agent"), "Builder")
        finally:
            os.remove(temp_path)

    @patch("taskctl.cli.handoff_task_start")
    @patch("taskctl.cli.sync_task_cockpit_note")
    @patch("taskctl.cli.get_task_file")
    def test_cmd_next_skip_handoff(self, mock_get_file, mock_sync, mock_handoff):
        task_content = """# Tasks

### 📌 Task [03.4]: Current Task
- **Status:** RUNNING

### Acceptance Criteria
- [ ] Done

---

## Backlog

- [ ] **[03.5]** Next queued task

---

## Completed Tasks Log
"""
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(task_content)
            temp_path = f.name

        try:
            mock_get_file.return_value = temp_path
            with patch("sys.stdout", new_callable=io.StringIO):
                cmd_next(handoff=False)
                mock_handoff.assert_not_called()
        finally:
            os.remove(temp_path)

    @patch("taskctl.cli.handoff_task_done")
    @patch("taskctl.cli.sync_task_cockpit_note")
    @patch("taskctl.cli.run_cmd")
    @patch("taskctl.cli.get_task_file")
    def test_cmd_done_triggers_handoff(self, mock_get_file, mock_run_cmd, mock_sync, mock_handoff):
        mock_handoff.return_value = AgentHandoffResult(
            phase="completion",
            task_id="03.4",
            target_agent="Auditor",
            delivered=True,
            response="Verified.",
        )
        task_content = """# Tasks

### 📌 Task [03.4]: Finished task
- **Status:** RUNNING

### Acceptance Criteria
- [x] Done

---

## Backlog

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
"""
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(task_content)
            temp_path = f.name

        try:
            mock_get_file.return_value = temp_path
            mock_run_cmd.side_effect = [
                MagicMock(stdout=""),  # git diff --cached (no staged feature)
                MagicMock(stdout="abc1234\n"),  # git rev-parse HEAD (commit_hash)
                MagicMock(returncode=0),  # git add TASK.md
                MagicMock(returncode=0),  # git commit gov
                MagicMock(stdout="def5678\n"),  # git rev-parse HEAD (gov_hash)
            ]

            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                cmd_done(custom_msg=None, promote=False, target_agent="Auditor")
                out = mock_out.getvalue()
                self.assertIn("[COMMIT 2/2] Governance commit created: def5678", out)
                self.assertIn("[Hand-off] Completion context dispatched to canvas agent 'Auditor'", out)
                mock_handoff.assert_called_once()
                task_data = mock_handoff.call_args[0][0]
                self.assertEqual(task_data["task_id"], "03.4")
                self.assertEqual(task_data["status"], "DONE")
                self.assertEqual(task_data["commit_hash"], "abc1234")
                self.assertEqual(task_data["governance_commit"], "def5678")
        finally:
            os.remove(temp_path)

    @patch("taskctl.cli.handoff_task_done")
    @patch("taskctl.cli.sync_task_cockpit_note")
    @patch("taskctl.cli.run_cmd")
    @patch("taskctl.cli.get_task_file")
    def test_cmd_done_skip_handoff(self, mock_get_file, mock_run_cmd, mock_sync, mock_handoff):
        task_content = """# Tasks

### 📌 Task [03.4]: Finished task
- **Status:** RUNNING

### Acceptance Criteria
- [x] Done

---

## Backlog

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
"""
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(task_content)
            temp_path = f.name

        try:
            mock_get_file.return_value = temp_path
            mock_run_cmd.side_effect = [
                MagicMock(stdout=""),  # git diff --cached
                MagicMock(stdout="abc1234\n"),  # git rev-parse HEAD
                MagicMock(returncode=0),  # git add
                MagicMock(returncode=0),  # git commit
                MagicMock(stdout="def5678\n"),  # git rev-parse HEAD
            ]

            with patch("sys.stdout", new_callable=io.StringIO):
                cmd_done(handoff=False)
                mock_handoff.assert_not_called()
        finally:
            os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
