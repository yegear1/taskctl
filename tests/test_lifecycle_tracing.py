"""Unit and integration tests for lifecycle trace genesis and context propagation."""

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from taskctl.telemetry.tracing import (
    TraceContext,
    get_tracer,
    load_active_trace,
    clear_active_trace,
    normalize_trace_id,
)
from taskctl.telemetry.sink import TelemetryEmitter
from taskctl.cli import cmd_next, cmd_done


def _setup_git_repo(repo_dir: str, task_content: str) -> None:
    os.makedirs(os.path.join(repo_dir, ".agent"), exist_ok=True)
    task_file = os.path.join(repo_dir, ".agent", "TASK.md")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write(task_content)

    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=repo_dir, capture_output=True, check=True)


SAMPLE_TASK_CONTENT = """# Tasks & Roadmap

### 📌 Task [01.1]: First Alpha Feature

- **Description:** Implement alpha feature
- **Systems Involved:** [core, cli]
- **Runtime Target:** Profile 'default' | Model: 'flash'
- **Status:** READY FOR PLANNING

### Acceptance Criteria
- [ ] Criterion 1

---

## Backlog

- [ ] **[01.2]** Second Feature
- [ ] **[01.3]** Third Feature

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
"""


class TestLifecycleTraceGenesisAndPropagation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="taskctl_trace_test_")
        self.repo = os.path.join(self.temp_dir, "repo")
        _setup_git_repo(self.repo, SAMPLE_TASK_CONTENT)
        get_tracer().clear()

    def tearDown(self):
        os.environ.pop("MAESTRI_TRACE_ID", None)
        os.environ.pop("TRACEPARENT", None)
        os.environ.pop("TASKCTL_TRACE_ID", None)
        shutil.rmtree(self.temp_dir)
        get_tracer().clear()

    @patch("taskctl.cli.sync_task_cockpit_note")
    @patch("taskctl.cli.sync_hud_note")
    def test_cmd_next_trace_genesis_and_cache(self, mock_hud, mock_cockpit):
        """Test cmd_next originates trace ID, writes cache, updates TASK.md, and exports env."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.stdout", new_callable=io.StringIO):
                cmd_next(repo=self.repo, handoff=False)

            # 1. Environment export
            maestri_trace_id = os.environ.get("MAESTRI_TRACE_ID")
            traceparent = os.environ.get("TRACEPARENT")
            self.assertIsNotNone(maestri_trace_id)
            self.assertEqual(len(maestri_trace_id), 32)
            self.assertIsNotNone(traceparent)
            self.assertIn(maestri_trace_id, traceparent)

            # 2. Active trace cache file exists and contains matching trace_id
            cached = load_active_trace(self.repo, expected_task_id="01.2")
            self.assertIsNotNone(cached)
            self.assertEqual(cached.trace_id, maestri_trace_id)

            # 3. TASK.md active task has Trace ID
            task_file = os.path.join(self.repo, ".agent", "TASK.md")
            with open(task_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn(f"- **Trace ID:** {maestri_trace_id}", content)

    @patch("taskctl.cli.sync_task_cockpit_note")
    @patch("taskctl.cli.sync_hud_note")
    @patch("taskctl.cli.handoff_task_start")
    @patch("taskctl.cli.handoff_task_done")
    def test_trace_continuity_between_next_and_done(self, mock_handoff_done, mock_handoff_start, mock_hud, mock_cockpit):
        """Test cmd_done resumes genesis trace ID, passes it to handoff, and cleans up cache."""
        mock_handoff_start.return_value = MagicMock(delivered=True, target_agent="Builder", response="OK")
        mock_handoff_done.return_value = MagicMock(delivered=True, target_agent="Auditor", response="Verified")

        emitted_events = []
        emitter = TelemetryEmitter(emit_ndjson_stdout=False)
        with patch("taskctl.cli.get_telemetry_emitter", return_value=emitter):
            with patch.object(emitter, "emit", side_effect=emitted_events.append):
                with patch.dict(os.environ, {}, clear=True):
                    with patch("sys.stdout", new_callable=io.StringIO):
                        cmd_next(repo=self.repo, handoff=True)

                    genesis_trace_id = os.environ.get("MAESTRI_TRACE_ID")
                    self.assertIsNotNone(genesis_trace_id)

                    # Simulate a completely fresh shell session by clearing environment trace vars
                    with patch.dict(os.environ, {}, clear=True):
                        # Make a code change to stage
                        test_code_path = os.path.join(self.repo, "feature.py")
                        with open(test_code_path, "w", encoding="utf-8") as f:
                            f.write("print('hello')\n")
                        subprocess.run(["git", "add", "feature.py"], cwd=self.repo, check=True)

                        with patch("sys.stdout", new_callable=io.StringIO):
                            cmd_done(custom_msg="feat(core): add feature", repo=self.repo, handoff=True)

                    # Hand-off in done received the genesis trace_id
                    mock_handoff_done.assert_called_once()
                    done_task_data = mock_handoff_done.call_args[0][0]
                    self.assertEqual(done_task_data.get("trace_id"), genesis_trace_id)

                    # Cache is cleared
                    self.assertIsNone(load_active_trace(self.repo, expected_task_id="01.2"))

                    # TASK.md no longer has Trace ID line under Active Task
                    task_file = os.path.join(self.repo, ".agent", "TASK.md")
                    with open(task_file, "r", encoding="utf-8") as f:
                        task_content = f.read()
                    self.assertNotIn("- **Trace ID:**", task_content)

                    # Check emitted events share genesis trace ID
                    lifecycle_events = [e for e in emitted_events if hasattr(e, "event_type")]
                    task_events = [e for e in lifecycle_events if e.event_type in ("task_started", "task_completed")]
                    self.assertGreaterEqual(len(task_events), 2)
                    for tev in task_events:
                        self.assertEqual(tev.trace_id, genesis_trace_id)

    @patch("taskctl.cli.sync_task_cockpit_note")
    @patch("taskctl.cli.sync_hud_note")
    def test_injected_maestri_trace_id_uuid_normalization(self, mock_hud, mock_cockpit):
        """Test injected MAESTRI_TRACE_ID (UUID) is normalized and propagated end-to-end."""
        maestri_uuid = "346ab552-34a8-4840-bdf8-5334c5055804"
        expected_hex = "346ab55234a84840bdf85334c5055804"

        with patch.dict(os.environ, {"MAESTRI_TRACE_ID": maestri_uuid}, clear=True):
            with patch("sys.stdout", new_callable=io.StringIO):
                cmd_next(repo=self.repo, handoff=False)

            self.assertEqual(os.environ.get("MAESTRI_TRACE_ID"), expected_hex)
            cached = load_active_trace(self.repo, expected_task_id="01.2")
            self.assertIsNotNone(cached)
            self.assertEqual(cached.trace_id, expected_hex)


if __name__ == "__main__":
    unittest.main()
