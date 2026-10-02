"""Hermetic unit tests for taskctl interactive terminal dashboard (TUI)."""

import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from taskctl.tui.state import (
    DoDCheckItem,
    DashboardState,
    collect_dashboard_state,
    _check_python_syntax,
    _check_git_workspace,
    _run_automated_tests,
)
from taskctl.tui.renderer import (
    render_dashboard,
    _visible_len,
    _truncate_pad,
    _status_badge,
    _dod_badge,
    Ansi,
)
from taskctl.tui.dashboard import Dashboard
from taskctl.cli import cmd_dashboard


class TestTuiState(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        self.agent_dir = self.repo_path / ".agent"
        self.agent_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_dod_check_item_is_pass(self):
        item_pass = DoDCheckItem(name="Test", status="PASS", message="OK")
        self.assertTrue(item_pass.is_pass)
        item_fail = DoDCheckItem(name="Test", status="FAIL", message="Failed")
        self.assertFalse(item_fail.is_pass)

    def test_check_python_syntax_clean(self):
        py_file = self.repo_path / "valid.py"
        py_file.write_text("x = 42\n", encoding="utf-8")
        ok, msg, count = _check_python_syntax(self.test_dir)
        self.assertTrue(ok)
        self.assertEqual(count, 1)
        self.assertIn("compiled cleanly", msg)

    def test_check_python_syntax_error(self):
        py_file = self.repo_path / "invalid.py"
        py_file.write_text("def broken(:\n", encoding="utf-8")
        ok, msg, count = _check_python_syntax(self.test_dir)
        self.assertFalse(ok)
        self.assertIn("syntax error", msg)

    def test_check_git_workspace_mocked(self):
        with patch("subprocess.run") as mock_run:
            # Mock git status --porcelain and git diff --check
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=" M file1.py\n?? file2.py\n"),
                MagicMock(returncode=0, stdout=""),
            ]
            is_clean, staged, unstaged, untracked, preview, diff_clean, _ = _check_git_workspace(self.test_dir)
            self.assertFalse(is_clean)
            self.assertEqual(staged, 0)
            self.assertEqual(unstaged, 1)
            self.assertEqual(untracked, 1)
            self.assertTrue(diff_clean)
            self.assertEqual(len(preview), 2)

    def test_run_automated_tests_mocked(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="Ran 10 tests\n\nOK")
            passed, msg, dur = _run_automated_tests(self.test_dir)
            self.assertTrue(passed)
            self.assertIn("OK", msg)
            self.assertGreaterEqual(dur, 0.0)

    def test_collect_dashboard_state(self):
        task_md = self.agent_dir / "TASK.md"
        task_md.write_text("""# Tasks
### 📌 Task [01.1]: Test task
- **Description:** Sample description
- **Systems Involved:** [taskctl/]
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash-medium'
- **Status:** RUNNING

### Acceptance Criteria
- [x] First criterion
- [ ] Second criterion

---
""", encoding="utf-8")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="feature-branch\n"),
                MagicMock(returncode=0, stdout="a1b2c3d\n"),
                MagicMock(returncode=0, stdout=""),
                MagicMock(returncode=0, stdout=""),
                MagicMock(returncode=0, stdout="+mock diff line\n"),
            ]
            with patch("taskctl.tui.state.get_task_file", return_value=str(task_md)):
                state = collect_dashboard_state(repo_root=self.test_dir, run_tests=False, run_audit=False)
                self.assertEqual(state.branch, "feature-branch")
                self.assertEqual(state.head_commit, "a1b2c3d")
                self.assertEqual(state.active_task.get("id"), "01.1")
                self.assertEqual(state.active_task.get("status"), "RUNNING")
                self.assertEqual(len(state.acceptance_criteria), 2)
                self.assertTrue(state.acceptance_criteria[0]["checked"])
                self.assertFalse(state.acceptance_criteria[1]["checked"])
                self.assertEqual(state.git_diff_lines, ["+mock diff line"])
                self.assertEqual(state.git_diff_raw, "+mock diff line\n")

    def test_get_git_diff_mocked(self):
        from taskctl.tui.state import _get_git_diff
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="diff --git a/f.py b/f.py\n+x = 1\n")
            lines, raw = _get_git_diff(self.test_dir)
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0], "diff --git a/f.py b/f.py")
            self.assertIn("+x = 1", raw)


