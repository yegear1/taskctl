"""Unit tests for multi-repository context firewall and --repo flag support."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from taskctl.core.parser import resolve_repo_path, get_task_file, find_repo_root, parse_task_md
from taskctl.cli import (
    cmd_status,
    cmd_plan,
    cmd_next,
    cmd_audit,
    cmd_done,
    main,
)


def _init_repo(repo_dir: str, task_content: str) -> None:
    """Helper to initialize a git repo with a .agent/TASK.md."""
    os.makedirs(os.path.join(repo_dir, ".agent"), exist_ok=True)
    task_file = os.path.join(repo_dir, ".agent", "TASK.md")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write(task_content)

    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=repo_dir, capture_output=True, check=True)


SAMPLE_TASK_MD = """# Tasks & Roadmap

### 📌 Task [01.1]: Alpha Feature

- **Description:** Implement alpha feature in remote repo
- **Systems Involved:** [core]
- **Runtime Target:** Profile 'default' | Model: 'flash'
- **Status:** READY FOR PLANNING

### Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

---

## Backlog

- [ ] **[01.2]** Beta Feature

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
"""


class TestResolveRepoPath(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="taskctl_repo_test_")
        self.repo_a = os.path.join(self.temp_dir, "repo_a")
        self.repo_b = os.path.join(self.temp_dir, "repo_b")
        _init_repo(self.repo_a, SAMPLE_TASK_MD)
        _init_repo(self.repo_b, SAMPLE_TASK_MD)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_default_resolves_base_dir(self):
        resolved = resolve_repo_path(None, base_dir=self.repo_a)
        self.assertEqual(os.path.realpath(resolved), os.path.realpath(self.repo_a))

        resolved_empty = resolve_repo_path("", base_dir=self.repo_a)
        self.assertEqual(os.path.realpath(resolved_empty), os.path.realpath(self.repo_a))

    def test_absolute_path_resolution(self):
        resolved = resolve_repo_path(self.repo_b, base_dir=self.repo_a)
        self.assertEqual(os.path.realpath(resolved), os.path.realpath(self.repo_b))

    def test_relative_path_resolution(self):
        rel_path = os.path.relpath(self.repo_b, self.repo_a)
        resolved = resolve_repo_path(rel_path, base_dir=self.repo_a)
        self.assertEqual(os.path.realpath(resolved), os.path.realpath(self.repo_b))

    def test_task_file_path_resolution(self):
        task_file = os.path.join(self.repo_b, ".agent", "TASK.md")
        resolved = resolve_repo_path(task_file)
        self.assertEqual(os.path.realpath(resolved), os.path.realpath(self.repo_b))

    def test_name_matching_current_repo_basename(self):
        resolved = resolve_repo_path("repo_a", base_dir=self.repo_a)
        self.assertEqual(os.path.realpath(resolved), os.path.realpath(self.repo_a))

    def test_name_matching_sibling_repo(self):
        resolved = resolve_repo_path("repo_b", base_dir=self.repo_a)
        self.assertEqual(os.path.realpath(resolved), os.path.realpath(self.repo_b))

    def test_name_matching_watch_repos(self):
        repo_c = os.path.join(self.temp_dir, "external", "repo_c")
        _init_repo(repo_c, SAMPLE_TASK_MD)

        with patch.dict(os.environ, {"TASKCTL_WATCH_REPOS": repo_c}):
            resolved = resolve_repo_path("repo_c", base_dir=self.repo_a)
            self.assertEqual(os.path.realpath(resolved), os.path.realpath(repo_c))

    def test_nonexistent_repo_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            resolve_repo_path("nonexistent_repo_xyz_123", base_dir=self.repo_a)


class TestLifecycleCommandsWithRepo(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="taskctl_lifecycle_test_")
        self.local_repo = os.path.join(self.temp_dir, "local_repo")
        self.remote_repo = os.path.join(self.temp_dir, "remote_repo")
        _init_repo(self.local_repo, SAMPLE_TASK_MD.replace("Alpha Feature", "Local Alpha"))
        _init_repo(self.remote_repo, SAMPLE_TASK_MD.replace("Alpha Feature", "Remote Alpha"))
        self.old_cwd = os.getcwd()
        os.chdir(self.local_repo)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.temp_dir)

    def test_cmd_status_with_repo(self):
        with patch("sys.stdout") as mock_stdout:
            cmd_status(repo=self.remote_repo)
            output = "".join(call.args[0] for call in mock_stdout.write.mock_calls if call.args)
            self.assertIn("Remote Alpha", output)
            self.assertIn("remote_repo", output)
            self.assertNotIn("Local Alpha", output)

    def test_cmd_plan_with_repo(self):
        cmd_plan(prompt="Decompose remote tasks", repo=self.remote_repo)

        # Remote repo's TASK.md must be updated to PLANNING
        remote_task = get_task_file(self.remote_repo)
        with open(remote_task, "r", encoding="utf-8") as f:
            content_remote = f.read()
        self.assertIn("- **Status:** PLANNING", content_remote)

        # Local repo's TASK.md must remain untouched
        local_task = get_task_file(self.local_repo)
        with open(local_task, "r", encoding="utf-8") as f:
            content_local = f.read()
        self.assertIn("- **Status:** READY FOR PLANNING", content_local)

    def test_cmd_next_with_repo(self):
        cmd_next(weight="medium", handoff=False, repo=self.remote_repo)

        # Remote repo promoted next backlog task [01.2] to RUNNING
        remote_task = get_task_file(self.remote_repo)
        with open(remote_task, "r", encoding="utf-8") as f:
            content_remote = f.read()
        active_remote, backlog_remote = parse_task_md(content_remote)
        self.assertEqual(active_remote.get("id"), "01.2")
        self.assertEqual(active_remote.get("status"), "RUNNING")

        # Local repo remains unchanged
        local_task = get_task_file(self.local_repo)
        with open(local_task, "r", encoding="utf-8") as f:
            content_local = f.read()
        active_local, _ = parse_task_md(content_local)
        self.assertEqual(active_local.get("id"), "01.1")
        self.assertEqual(active_local.get("status"), "READY FOR PLANNING")

    def test_cmd_audit_with_repo(self):
        # Audit remote repo cleanly
        exit_code = cmd_audit(domain_lint=True, repo=self.remote_repo)
        self.assertEqual(exit_code, 0)

        # Invalid repo returns exit code 1
        err_code = cmd_audit(repo="invalid_repo_name_999")
        self.assertEqual(err_code, 1)

    def test_cmd_done_with_repo(self):
        # Create a staged file in the remote repo
        new_file = os.path.join(self.remote_repo, "remote_module.py")
        with open(new_file, "w", encoding="utf-8") as f:
            f.write("# remote module\n")
        subprocess.run(["git", "add", "remote_module.py"], cwd=self.remote_repo, check=True)

        # Execute cmd_done targeting remote_repo
        cmd_done(
            custom_msg="feat(remote): implement remote module",
            promote=True,
            handoff=False,
            repo=self.remote_repo,
        )

        # Check git log in remote repo
        git_log = subprocess.run(
            ["git", "log", "--oneline", "-n", "2"],
            cwd=self.remote_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("feat(remote): implement remote module", git_log)
        self.assertIn("docs(task): log completion of [01.1]", git_log)

        # Remote backlog item [01.2] should be promoted to RUNNING because promote=True
        with open(get_task_file(self.remote_repo), "r", encoding="utf-8") as f:
            content = f.read()
        active, _ = parse_task_md(content)
        self.assertEqual(active.get("id"), "01.2")
        self.assertEqual(active.get("status"), "RUNNING")

        # Verify local repo git log is completely untouched (only has initial commit)
        local_log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=self.local_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip().splitlines()
        self.assertEqual(len(local_log), 1)
        self.assertIn("chore: initial commit", local_log[0])


class TestCLIMainRepoParsing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="taskctl_main_test_")
        self.repo = os.path.join(self.temp_dir, "target_repo")
        _init_repo(self.repo, SAMPLE_TASK_MD)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_cli_status_repo_arg(self):
        with patch.object(sys, "argv", ["taskctl", "status", "--repo", self.repo]):
            with patch("taskctl.cli.cmd_status") as mock_status:
                main()
                mock_status.assert_called_once_with(repo=self.repo)

    def test_cli_plan_repo_arg(self):
        with patch.object(sys, "argv", ["taskctl", "plan", "prompt here", "--repo", self.repo]):
            with patch("taskctl.cli.cmd_plan") as mock_plan:
                main()
                mock_plan.assert_called_once_with(prompt="prompt here", repo=self.repo)

    def test_cli_next_repo_arg(self):
        with patch.object(sys, "argv", ["taskctl", "next", "--repo", self.repo, "--no-handoff"]):
            with patch("taskctl.cli.cmd_next") as mock_next:
                main()
                mock_next.assert_called_once_with(
                    weight="medium",
                    target_agent=None,
                    handoff=False,
                    repo=self.repo,
                )

    def test_cli_audit_repo_arg(self):
        with patch.object(sys, "argv", ["taskctl", "audit", "--domain-lint", "--repo", self.repo]):
            with patch("taskctl.cli.cmd_audit", return_value=0) as mock_audit:
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
                mock_audit.assert_called_once_with(
                    delegate=False,
                    agent_name=None,
                    domain_lint=True,
                    repo=self.repo,
                )

    def test_cli_done_repo_arg(self):
        with patch.object(sys, "argv", ["taskctl", "done", "feat: finish", "-p", "--repo", self.repo, "--no-handoff"]):
            with patch("taskctl.cli.cmd_done") as mock_done:
                main()
                mock_done.assert_called_once_with(
                    custom_msg="feat: finish",
                    promote=True,
                    weight="medium",
                    target_agent=None,
                    handoff=False,
                    repo=self.repo,
                )

    def test_cli_graph_repo_arg(self):
        with patch.object(sys, "argv", ["taskctl", "graph", "--repo", self.repo, "--export-plan"]):
            with patch("taskctl.cli.cmd_graph", return_value=0) as mock_graph:
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
                mock_graph.assert_called_once_with(
                    mermaid=False,
                    json_output=False,
                    check_cycles=False,
                    file_path=None,
                    no_infer=False,
                    export_plan=True,
                    out_file=None,
                    repo=self.repo,
                )


if __name__ == "__main__":
    unittest.main()
