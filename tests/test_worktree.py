"""Hermetic unit tests for taskctl worktree manager and stage merge verification."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from taskctl.core.worktree import (
    WorktreeManager,
    WorktreeInfo,
    DisjointScopeConflict,
    MergeVerificationResult,
    StageVerificationResult,
)
from taskctl.cli import cmd_worktree, cmd_stage_verify, cmd_stage_verify_from_args


class TestWorktreeManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="taskctl_wt_test_")
        self.repo_dir = os.path.join(self.test_dir, "repo")
        os.makedirs(self.repo_dir, exist_ok=True)

        # Initialize real git repository hermetically
        self._git(["init"], cwd=self.repo_dir)
        self._git(["config", "user.name", "Taskctl Tester"], cwd=self.repo_dir)
        self._git(["config", "user.email", "tester@taskctl.local"], cwd=self.repo_dir)

        # Initial commit
        self.readme_path = os.path.join(self.repo_dir, "README.md")
        with open(self.readme_path, "w", encoding="utf-8") as f:
            f.write("# Main Repo\nInitial baseline\n")
        self._git(["add", "README.md"], cwd=self.repo_dir)
        self._git(["commit", "-m", "chore: initial commit"], cwd=self.repo_dir)

        # Ensure main branch is active
        self._git(["branch", "-M", "main"], cwd=self.repo_dir)

        # Create basic .agent/TASK.md
        agent_dir = os.path.join(self.repo_dir, ".agent")
        os.makedirs(agent_dir, exist_ok=True)
        task_md = os.path.join(agent_dir, "TASK.md")
        with open(task_md, "w", encoding="utf-8") as f:
            f.write("""# TASK.md

## Active Task

### 📌 Task [01.1]: Alpha Feature
- **Status:** RUNNING

### Acceptance Criteria
- [ ] Criterion 1

---

## Backlog

- [ ] **[01.2]** Beta Feature (deps: 01.1)
- [ ] **[01.3]** Gamma Feature (deps: 01.1)

---

