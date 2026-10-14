"""Dynamic Git worktree lifecycle management and branch merge verification engine.

Provides hermetic worktree isolation, disjoint file scope detection across
concurrent tasks in DAG execution stages, and in-memory dry-run merge verification.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from taskctl.core.parser import find_repo_root


@dataclass
class WorktreeInfo:
    """Metadata representing an allocated Git worktree."""
    task_id: str
    path: str
    branch: Optional[str] = None
    head_commit: Optional[str] = None
    is_bare: bool = False
    is_locked: bool = False
    lock_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "path": self.path,
            "branch": self.branch,
            "head_commit": self.head_commit,
            "is_bare": self.is_bare,
            "is_locked": self.is_locked,
            "lock_reason": self.lock_reason,
        }


@dataclass
class BranchDiffInfo:
    """Diff statistics of a task branch relative to a base reference."""
    branch: str
    base_ref: str
    files: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    head_commit: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "branch": self.branch,
            "base_ref": self.base_ref,
            "files": self.files,
            "files_count": len(self.files),
            "insertions": self.insertions,
            "deletions": self.deletions,
            "head_commit": self.head_commit,
        }


@dataclass
class DisjointScopeConflict:
    """Overlapping file paths modified concurrently by multiple tasks in the same stage."""
    file_path: str
    conflicting_branches: List[str]
    conflicting_tasks: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "conflicting_branches": self.conflicting_branches,
            "conflicting_tasks": self.conflicting_tasks,
        }


@dataclass
class MergeVerificationResult:
    """Result of an in-memory mergeability check against a base reference."""
    branch: str
    base_ref: str
    clean: bool
    status: str  # "clean", "conflict", "error", "skipped"
    conflict_files: List[str] = field(default_factory=list)
    tree_oid: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "branch": self.branch,
            "base_ref": self.base_ref,
            "clean": self.clean,
            "status": self.status,
            "conflict_files": self.conflict_files,
            "tree_oid": self.tree_oid,
            "message": self.message,
        }


@dataclass
class StageVerificationResult:
    """Aggregated verification result for a single DAG execution stage."""
    stage_index: int
    status: str  # "APPROVED", "CHANGES REQUIRED", "ERROR"
    is_executable: bool
    disjoint_scopes_clean: bool
    scope_conflicts: List[DisjointScopeConflict] = field(default_factory=list)
    task_merge_results: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_index": self.stage_index,
            "status": self.status,
            "is_executable": self.is_executable,
            "disjoint_scopes_clean": self.disjoint_scopes_clean,
            "scope_conflicts": [c.to_dict() for c in self.scope_conflicts],
            "task_merge_results": self.task_merge_results,
            "summary": self.summary,
        }


class WorktreeManager:
    """Manages ephemeral Git worktree lifecycles and stage merge verifications."""

    def __init__(
        self,
        repo_root: Optional[str] = None,
        worktree_base_dir: Optional[str] = None,
    ):
        self.repo_root = os.path.abspath(repo_root or find_repo_root())
        env_wt_dir = os.environ.get("TASKCTL_WORKTREE_DIR")
        if worktree_base_dir:
            self.worktree_base_dir = os.path.abspath(worktree_base_dir)
        elif env_wt_dir:
            self.worktree_base_dir = os.path.abspath(env_wt_dir)
        else:
            self.worktree_base_dir = os.path.join(self.repo_root, ".taskctl", "worktrees")

        self._ensure_git_exclude()

    def _run_git(
        self,
        args: List[str],
        cwd: Optional[str] = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        """Run a git command hermetically inside repo_root or specified cwd."""
        effective_cwd = cwd or self.repo_root
        cmd = ["git"] + args
        return subprocess.run(
            cmd,
            cwd=effective_cwd,
            text=True,
            capture_output=True,
            check=check,
        )

    def _ensure_git_exclude(self) -> None:
        """Ensure the worktrees base directory is safely ignored in .git/info/exclude."""
        try:
            # Query the git common dir (handles both regular repos and worktrees)
            res = self._run_git(["rev-parse", "--git-common-dir"])
            if res.returncode == 0 and res.stdout.strip():
                git_dir = res.stdout.strip()
                if not os.path.isabs(git_dir):
                    git_dir = os.path.join(self.repo_root, git_dir)
            else:
                git_dir = os.path.join(self.repo_root, ".git")

            if not os.path.exists(git_dir):
                return

            info_dir = os.path.join(git_dir, "info")
            os.makedirs(info_dir, exist_ok=True)
            exclude_file = os.path.join(info_dir, "exclude")

            # Determine relative path from repo root if within repo
            try:
                rel_path = os.path.relpath(self.worktree_base_dir, self.repo_root)
                if not rel_path.startswith(".."):
                    pattern = rel_path.rstrip("/") + "/*"
                    pattern_dir = rel_path.rstrip("/") + "/"
                else:
                    return
            except ValueError:
                return

            existing = ""
            if os.path.exists(exclude_file):
                with open(exclude_file, "r", encoding="utf-8") as f:
                    existing = f.read()

            if pattern not in existing and pattern_dir not in existing:
                with open(exclude_file, "a", encoding="utf-8") as f:
                    if existing and not existing.endswith("\n"):
                        f.write("\n")
                    f.write(f"# Auto-configured by taskctl worktree engine\n{pattern_dir}\n")
        except Exception:
            # Non-fatal if git exclude cannot be modified
            pass

    @staticmethod
    def sanitize_task_id(task_id: str) -> str:
        """Sanitize a task ID for safe use in branch and directory names."""
        return re.sub(r"[^a-zA-Z0-9_\-\.]", "-", task_id).strip("-")

    def create_worktree(
        self,
        task_id: str,
        branch: Optional[str] = None,
        base_ref: str = "HEAD",
        worktree_path: Optional[str] = None,
        force: bool = False,
    ) -> WorktreeInfo:
        """Provision an ephemeral worktree for the specified task."""
        sanitized = self.sanitize_task_id(task_id)
        if not sanitized:
            raise ValueError(f"Invalid task_id: '{task_id}'")

        target_branch = branch or f"task/{sanitized}"
        target_path = os.path.abspath(
            worktree_path or os.path.join(self.worktree_base_dir, sanitized)
        )

        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        # Check if the target branch already exists locally
        branch_check = self._run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{target_branch}"])
        branch_exists = (branch_check.returncode == 0)

        # Check if worktree directory already exists
        if os.path.exists(target_path):
            existing_wts = self.list_worktrees()
            for wt in existing_wts:
                if os.path.abspath(wt.path) == target_path:
                    if not force:
                        return wt
                    # If force, remove prior worktree registration
                    self._run_git(["worktree", "remove", "--force", target_path])
                    break
            if os.path.exists(target_path) and force:
                shutil.rmtree(target_path, ignore_errors=True)

        args = ["worktree", "add"]
        if force:
            args.append("--force")

        if branch_exists:
            args.extend([target_path, target_branch])
        else:
            args.extend(["-b", target_branch, target_path, base_ref])

        res = self._run_git(args)
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip() or f"git worktree add failed with code {res.returncode}"
            raise RuntimeError(f"Failed to create worktree at '{target_path}': {err}")

        # Resolve head commit
        head_res = self._run_git(["rev-parse", "HEAD"], cwd=target_path)
        head_commit = head_res.stdout.strip() if head_res.returncode == 0 else None

        return WorktreeInfo(
            task_id=task_id,
            path=target_path,
            branch=target_branch,
            head_commit=head_commit,
            is_bare=False,
            is_locked=False,
        )

    def list_worktrees(self) -> List[WorktreeInfo]:
        """List all registered Git worktrees, mapping them to task IDs when possible."""
        res = self._run_git(["worktree", "list", "--porcelain"])
        if res.returncode != 0:
            return []

        worktrees: List[WorktreeInfo] = []
        current: Dict[str, Any] = {}

        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                if "path" in current:
                    wt_obj = self._build_worktree_info(current)
                    worktrees.append(wt_obj)
                    current = {}
                continue

            if line.startswith("worktree "):
                if "path" in current:
                    worktrees.append(self._build_worktree_info(current))
                    current = {}
                current["path"] = line[len("worktree "):].strip()
            elif line.startswith("HEAD "):
                current["head_commit"] = line[len("HEAD "):].strip()
            elif line.startswith("branch "):
                ref = line[len("branch "):].strip()
                if ref.startswith("refs/heads/"):
                    current["branch"] = ref[len("refs/heads/"):]
                else:
                    current["branch"] = ref
            elif line == "bare":
                current["is_bare"] = True
            elif line == "locked":
                current["is_locked"] = True
            elif line.startswith("locked "):
                current["is_locked"] = True
                current["lock_reason"] = line[len("locked "):].strip()

        if "path" in current:
            worktrees.append(self._build_worktree_info(current))

        return worktrees

    def _build_worktree_info(self, data: Dict[str, Any]) -> WorktreeInfo:
        path = data.get("path", "")
        branch = data.get("branch")

        # Derive task_id from path if within worktree_base_dir or from branch
        task_id = "main"
        try:
            rel = os.path.relpath(path, self.worktree_base_dir)
            if not rel.startswith("..") and os.sep not in rel:
                task_id = rel
            elif branch and branch.startswith("task/"):
                task_id = branch[len("task/"):]
            elif path == self.repo_root:
                task_id = "root"
        except Exception:
            pass

        return WorktreeInfo(
            task_id=task_id,
            path=path,
            branch=branch,
            head_commit=data.get("head_commit"),
            is_bare=data.get("is_bare", False),
            is_locked=data.get("is_locked", False),
            lock_reason=data.get("lock_reason"),
        )

    def get_worktree(self, task_id: str) -> Optional[WorktreeInfo]:
        """Find an allocated worktree matching the given task ID."""
        sanitized = self.sanitize_task_id(task_id)
        expected_branch = f"task/{sanitized}"
        alt_branch = f"task/{task_id.replace('.', '-')}"
        alt_base = task_id.replace(".", "-")
        for wt in self.list_worktrees():
            if wt.task_id in (task_id, sanitized, alt_base):
                return wt
            if wt.branch in (expected_branch, task_id, alt_branch):
                return wt
            if os.path.basename(wt.path) in (sanitized, alt_base):
                return wt
        return None

    def remove_worktree(
        self,
        task_id: str,
        force: bool = False,
        delete_branch: bool = False,
    ) -> bool:
        """Safely remove a worktree and optionally delete its associated branch."""
        wt = self.get_worktree(task_id)
        if not wt:
            # If path exists directly under worktree_base_dir, attempt directory cleanup
            sanitized = self.sanitize_task_id(task_id)
            direct_path = os.path.join(self.worktree_base_dir, sanitized)
            if os.path.exists(direct_path):
                self._run_git(["worktree", "remove", "--force" if force else "", direct_path])
                shutil.rmtree(direct_path, ignore_errors=True)
                self.prune_worktrees()
                return True
            return False

        if wt.path == self.repo_root:
            raise ValueError("Cannot remove root repository working tree.")

        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(wt.path)

        res = self._run_git(args)
        if res.returncode != 0:
            # If git worktree remove fails, check if dir can be safely pruned
            if force and os.path.exists(wt.path):
                shutil.rmtree(wt.path, ignore_errors=True)
                self.prune_worktrees()
            else:
                err = res.stderr.strip() or res.stdout.strip()
                raise RuntimeError(f"Failed to remove worktree at '{wt.path}': {err}")

        if delete_branch and wt.branch:
            del_args = ["branch", "-D" if force else "-d", wt.branch]
            self._run_git(del_args)

        self.prune_worktrees()
        return True

    def prune_worktrees(self) -> str:
        """Execute git worktree prune to clean up stale metadata."""
        res = self._run_git(["worktree", "prune"])
        return res.stdout.strip()

    def get_branch_diff(self, branch: str, base_ref: str = "HEAD") -> BranchDiffInfo:
        """Retrieve modified files and diff statistics for a branch relative to base_ref."""
        # Check files modified
        diff_res = self._run_git(["diff", "--name-only", f"{base_ref}...{branch}"])
        if diff_res.returncode != 0:
            # Fallback to direct two-dot diff if merge-base calculation fails
            diff_res = self._run_git(["diff", "--name-only", base_ref, branch])

        files = [line.strip() for line in diff_res.stdout.splitlines() if line.strip()]

        # Shortstat
        stat_res = self._run_git(["diff", "--shortstat", f"{base_ref}...{branch}"])
        insertions = 0
        deletions = 0
        if stat_res.returncode == 0 and stat_res.stdout.strip():
            m_ins = re.search(r"(\d+)\s+insertion", stat_res.stdout)
            m_del = re.search(r"(\d+)\s+deletion", stat_res.stdout)
            if m_ins:
                insertions = int(m_ins.group(1))
            if m_del:
                deletions = int(m_del.group(1))

        rev_res = self._run_git(["rev-parse", branch])
        head_commit = rev_res.stdout.strip() if rev_res.returncode == 0 else None

        return BranchDiffInfo(
            branch=branch,
            base_ref=base_ref,
            files=files,
            insertions=insertions,
            deletions=deletions,
            head_commit=head_commit,
        )

    def check_disjoint_scopes(
        self,
        branch_files: Dict[str, List[str]],
        task_ids: Optional[Dict[str, str]] = None,
    ) -> List[DisjointScopeConflict]:
        """Verify that concurrent branches do not modify overlapping files."""
        file_to_branches: Dict[str, List[str]] = {}
        for b, files in branch_files.items():
            for f in files:
                file_to_branches.setdefault(f, []).append(b)

        conflicts: List[DisjointScopeConflict] = []
        task_map = task_ids or {}

        for file_path, branches in sorted(file_to_branches.items()):
            if len(branches) > 1:
                t_ids = [task_map.get(b, b) for b in branches]
                conflicts.append(
                    DisjointScopeConflict(
                        file_path=file_path,
                        conflicting_branches=branches,
                        conflicting_tasks=t_ids,
                    )
                )

        return conflicts

    def verify_branch_merge(
        self,
        branch: str,
        base_ref: str = "HEAD",
    ) -> MergeVerificationResult:
        """Perform an in-memory dry-run merge verification against base_ref.

        Uses `git merge-tree --write-tree` (Git >= 2.38) or fallback 3-way
        tree inspection without modifying the index or working directory.
        """
        # First verify both refs exist
        if self._run_git(["rev-parse", "--verify", "--quiet", branch]).returncode != 0:
            return MergeVerificationResult(
                branch=branch,
                base_ref=base_ref,
                clean=False,
                status="error",
                message=f"Branch '{branch}' does not exist",
            )
        if self._run_git(["rev-parse", "--verify", "--quiet", base_ref]).returncode != 0:
            return MergeVerificationResult(
                branch=branch,
                base_ref=base_ref,
                clean=False,
                status="error",
                message=f"Base ref '{base_ref}' does not exist",
            )

        # Attempt modern git merge-tree --write-tree
        res = self._run_git(["merge-tree", "--write-tree", base_ref, branch])

        if res.returncode == 0:
            tree_oid = res.stdout.strip().splitlines()[0] if res.stdout.strip() else None
            return MergeVerificationResult(
                branch=branch,
                base_ref=base_ref,
                clean=True,
                status="clean",
                tree_oid=tree_oid,
                message="Clean merge with zero conflicts.",
            )

        if res.returncode == 1:
            # Conflict detected by merge-tree --write-tree
            output = res.stdout + "\n" + res.stderr
            conflict_files = []
            for line in output.splitlines():
                m = re.search(r"CONFLICT\s+\([^)]+\):\s+Merge conflict in\s+(.*)", line)
                if m:
                    conflict_files.append(m.group(1).strip())
                elif "Auto-merging" in line and "conflict" in output.lower():
                    # check if marked conflict in subsequent lines
                    pass

            # If conflict_files empty from regex, inspect diff between base and branch
            if not conflict_files:
                for line in output.splitlines():
                    if line.startswith("CONFLICT "):
                        conflict_files.append(line.strip())

            return MergeVerificationResult(
                branch=branch,
                base_ref=base_ref,
                clean=False,
                status="conflict",
                conflict_files=sorted(list(set(conflict_files))),
                message="Merge conflicts detected during dry-run merge verification.",
            )

        # If returncode is > 1 (e.g. older Git or unsupported option), use fallback check
        mb_res = self._run_git(["merge-base", base_ref, branch])
        if mb_res.returncode == 0:
            base_commit = mb_res.stdout.strip()
            # Try deprecated trivial merge-tree
            legacy_res = self._run_git(["merge-tree", base_commit, base_ref, branch])
            if legacy_res.returncode == 0:
                has_conflict = "+<<<<<<<" in legacy_res.stdout
                if not has_conflict:
                    return MergeVerificationResult(
                        branch=branch,
                        base_ref=base_ref,
                        clean=True,
                        status="clean",
                        message="Clean merge verified via 3-way tree simulation.",
                    )
                else:
                    return MergeVerificationResult(
                        branch=branch,
                        base_ref=base_ref,
                        clean=False,
                        status="conflict",
                        message="Merge conflict markers detected during 3-way simulation.",
                    )

        return MergeVerificationResult(
            branch=branch,
            base_ref=base_ref,
            clean=False,
            status="error",
            message=res.stderr.strip() or f"git merge-tree exited with code {res.returncode}",
        )

    def verify_stage(
        self,
        stage_tasks: List[Dict[str, Any]],
        base_ref: str = "HEAD",
        stage_index: int = 0,
        check_disjoint: bool = True,
    ) -> StageVerificationResult:
        """Verify an entire DAG execution stage for disjoint scopes and clean mergeability."""
        branch_files: Dict[str, List[str]] = {}
        task_id_map: Dict[str, str] = {}
        merge_results: List[Dict[str, Any]] = []

        all_clean = True
        has_errors = False

        for task in stage_tasks:
            t_id = str(task.get("id", ""))
            sanitized = self.sanitize_task_id(t_id)
            branch = task.get("suggested_branch") or task.get("branch") or f"task/{sanitized}"
            task_id_map[branch] = t_id

            # Verify if branch exists
            b_exists = (self._run_git(["rev-parse", "--verify", "--quiet", branch]).returncode == 0)
            if not b_exists:
                # Branch not yet created or pushed
                res_entry = {
                    "task_id": t_id,
                    "branch": branch,
                    "status": "missing_branch",
                    "clean": False,
                    "files": [],
                    "message": f"Branch '{branch}' not found locally.",
                }
                merge_results.append(res_entry)
                has_errors = True
                all_clean = False
                continue

            diff_info = self.get_branch_diff(branch, base_ref=base_ref)
            branch_files[branch] = diff_info.files

            merge_res = self.verify_branch_merge(branch, base_ref=base_ref)
            if not merge_res.clean:
                all_clean = False
                if merge_res.status == "error":
                    has_errors = True

            res_entry = {
                "task_id": t_id,
                "branch": branch,
                "status": merge_res.status,
                "clean": merge_res.clean,
                "files": diff_info.files,
                "insertions": diff_info.insertions,
                "deletions": diff_info.deletions,
                "conflict_files": merge_res.conflict_files,
                "message": merge_res.message,
            }
            merge_results.append(res_entry)

        # Check disjoint scopes if concurrency > 1
        scope_conflicts: List[DisjointScopeConflict] = []
        if check_disjoint and len(stage_tasks) > 1:
            scope_conflicts = self.check_disjoint_scopes(branch_files, task_id_map)
            if scope_conflicts:
                all_clean = False

        if has_errors:
            overall_status = "ERROR"
            is_executable = False
        elif not all_clean:
            overall_status = "CHANGES REQUIRED"
            is_executable = False
        else:
            overall_status = "APPROVED"
            is_executable = True

        summary = {
            "total_tasks": len(stage_tasks),
            "clean_count": sum(1 for r in merge_results if r["clean"]),
            "conflict_count": sum(1 for r in merge_results if r["status"] == "conflict"),
            "missing_count": sum(1 for r in merge_results if r["status"] == "missing_branch"),
            "error_count": sum(1 for r in merge_results if r["status"] == "error"),
            "scope_conflicts_count": len(scope_conflicts),
        }

        return StageVerificationResult(
            stage_index=stage_index,
            status=overall_status,
            is_executable=is_executable,
            disjoint_scopes_clean=(len(scope_conflicts) == 0),
            scope_conflicts=scope_conflicts,
            task_merge_results=merge_results,
            summary=summary,
        )

    def verify_plan(
        self,
        plan_data: Dict[str, Any],
        stage_index: Optional[int] = None,
        base_ref: str = "HEAD",
    ) -> List[StageVerificationResult]:
        """Verify stages from an exported DAG execution plan dictionary."""
        stages = plan_data.get("stages", [])
        results: List[StageVerificationResult] = []

        for idx, s in enumerate(stages):
            s_idx = s.get("stage_index", idx)
            if stage_index is not None and s_idx != stage_index:
                continue

            tasks = s.get("tasks", [])
            res = self.verify_stage(
                stage_tasks=tasks,
                base_ref=base_ref,
                stage_index=s_idx,
                check_disjoint=s.get("parallel", len(tasks) > 1),
            )
            results.append(res)

        return results