class TestTuiRenderer(unittest.TestCase):
    def test_visible_len_and_truncate(self):
        colored_text = f"{Ansi.BOLD}{Ansi.CYAN}Hello World{Ansi.RESET}"
        self.assertEqual(_visible_len(colored_text), 11)
        padded = _truncate_pad("Test", 10)
        self.assertEqual(len(padded), 10)

    def test_status_badges(self):
        b_color = _status_badge("RUNNING", use_color=True)
        self.assertIn("RUNNING", b_color)
        b_plain = _status_badge("RUNNING", use_color=False)
        self.assertEqual(b_plain, "[RUNNING]")

    def test_dod_badges(self):
        b_pass = _dod_badge("PASS", use_color=False)
        self.assertEqual(b_pass, "[PASS]")
        b_fail = _dod_badge("FAIL", use_color=False)
        self.assertEqual(b_fail, "[FAIL]")
        b_pend = _dod_badge("PENDING", use_color=False)
        self.assertEqual(b_pend, "[PEND]")

    def test_render_dashboard_plain(self):
        state = DashboardState(
            repo_root="/path/to/repo",
            branch="main",
            head_commit="abcdef1",
            active_task={
                "id": "03.5",
                "title": "Interactive terminal dashboard",
                "status": "RUNNING",
                "target": "Profile 'yegear' | Model: 'gemini-3.8-flash-medium'",
                "systems": "[taskctl/tui/]",
            },
            acceptance_criteria=[
                {"checked": True, "text": "Criterion 1"},
                {"checked": False, "text": "Criterion 2"},
            ],
            dod_items=[
                DoDCheckItem(name="Syntax & Typing Check", status="PASS", message="Clean"),
                DoDCheckItem(name="Git Cleanliness", status="PASS", message="Clean"),
                DoDCheckItem(name="Scope Auditor", status="PASS", message="[APPROVED]"),
                DoDCheckItem(name="Automated Tests", status="PENDING", message="Press 't' to run"),
            ],
            audit_verdict=None,
            git_clean=True,
            staged_count=0,
            unstaged_count=0,
            untracked_count=0,
            git_status_preview=[],
        )

        output = render_dashboard(state, width=80, use_color=False)
        self.assertIn("TASKCTL COCKPIT", output)
        self.assertIn("[03.5] Interactive terminal dashboard", output)
        self.assertIn("[RUNNING]", output)
        self.assertIn("Criterion 1", output)
        self.assertIn("Criterion 2", output)
        self.assertIn("Syntax & Typing Check", output)
        self.assertIn("Automated Tests", output)
        self.assertIn("[r] Refresh", output)

    def test_render_dashboard_with_modified_files(self):
        state = DashboardState(
            repo_root="/path/to/repo",
            branch="dev",
            head_commit="1234567",
            active_task={},
            acceptance_criteria=[],
            dod_items=[],
            audit_verdict=None,
            git_clean=False,
            staged_count=1,
            unstaged_count=2,
            untracked_count=1,
            git_status_preview=["M  file1.py", " M file2.py", "?? file3.py"],
        )
        output = render_dashboard(state, width=80, use_color=False)
        self.assertIn("WORKSPACE HYGIENE", output)
        self.assertIn("file1.py", output)
        self.assertIn("file2.py", output)

    def test_render_split_dashboard_clean(self):
        state = DashboardState(
            repo_root="/path/to/repo",
            branch="main",
            head_commit="abcdef1",
            active_task={"id": "03.7", "title": "Diff Viewer", "status": "RUNNING"},
            acceptance_criteria=[{"checked": True, "text": "Criterion A"}],
            dod_items=[DoDCheckItem(name="Syntax Check", status="PASS", message="Clean")],
            audit_verdict=None,
            git_clean=True,
            staged_count=0,
            unstaged_count=0,
            untracked_count=0,
            git_status_preview=[],
            git_diff_lines=[],
        )
        output = render_dashboard(state, width=90, use_color=False, split_pane=True)
        self.assertIn("TASKCTL COCKPIT", output)
        self.assertIn("ACTIVE TASK CONTRACT", output)
        self.assertIn("GIT DIFF PREVIEW [Clean]", output)
        self.assertIn("Working tree clean", output)

    def test_render_split_dashboard_with_diff(self):
        state = DashboardState(
            repo_root="/path/to/repo",
            branch="feature",
            head_commit="1122334",
            active_task={"id": "03.7", "title": "Diff Viewer", "status": "RUNNING"},
            acceptance_criteria=[],
            dod_items=[],
            audit_verdict=None,
            git_clean=False,
            staged_count=1,
            unstaged_count=0,
            untracked_count=0,
            git_status_preview=["M  main.py"],
            git_diff_lines=[
                "diff --git a/main.py b/main.py",
                "index 111..222 100644",
                "--- a/main.py",
                "+++ b/main.py",
                "@@ -1,3 +1,4 @@",
                "+new line content",
                "-old line content",
                " context line",
            ],
        )
        # Test colored output
        out_col = render_dashboard(state, width=100, use_color=True, split_pane=True, diff_scroll_offset=0)
        self.assertIn("GIT DIFF", out_col)
        self.assertIn("new line content", out_col)
        self.assertIn("Mode: Split Diff", out_col)

        # Test plain output
        out_plain = render_dashboard(state, width=100, use_color=False, split_pane=True, diff_scroll_offset=0)
        self.assertIn("GIT DIFF [1-", out_plain)
        self.assertIn("new line content", out_plain)

    def test_render_split_dashboard_scrolling(self):
        diff_lines = [f"+diff line {i}" for i in range(40)]
        state = DashboardState(
            repo_root="/path/to/repo",
            branch="feature",
            head_commit="1122334",
            active_task={"id": "03.7", "title": "Diff Viewer", "status": "RUNNING"},
            acceptance_criteria=[],
            dod_items=[],
            audit_verdict=None,
            git_clean=False,
            staged_count=1,
            unstaged_count=0,
            untracked_count=0,
            git_status_preview=["M  large.py"],
            git_diff_lines=diff_lines,
        )
        out = render_dashboard(state, width=100, use_color=False, split_pane=True, diff_scroll_offset=10)
        self.assertIn("+diff line 10", out)
        self.assertIn("above", out)
        self.assertIn("below", out)