## Completed Tasks Log
""")
        self._git(["add", ".agent/TASK.md"], cwd=self.repo_dir)
        self._git(["commit", "-m", "chore: add task contract"], cwd=self.repo_dir)

        self.mgr = WorktreeManager(repo_root=self.repo_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _git(self, args, cwd=None):
        return subprocess.run(
            ["git"] + args,
            cwd=cwd or self.repo_dir,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_ensure_git_exclude(self):
        exclude_path = os.path.join(self.repo_dir, ".git", "info", "exclude")
        self.assertTrue(os.path.exists(exclude_path))
        with open(exclude_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(".taskctl/worktrees/", content)

    def test_create_list_and_remove_worktree(self):
        # Create worktree for task [01.2]
        wt = self.mgr.create_worktree(task_id="01.2", base_ref="HEAD")
        self.assertIsNotNone(wt)
        self.assertEqual(wt.task_id, "01.2")
        self.assertEqual(wt.branch, "task/01.2")
        self.assertTrue(os.path.exists(wt.path))

        # Check listed worktrees
        wts = self.mgr.list_worktrees()
        paths = [os.path.abspath(w.path) for w in wts]
        self.assertIn(os.path.abspath(wt.path), paths)

        # Get worktree
        found = self.mgr.get_worktree("01.2")
        self.assertIsNotNone(found)
        self.assertEqual(found.branch, "task/01.2")

        # Calling create again on existing worktree returns existing without error
        wt2 = self.mgr.create_worktree(task_id="01.2")
        self.assertEqual(wt.path, wt2.path)

        # Remove worktree
        removed = self.mgr.remove_worktree("01.2", force=True, delete_branch=True)
        self.assertTrue(removed)
        self.assertIsNone(self.mgr.get_worktree("01.2"))

    def test_cannot_remove_root_repo(self):
        wts = self.mgr.list_worktrees()
        root_wt = next((w for w in wts if os.path.abspath(w.path) == os.path.abspath(self.repo_dir)), None)
        self.assertIsNotNone(root_wt)
        with self.assertRaises(ValueError):
            self.mgr.remove_worktree(root_wt.task_id)

    def test_disjoint_scopes_detection(self):
        # Create two branches modifying separate files
        self._git(["branch", "task/01-2", "HEAD"])
        self._git(["branch", "task/01-3", "HEAD"])

        wt2 = self.mgr.create_worktree(task_id="01.2", branch="task/01-2")
        with open(os.path.join(wt2.path, "alpha.py"), "w") as f:
            f.write("# alpha module\n")
        self._git(["add", "alpha.py"], cwd=wt2.path)
        self._git(["commit", "-m", "feat: add alpha"], cwd=wt2.path)

        wt3 = self.mgr.create_worktree(task_id="01.3", branch="task/01-3")
        with open(os.path.join(wt3.path, "beta.py"), "w") as f:
            f.write("# beta module\n")
        self._git(["add", "beta.py"], cwd=wt3.path)
        self._git(["commit", "-m", "feat: add beta"], cwd=wt3.path)

        diff2 = self.mgr.get_branch_diff("task/01-2", base_ref="main")
        diff3 = self.mgr.get_branch_diff("task/01-3", base_ref="main")
        self.assertEqual(diff2.files, ["alpha.py"])
        self.assertEqual(diff3.files, ["beta.py"])

        conflicts = self.mgr.check_disjoint_scopes({
            "task/01-2": diff2.files,
            "task/01-3": diff3.files,
        })
        self.assertEqual(len(conflicts), 0)

        # Now simulate an overlapping change in wt3 to alpha.py
        with open(os.path.join(wt3.path, "alpha.py"), "w") as f:
            f.write("# overlapping alpha edit\n")
        self._git(["add", "alpha.py"], cwd=wt3.path)
        self._git(["commit", "-m", "fix: touch alpha too"], cwd=wt3.path)

        diff3_updated = self.mgr.get_branch_diff("task/01-3", base_ref="main")
        conflicts = self.mgr.check_disjoint_scopes({
            "task/01-2": diff2.files,
            "task/01-3": diff3_updated.files,
        }, task_ids={"task/01-2": "01.2", "task/01-3": "01.3"})

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].file_path, "alpha.py")
        self.assertIn("task/01-2", conflicts[0].conflicting_branches)
        self.assertIn("task/01-3", conflicts[0].conflicting_branches)
        self.assertIn("01.2", conflicts[0].conflicting_tasks)

    def test_verify_branch_merge_clean(self):
        # Create a branch and add a new file
        self._git(["checkout", "-b", "task/clean-branch", "main"])
        new_file = os.path.join(self.repo_dir, "clean.txt")
        with open(new_file, "w") as f:
            f.write("Clean content\n")
        self._git(["add", "clean.txt"])
        self._git(["commit", "-m", "feat: clean file"])
        self._git(["checkout", "main"])

        res = self.mgr.verify_branch_merge("task/clean-branch", base_ref="main")
        self.assertTrue(res.clean)
        self.assertEqual(res.status, "clean")
        self.assertEqual(len(res.conflict_files), 0)

    def test_verify_branch_merge_conflict(self):
        # In main, modify README
        with open(self.readme_path, "a") as f:
            f.write("Line from main branch\n")
        self._git(["add", "README.md"])
        self._git(["commit", "-m", "chore: update readme on main"])

        # Create branch from previous commit and modify the same line differently
        prev_commit = self._git(["rev-parse", "HEAD~1"]).stdout.strip()
        self._git(["checkout", "-b", "task/conflict-branch", prev_commit])
        with open(self.readme_path, "a") as f:
            f.write("Conflicting line from feature branch\n")
        self._git(["add", "README.md"])
        self._git(["commit", "-m", "chore: conflicting readme"])
        self._git(["checkout", "main"])

        res = self.mgr.verify_branch_merge("task/conflict-branch", base_ref="main")
        self.assertFalse(res.clean)
        self.assertEqual(res.status, "conflict")
        self.assertTrue(any("README.md" in cf for cf in res.conflict_files))

    def test_verify_stage_execution(self):
        # Branch 1 clean
        self._git(["branch", "task/01-2", "main"])
        wt2 = self.mgr.create_worktree("01.2", branch="task/01-2")
        with open(os.path.join(wt2.path, "f1.txt"), "w") as f:
            f.write("File 1\n")
        self._git(["add", "f1.txt"], cwd=wt2.path)
        self._git(["commit", "-m", "feat: f1"], cwd=wt2.path)

        # Branch 2 clean and disjoint
        self._git(["branch", "task/01-3", "main"])
        wt3 = self.mgr.create_worktree("01.3", branch="task/01-3")
        with open(os.path.join(wt3.path, "f2.txt"), "w") as f:
            f.write("File 2\n")
        self._git(["add", "f2.txt"], cwd=wt3.path)
        self._git(["commit", "-m", "feat: f2"], cwd=wt3.path)

        stage_tasks = [
            {"id": "01.2", "suggested_branch": "task/01-2"},
            {"id": "01.3", "suggested_branch": "task/01-3"},
        ]

        stage_res = self.mgr.verify_stage(stage_tasks, base_ref="main", stage_index=0)
        self.assertEqual(stage_res.status, "APPROVED")
        self.assertTrue(stage_res.is_executable)
        self.assertTrue(stage_res.disjoint_scopes_clean)
        self.assertEqual(len(stage_res.scope_conflicts), 0)

    def test_verify_plan_integration(self):
        # Create execution plan dict
        self._git(["branch", "task/01-2", "main"])
        wt2 = self.mgr.create_worktree("01.2", branch="task/01-2")
        with open(os.path.join(wt2.path, "f1.txt"), "w") as f:
            f.write("File 1\n")
        self._git(["add", "f1.txt"], cwd=wt2.path)
        self._git(["commit", "-m", "feat: f1"], cwd=wt2.path)

        plan_data = {
            "version": "1.0.0",
            "stages": [
                {
                    "stage_index": 0,
                    "concurrency": 1,
                    "parallel": False,
                    "tasks": [
                        {"id": "01.2", "suggested_branch": "task/01-2"}
                    ],
                }
            ],
        }

        results = self.mgr.verify_plan(plan_data, base_ref="main")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "APPROVED")


class TestWorktreeCLI(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="taskctl_cli_wt_")
        self.repo_dir = os.path.join(self.test_dir, "repo")
        os.makedirs(self.repo_dir, exist_ok=True)

        self._git(["init"], cwd=self.repo_dir)
        self._git(["config", "user.name", "CLI Tester"], cwd=self.repo_dir)
        self._git(["config", "user.email", "clitester@taskctl.local"], cwd=self.repo_dir)

        readme_path = os.path.join(self.repo_dir, "README.md")
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write("# CLI Repo\n")
        self._git(["add", "README.md"], cwd=self.repo_dir)
        self._git(["commit", "-m", "chore: initial commit"], cwd=self.repo_dir)
        self._git(["branch", "-M", "main"], cwd=self.repo_dir)

        agent_dir = os.path.join(self.repo_dir, ".agent")
        os.makedirs(agent_dir, exist_ok=True)
        task_md = os.path.join(agent_dir, "TASK.md")
        with open(task_md, "w", encoding="utf-8") as f:
            f.write("""# TASK.md

