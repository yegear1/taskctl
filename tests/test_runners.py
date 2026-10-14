"""Tests for the pluggable runner layer and built-in runner adapters."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from taskctl.runners.base import RunnerResult, TaskRunner
from taskctl.runners.codex import CodexRunner
from taskctl.runners.custom import CustomRunner
from taskctl.runners.maestri import MaestriRunner
from taskctl.runners.multigravity import MultigravityRunner
from taskctl.runners.registry import get_runner, list_runners, register_runner
from taskctl.cli import cmd_next, main


class TestRunnerBaseAndRegistry(unittest.TestCase):
    def test_runner_result_to_dict(self):
        res = RunnerResult(
            runner="test",
            task_id="01.1",
            status="delivered",
            delivered=True,
            target="AgentX",
            output="Done",
            error=None,
            details={"foo": "bar"},
        )
        d = res.to_dict()
        self.assertEqual(d["runner"], "test")
        self.assertEqual(d["task_id"], "01.1")
        self.assertEqual(d["status"], "delivered")
        self.assertTrue(d["delivered"])
        self.assertEqual(d["target"], "AgentX")
        self.assertEqual(d["output"], "Done")
        self.assertEqual(d["details"], {"foo": "bar"})

    def test_list_runners(self):
        runners = list_runners()
        self.assertIn("maestri", runners)
        self.assertIn("multigravity", runners)
        self.assertIn("codex", runners)
        self.assertIn("custom", runners)

    def test_get_runner_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TASKCTL_DEFAULT_RUNNER", None)
            runner = get_runner()
            self.assertIsInstance(runner, MaestriRunner)

    def test_get_runner_env_override(self):
        with patch.dict(os.environ, {"TASKCTL_DEFAULT_RUNNER": "codex"}):
            runner = get_runner()
            self.assertIsInstance(runner, CodexRunner)

    def test_get_runner_explicit_arg(self):
        runner = get_runner("multigravity")
        self.assertIsInstance(runner, MultigravityRunner)

    def test_get_runner_unknown_raises(self):
        with self.assertRaises(ValueError) as ctx:
            get_runner("unsupported_runner_xyz")
        self.assertIn("Unknown runner 'unsupported_runner_xyz'", str(ctx.exception))
        self.assertIn("Available runners:", str(ctx.exception))

    def test_register_custom_runner(self):
        class DummyRunner(TaskRunner):
            name = "dummy"

            def run(self, task_data, **kwargs):
                return RunnerResult(
                    runner=self.name,
                    task_id=task_data.get("task_id", ""),
                    status="executed",
                    delivered=True,
                )

        register_runner("dummy", DummyRunner)
        self.assertIn("dummy", list_runners())
        runner = get_runner("dummy")
        self.assertIsInstance(runner, DummyRunner)
        res = runner.run({"task_id": "99.1"})
        self.assertEqual(res.status, "executed")
        self.assertTrue(res.delivered)


class TestMaestriRunner(unittest.TestCase):
    @patch("taskctl.runners.maestri.handoff_task_start")
    def test_maestri_runner_delivered(self, mock_handoff):
        mock_handoff.return_value = MagicMock(
            phase="start",
            delivered=True,
            target_agent="Builder",
            response="Ready.",
            error=None,
        )
        runner = MaestriRunner()
        task_data = {"task_id": "02.4", "title": "Runner abstraction"}
        res = runner.run(task_data, target_agent="Builder")

        self.assertEqual(res.runner, "maestri")
        self.assertEqual(res.status, "delivered")
        self.assertTrue(res.delivered)
        self.assertEqual(res.target, "Builder")
        self.assertEqual(res.output, "Ready.")
        self.assertIsNone(res.error)

    @patch("taskctl.runners.maestri.handoff_task_start")
    def test_maestri_runner_degraded(self, mock_handoff):
        mock_handoff.return_value = MagicMock(
            phase="start",
            delivered=False,
            target_agent=None,
            response=None,
            error="Agents offline",
        )
        runner = MaestriRunner()
        task_data = {"task_id": "02.4", "title": "Runner abstraction"}
        res = runner.run(task_data)

        self.assertEqual(res.status, "degraded")
        self.assertFalse(res.delivered)
        self.assertEqual(res.error, "Agents offline")

    @patch("taskctl.runners.maestri.handoff_task_start", side_effect=RuntimeError("Socket error"))
    def test_maestri_runner_exception_handling(self, mock_handoff):
        runner = MaestriRunner()
        res = runner.run({"task_id": "02.4"})
        self.assertEqual(res.status, "degraded")
        self.assertFalse(res.delivered)
        self.assertIn("Socket error", str(res.error))


class TestMultigravityRunner(unittest.TestCase):
    @patch("shutil.which", return_value="/usr/local/bin/multigravity")
    @patch("subprocess.run")
    def test_multigravity_runner_binary_success(self, mock_run, mock_which):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["multigravity", "run"],
            returncode=0,
            stdout="Allocated profile yegear on worktree /tmp/wt",
            stderr="",
        )
        runner = MultigravityRunner()
        task_data = {
            "task_id": "02.4",
            "title": "Multigravity task",
            "target_profile": "yegear",
            "target_model": "flash",
        }
        res = runner.run(task_data)

        self.assertEqual(res.runner, "multigravity")
        self.assertEqual(res.status, "executed")
        self.assertTrue(res.delivered)
        self.assertIn("yegear", str(res.target))
        self.assertIn("Allocated profile", str(res.output))
        mock_run.assert_called_once()

    @patch("shutil.which", return_value=None)
    def test_multigravity_runner_missing_cli(self, mock_which):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TASKCTL_MULTIGRAVITY_CMD", None)
            runner = MultigravityRunner()
            task_data = {
                "task_id": "02.4",
                "target_profile": "luisfmb",
                "target_model": "gemini-3.8-flash-medium",
            }
            res = runner.run(task_data)

            self.assertEqual(res.status, "degraded")
            self.assertFalse(res.delivered)
            self.assertIn("multigravity CLI binary not found", str(res.error))

    @patch.dict(os.environ, {"TASKCTL_MULTIGRAVITY_CMD": "echo task={task_id} profile={profile}"})
    def test_multigravity_runner_template_cmd(self):
        runner = MultigravityRunner()
        task_data = {
            "task_id": "02.4",
            "target_profile": "joaoww",
            "target_model": "flash",
        }
        res = runner.run(task_data)
        self.assertEqual(res.status, "executed")
        self.assertTrue(res.delivered)
        self.assertIn("task=02.4 profile=joaoww", str(res.output))

    @patch("shutil.which", return_value="/usr/local/bin/multigravity")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="multigravity", timeout=1.0))
    def test_multigravity_runner_timeout(self, mock_run, mock_which):
        runner = MultigravityRunner()
        task_data = {"task_id": "02.4", "target_profile": "yegear", "target_model": "flash"}
        res = runner.run(task_data, timeout=1.0)
        self.assertEqual(res.status, "degraded")
        self.assertFalse(res.delivered)
        self.assertIn("timed out", str(res.error))


class TestCodexRunner(unittest.TestCase):
    @patch("shutil.which", return_value="/usr/bin/codex")
    @patch("subprocess.run")
    def test_codex_runner_binary_success(self, mock_run, mock_which):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["codex", "run"],
            returncode=0,
            stdout="Codex task initiated",
            stderr="",
        )
        runner = CodexRunner()
        task_data = {"task_id": "02.4", "title": "Codex integration"}
        res = runner.run(task_data)
        self.assertEqual(res.runner, "codex")
        self.assertEqual(res.status, "executed")
        self.assertTrue(res.delivered)
        self.assertIn("Codex task initiated", str(res.output))

    @patch("shutil.which", return_value=None)
    def test_codex_runner_missing_binary(self, mock_which):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TASKCTL_CODEX_CMD", None)
            runner = CodexRunner()
            res = runner.run({"task_id": "02.4"})
            self.assertEqual(res.status, "degraded")
            self.assertFalse(res.delivered)
            self.assertIn("Codex runner binary or TASKCTL_CODEX_CMD not found", str(res.error))

    @patch.dict(os.environ, {"TASKCTL_CODEX_CMD": "echo codex={task_id}"})
    def test_codex_runner_custom_cmd(self):
        runner = CodexRunner()
        res = runner.run({"task_id": "02.4"})
        self.assertEqual(res.status, "executed")
        self.assertTrue(res.delivered)
        self.assertIn("codex=02.4", str(res.output))


class TestCustomRunner(unittest.TestCase):
    def test_custom_runner_no_command_configured(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TASKCTL_RUNNER_COMMAND", None)
            runner = CustomRunner()
            res = runner.run({"task_id": "02.4"})
            self.assertEqual(res.status, "failed")
            self.assertFalse(res.delivered)
            self.assertIn("No custom runner command specified", str(res.error))

    def test_custom_runner_template_substitution(self):
        runner = CustomRunner()
        task_data = {
            "task_id": "02.4",
            "title": "Pluggable runner",
            "status": "RUNNING",
            "target_profile": "luisfmb",
            "target_model": "gemini-3.8-flash-medium",
            "repo": "taskctl",
            "repo_path": "/tmp",
        }
        cmd = "echo ID={task_id} TITLE={title} PROFILE={profile}"
        res = runner.run(task_data, command=cmd)
        self.assertEqual(res.status, "executed")
        self.assertTrue(res.delivered)
        self.assertIn("ID=02.4 TITLE=Pluggable runner PROFILE=luisfmb", str(res.output))

    def test_custom_runner_command_failure(self):
        runner = CustomRunner()
        cmd = "sh -c 'echo error occurred >&2; exit 42'"
        res = runner.run({"task_id": "02.4"}, command=cmd)
        self.assertEqual(res.status, "failed")
        self.assertFalse(res.delivered)
        self.assertIn("error occurred", str(res.error))

    def test_custom_runner_timeout(self):
        runner = CustomRunner()
        cmd = "sleep 2"
        res = runner.run({"task_id": "02.4"}, command=cmd, timeout=0.1)
        self.assertEqual(res.status, "degraded")
        self.assertFalse(res.delivered)
        self.assertIn("timed out", str(res.error))


class TestCLIRunnerIntegration(unittest.TestCase):
    def setUp(self):
        self.test_content = """# Tasks

