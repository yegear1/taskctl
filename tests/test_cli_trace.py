"""Unit tests for taskctl trace CLI command."""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from taskctl.cli import cmd_trace, main
from taskctl.telemetry.tracing import TraceContext, get_tracer, save_active_trace
from taskctl.telemetry.victorialogs import TaskCycleSummary, VictoriaLogsClient


class TestCliTraceCommand(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="taskctl_trace_test_")
        self.agent_dir = os.path.join(self.temp_dir, ".agent")
        os.makedirs(self.agent_dir, exist_ok=True)
        self.task_file = os.path.join(self.agent_dir, "TASK.md")
        with open(self.task_file, "w", encoding="utf-8") as f:
            f.write(
                "# TASK.md\n\n"
                "## Active Task\n\n"
                "### 📌 Task [02.8]: Context Propagation\n\n"
                "- **Status:** RUNNING\n"
                "- **Trace ID:** 11112222333344445555666677778888\n\n"
                "### Acceptance Criteria\n- [ ] criterion 1\n"
            )

        tracer = get_tracer()
        tracer.clear()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cli_trace_positional_raw_id(self):
        with patch.object(sys, "argv", ["taskctl", "trace", "02.8", "--repo", self.temp_dir]):
            with patch("taskctl.cli.cmd_trace", wraps=cmd_trace) as spy:
                with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                    with self.assertRaises(SystemExit) as cm:
                        main()
                    self.assertEqual(cm.exception.code, 0)
                    out = mock_out.getvalue()
                    self.assertIn("TASK CYCLE LIFECYCLE TRACE: [02.8]", out)

    def test_cli_trace_positional_bracketed_id(self):
        with patch.object(sys, "argv", ["taskctl", "trace", "[02.8]", "--repo", self.temp_dir]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
                out = mock_out.getvalue()
                self.assertIn("TASK CYCLE LIFECYCLE TRACE: [02.8]", out)

    def test_cli_trace_task_flag_json(self):
        with patch.object(sys, "argv", ["taskctl", "trace", "--task", "02.8", "--json", "--repo", self.temp_dir]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
                data = json.loads(mock_out.getvalue())
                self.assertEqual(data["task_id"], "02.8")
                self.assertIn("timeline", data)
                self.assertIn("blocked_commands", data)
                self.assertIn("tokens", data)

    def test_cli_trace_id_flag(self):
        trace_hex = "4e962325383081638ff876c2fa566890"
        with patch.object(sys, "argv", ["taskctl", "trace", "--id", trace_hex, "--repo", self.temp_dir]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
                out = mock_out.getvalue()
                self.assertIn(trace_hex, out)

    def test_cli_trace_active_task_default(self):
        # When no task or trace ID is specified, it should resolve from TASK.md in repo
        with patch.object(sys, "argv", ["taskctl", "trace", "--repo", self.temp_dir]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
                out = mock_out.getvalue()
                self.assertIn("TASK CYCLE LIFECYCLE TRACE: [02.8]", out)

    def test_cli_trace_cached_active_trace_resolution(self):
        # When active trace is cached in .agent/.cache/active_trace.json
        ctx = TraceContext(trace_id="aabbccddeeff00112233445566778899", span_id="1122334455667788")
        save_active_trace(self.temp_dir, "02.8", ctx)

        with patch.object(sys, "argv", ["taskctl", "trace", "--json", "--repo", self.temp_dir]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
                data = json.loads(mock_out.getvalue())
                self.assertEqual(data["trace_id"], "aabbccddeeff00112233445566778899")

    def test_cli_trace_analytics_flag(self):
        tracer = get_tracer()
        with tracer.start_span("cli.next", tags={"task_id": "02.8"}):
            pass
        with tracer.start_span("cli.audit", tags={"task_id": "02.8"}):
            pass

        with patch.object(sys, "argv", ["taskctl", "trace", "02.8", "--analytics", "--repo", self.temp_dir]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
                out = mock_out.getvalue()
                self.assertIn("Total Spans", out)
                self.assertIn("Total Duration", out)

    def test_cli_trace_help(self):
        with patch.object(sys, "argv", ["taskctl", "trace", "--help"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
                out = mock_out.getvalue()
                self.assertIn("Usage: taskctl trace", out)


if __name__ == "__main__":
    unittest.main()