## Active Task

### 📌 Task [01.1]: First Active Feature
- **Status:** RUNNING

### Acceptance Criteria
- [ ] Criterion 1

---

## Backlog

- [ ] **[01.2]** Second Feature (deps: 01.1)

---

## Completed Tasks Log
""")
        self._git(["add", ".agent/TASK.md"], cwd=self.repo_dir)
        self._git(["commit", "-m", "chore: add task contract"], cwd=self.repo_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _git(self, args, cwd=None):
        return subprocess.run(
            ["git"] + args,
            cwd=cwd or self.repo_dir,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_cli_worktree_create_list_remove(self):
        # Create worktree via CLI
        ret = cmd_worktree(
            action="create",
            task_id="01.2",
            base_ref="main",
            repo=self.repo_dir,
        )
        self.assertEqual(ret, 0)

        # List worktrees via CLI (text and json)
        ret_list = cmd_worktree(action="list", repo=self.repo_dir)
        self.assertEqual(ret_list, 0)

        ret_json = cmd_worktree(action="list", repo=self.repo_dir, json_output=True)
        self.assertEqual(ret_json, 0)

        # Prune worktrees
        ret_prune = cmd_worktree(action="prune", repo=self.repo_dir)
        self.assertEqual(ret_prune, 0)

        # Remove worktree
        ret_rm = cmd_worktree(action="remove", task_id="01.2", repo=self.repo_dir, force=True, delete_branch=True)
        self.assertEqual(ret_rm, 0)

    def test_cli_stage_verify_clean(self):
        # 1. When task [01.1] has no branch yet, verifying all stages returns exit code 2 (missing_branch)
        ret_missing = cmd_stage_verify(
            base_ref="main",
            repo=self.repo_dir,
        )
        self.assertEqual(ret_missing, 2)

        # 2. Provision branch for task [01.2]
        cmd_worktree(action="create", task_id="01.2", base_ref="main", repo=self.repo_dir)
        mgr = WorktreeManager(repo_root=self.repo_dir)
        wt2 = mgr.get_worktree("01.2")
        with open(os.path.join(wt2.path, "code2.py"), "w") as f:
            f.write("# new feature 2\n")
        self._git(["add", "code2.py"], cwd=wt2.path)
        self._git(["commit", "-m", "feat: add feature code 2"], cwd=wt2.path)

        # Verifying specifically stage 1 (which only contains [01.2]) passes cleanly
        ret_stage1 = cmd_stage_verify(
            stage_index=1,
            base_ref="main",
            repo=self.repo_dir,
        )
        self.assertEqual(ret_stage1, 0)

        # Verifying via cmd_stage_verify_from_args with --stage 1
        ret_args = cmd_stage_verify_from_args(
            ["--stage", "1", "--base", "main", "--repo", self.repo_dir],
        )
        self.assertEqual(ret_args, 0)

        # 3. Provision branch for task [01.1] as well
        cmd_worktree(action="create", task_id="01.1", base_ref="main", repo=self.repo_dir)
        wt1 = mgr.get_worktree("01.1")
        with open(os.path.join(wt1.path, "code1.py"), "w") as f:
            f.write("# new feature 1\n")
        self._git(["add", "code1.py"], cwd=wt1.path)
        self._git(["commit", "-m", "feat: add feature code 1"], cwd=wt1.path)

        # Now all stages pass cleanly
        ret_all = cmd_stage_verify(
            base_ref="main",
            repo=self.repo_dir,
        )
        self.assertEqual(ret_all, 0)

        # JSON mode
        ret_json = cmd_stage_verify(
            base_ref="main",
            repo=self.repo_dir,
            json_output=True,
        )
        self.assertEqual(ret_json, 0)


if __name__ == "__main__":
    unittest.main()