### 📌 Task [01.1]: Alpha Feature
- **Status:** RUNNING

### Acceptance Criteria
- [ ] Done

---

## Backlog

- [ ] **[01.2]** Pluggable runner execution

---

## Completed Tasks Log
"""
        self.temp_file = tempfile.NamedTemporaryFile("w+", delete=False)
        self.temp_file.write(self.test_content)
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    @patch("taskctl.cli.get_task_file")
    @patch("taskctl.cli.sync_task_cockpit_note")
    def test_cmd_next_with_custom_runner(self, mock_sync, mock_get_file):
        mock_get_file.return_value = self.temp_file.name
        with patch.dict(os.environ, {"TASKCTL_RUNNER_COMMAND": "echo Running task {task_id}"}):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                cmd_next(runner="custom")
                out = mock_out.getvalue()
                self.assertIn("Promoted [01.2] 'Pluggable runner execution'", out)
                self.assertIn("[Runner:custom] Status: EXECUTED", out)
                self.assertIn("Running task 01.2", out)

    @patch("taskctl.cli.get_task_file")
    @patch("taskctl.cli.sync_task_cockpit_note")
    def test_cmd_next_with_unknown_runner_exits(self, mock_sync, mock_get_file):
        mock_get_file.return_value = self.temp_file.name
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            with self.assertRaises(SystemExit) as cm:
                cmd_next(runner="non_existent_runner_123")
            self.assertEqual(cm.exception.code, 1)
            out = mock_out.getvalue()
            self.assertIn("Unknown runner 'non_existent_runner_123'", out)

    @patch("taskctl.cli.cmd_next")
    def test_cli_main_next_runner_flag(self, mock_next):
        with patch.object(sys, "argv", ["taskctl", "next", "--runner", "codex"]):
            main()
            mock_next.assert_called_once_with(
                weight="medium",
                target_agent=None,
                handoff=True,
                repo=None,
                runner="codex",
            )

    @patch("taskctl.cli.cmd_done")
    def test_cli_main_done_runner_flag(self, mock_done):
        with patch.object(sys, "argv", ["taskctl", "done", "feat: test", "-p", "--runner", "multigravity"]):
            main()
            mock_done.assert_called_once_with(
                custom_msg="feat: test",
                promote=True,
                weight="medium",
                target_agent=None,
                handoff=True,
                repo=None,
                runner="multigravity",
            )


if __name__ == "__main__":
    unittest.main()