class TestDashboardController(unittest.TestCase):
    @patch("taskctl.tui.dashboard.collect_dashboard_state")
    def test_dashboard_snapshot(self, mock_state):
        mock_state.return_value = DashboardState(
            repo_root="/mock/repo",
            branch="main",
            head_commit="1122334",
            active_task={"id": "01.1", "title": "Test", "status": "PLANNING"},
            acceptance_criteria=[],
            dod_items=[],
            audit_verdict=None,
            git_clean=True,
            staged_count=0,
            unstaged_count=0,
            untracked_count=0,
            git_status_preview=[],
        )
        dash = Dashboard(repo_root="/mock/repo", use_color=False)
        snapshot = dash.render_snapshot()
        self.assertIn("TASKCTL COCKPIT", snapshot)
        self.assertIn("[01.1] Test", snapshot)

    def test_dashboard_run_non_tty(self):
        dash = Dashboard(use_color=False)
        with patch("sys.stdin.isatty", return_value=False):
            with patch("sys.stdout.write") as mock_stdout_write:
                code = dash.run()
                self.assertEqual(code, 0)
                mock_stdout_write.assert_called()

    def test_cmd_dashboard_snapshot(self):
        with patch("sys.stdout.write"):
            code = cmd_dashboard(snapshot=True, split=True)
            self.assertEqual(code, 0)

    def test_handle_input_mouse_sgr(self):
        dash = Dashboard()
        dash.scroll_offset = 6

        # SGR Wheel Up (button 64)
        act_up = dash.handle_input("\x1b[<64;10;20M")
        self.assertEqual(act_up, "refresh")
        self.assertEqual(dash.scroll_offset, 3)

        # SGR Wheel Down (button 65)
        act_down = dash.handle_input("\x1b[<65;10;20M")
        self.assertEqual(act_down, "refresh")
        self.assertEqual(dash.scroll_offset, 6)

        # Non-wheel mouse click ignored safely
        act_click = dash.handle_input("\x1b[<0;10;20M")
        self.assertIsNone(act_click)

    def test_handle_input_mouse_legacy(self):
        dash = Dashboard()
        dash.scroll_offset = 5

        # Legacy wheel up: 96
        act_up = dash.handle_input("\x1b[M" + chr(96) + "xy")
        self.assertEqual(act_up, "refresh")
        self.assertEqual(dash.scroll_offset, 2)

        # Legacy wheel down: 97
        act_down = dash.handle_input("\x1b[M" + chr(97) + "xy")
        self.assertEqual(act_down, "refresh")
        self.assertEqual(dash.scroll_offset, 5)

    def test_handle_input_keyboard_scroll_and_keys(self):
        dash = Dashboard()
        self.assertEqual(dash.scroll_offset, 0)

        # j (scroll down 1)
        dash.handle_input("j")
        self.assertEqual(dash.scroll_offset, 1)

        # Arrow Down
        dash.handle_input("\x1b[B")
        self.assertEqual(dash.scroll_offset, 2)

        # k (scroll up 1)
        dash.handle_input("k")
        self.assertEqual(dash.scroll_offset, 1)

        # Arrow Up
        dash.handle_input("\x1b[A")
        self.assertEqual(dash.scroll_offset, 0)

        # Page Down
        dash.handle_input("\x1b[6~")
        self.assertEqual(dash.scroll_offset, 10)

        # Page Up
        dash.handle_input("\x1b[5~")
        self.assertEqual(dash.scroll_offset, 0)

        # End & Home
        dash.handle_input("\x1b[F")
        self.assertEqual(dash.scroll_offset, 999999)
        dash.handle_input("\x1b[H")
        self.assertEqual(dash.scroll_offset, 0)

        # Toggle split pane
        self.assertFalse(dash.split_pane)
        dash.handle_input("d")
        self.assertTrue(dash.split_pane)
        dash.handle_input("\t")
        self.assertFalse(dash.split_pane)

        # Refresh and actions
        self.assertEqual(dash.handle_input("r"), "refresh")
        self.assertEqual(dash.handle_input("t"), "run_tests")
        self.assertEqual(dash.handle_input("q"), "quit")
        self.assertEqual(dash.handle_input("\x1b"), "quit")
        self.assertEqual(dash.handle_input("\x03"), "quit")

    @patch("select.select")
    @patch("sys.stdin.read")
    @patch("sys.stdin.isatty", return_value=True)
    @patch("sys.stdout.isatty", return_value=True)
    @patch("taskctl.tui.dashboard.collect_dashboard_state")
    def test_dashboard_interactive_quit(self, mock_state, mock_stdout_tty, mock_stdin_tty, mock_read, mock_select):
        mock_state.return_value = DashboardState(
            repo_root="/mock",
            branch="main",
            head_commit="111",
            active_task={"id": "01.1", "title": "Test", "status": "RUNNING"},
            acceptance_criteria=[],
            dod_items=[],
            audit_verdict=None,
            git_clean=True,
            staged_count=0,
            unstaged_count=0,
            untracked_count=0,
            git_status_preview=[],
        )
        # Mock pressing 'q' to quit
        mock_select.return_value = ([sys.stdin], [], [])
        mock_read.return_value = "q"

        dash = Dashboard(interval=0.1, use_color=False)
        with patch("sys.stdout.write"):
            code = dash.run()
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
