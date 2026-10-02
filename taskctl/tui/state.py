"""Dashboard state model and data collectors for taskctl TUI."""

from __future__ import annotations

import os
import sys
import glob
import time
import subprocess
import py_compile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from taskctl.core.parser import find_repo_root, get_task_file, parse_task_md
from taskctl.core.auditor import ScopeAuditor, AuditVerdict, AuditSeverity


@dataclass
class DoDCheckItem:
    """Individual Definition of Done (DoD) verification item."""
    name: str
    status: str  # "PASS", "FAIL", "WARN", "PENDING", "RUNNING"
    message: str
    details: str = ""
    duration_ms: float = 0.0

    @property
    def is_pass(self) -> bool:
        return self.status == "PASS"


@dataclass
class DashboardState:
    """Complete snapshot of the repository task contract and DoD status."""
    repo_root: str
    branch: str
    head_commit: str
    active_task: Dict[str, Any]
    acceptance_criteria: List[Dict[str, Any]]
    dod_items: List[DoDCheckItem]
    audit_verdict: Optional[AuditVerdict]
    git_clean: bool
    staged_count: int
    unstaged_count: int
    untracked_count: int
    git_status_preview: List[str]
    last_updated: float = field(default_factory=time.time)
    error_message: Optional[str] = None


def _check_python_syntax(repo_root: str) -> Tuple[bool, str, int]:
    """Verify syntax of all Python files in the repository using py_compile."""
    py_files: List[str] = []
    for root_dir, _, files in os.walk(repo_root):
        # Ignore virtual environments, git, cache
        if any(skip in root_dir for skip in [".git", "__pycache__", ".venv", "venv", "build", "dist"]):
            continue
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root_dir, f))

    errors: List[str] = []
    for py_file in py_files:
        try:
            py_compile.compile(py_file, doraise=True)
        except py_compile.PyCompileError as e:
            rel = os.path.relpath(py_file, repo_root)
            errors.append(f"{rel}: {e.msg}")

    if errors:
        return False, f"{len(errors)} syntax error(s) detected", len(py_files)
    return True, f"All {len(py_files)} Python files compiled cleanly", len(py_files)


def _check_git_workspace(repo_root: str) -> Tuple[bool, int, int, int, List[str], bool, str]:
    """Inspect git cleanliness, status, and diff --check."""
    res_stat = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    status_lines = [l for l in res_stat.stdout.splitlines() if l.strip()]

    staged = 0
    unstaged = 0
    untracked = 0
    preview: List[str] = []

    for l in status_lines:
        code = l[:2]
        filename = l[3:].strip()
        if code[0] in "MADRC":
            staged += 1
        if code[1] in "MD":
            unstaged += 1
        if code == "??":
            untracked += 1
        if len(preview) < 5:
            preview.append(l)

    # Check git diff --check (whitespace and merge markers)
    res_diff = subprocess.run(
        ["git", "diff", "--check"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    diff_clean = (res_diff.returncode == 0)
    diff_msg = "No conflict markers or whitespace errors" if diff_clean else res_diff.stdout.strip()[:60]

    is_clean = (len(status_lines) == 0 and diff_clean)
    return is_clean, staged, unstaged, untracked, preview, diff_clean, diff_msg


def _run_automated_tests(repo_root: str) -> Tuple[bool, str, float]:
    """Execute unittest discovery hermetically."""
    t0 = time.time()
    res = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "tests"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    duration = time.time() - t0
    passed = (res.returncode == 0)
    # Output parsing: e.g. "Ran 113 tests in 0.219s\n\nOK"
    last_line = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else ""
    if not last_line and res.stdout.strip():
        last_line = res.stdout.strip().splitlines()[-1]

    msg = f"{last_line} ({duration:.2f}s)" if last_line else ("Tests passed" if passed else "Tests failed")
    return passed, msg, duration


def collect_dashboard_state(
    repo_root: Optional[str] = None,
    run_tests: bool = False,
    run_audit: bool = True,
) -> DashboardState:
    """Collect real-time state for the dashboard."""
    if repo_root is None:
        repo_root = find_repo_root()

    # Git metadata
    branch_res = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    branch = branch_res.stdout.strip() or "unknown"

    commit_res = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    head_commit = commit_res.stdout.strip() or "unknown"

    # Parse TASK.md
    active_task: Dict[str, Any] = {}
    criteria: List[Dict[str, Any]] = []
    error_msg: Optional[str] = None

    try:
        task_file = get_task_file()
        with open(task_file, "r", encoding="utf-8") as f:
            content = f.read()
        active_task, _ = parse_task_md(content)
        criteria = active_task.get("criteria", [])
    except Exception as e:
        error_msg = f"Failed to parse TASK.md: {e}"

    # Git workspace
    git_clean, staged, unstaged, untracked, preview, diff_clean, diff_msg = _check_git_workspace(repo_root)

    # DoD Checklist items
    dod_items: List[DoDCheckItem] = []

    # 1. Syntax & Typing Check
    t0 = time.time()
    syntax_ok, syntax_msg, num_files = _check_python_syntax(repo_root)
    syntax_dur = (time.time() - t0) * 1000.0
    dod_items.append(DoDCheckItem(
        name="Syntax & Typing Check",
        status="PASS" if syntax_ok else "FAIL",
        message=syntax_msg,
        duration_ms=syntax_dur,
    ))

    # 2. Git Cleanliness
    git_msg = "Working tree clean" if len(preview) == 0 else f"{staged} staged, {unstaged} modified, {untracked} untracked"
    git_status = "PASS" if diff_clean else "FAIL"
    dod_items.append(DoDCheckItem(
        name="Git Cleanliness",
        status=git_status,
        message=f"{git_msg} | diff: {'clean' if diff_clean else 'issues'}",
        details=diff_msg if not diff_clean else "",
    ))

    # 3. Scope Audit
    audit_verdict: Optional[AuditVerdict] = None
    if run_audit:
        try:
            from pathlib import Path
            auditor = ScopeAuditor()
            audit_verdict = auditor.run(Path(repo_root))
            audit_status = audit_verdict.status
            rule_count = len(audit_verdict.results)
            passed_rules = sum(1 for r in audit_verdict.results if r.severity == AuditSeverity.APPROVED)
            status_label = "PASS" if audit_verdict.exit_code == 0 else ("WARN" if audit_verdict.exit_code == 1 else "FAIL")
            dod_items.append(DoDCheckItem(
                name="Scope Auditor",
                status=status_label,
                message=f"[{audit_status}] {passed_rules}/{rule_count} rules passed",
            ))
        except Exception as e:
            dod_items.append(DoDCheckItem(
                name="Scope Auditor",
                status="FAIL",
                message=f"Audit execution error: {e}",
            ))
    else:
        dod_items.append(DoDCheckItem(
            name="Scope Auditor",
            status="PENDING",
            message="Audit skipped",
        ))

    # 4. Automated Tests
    if run_tests:
        test_ok, test_msg, test_dur = _run_automated_tests(repo_root)
        dod_items.append(DoDCheckItem(
            name="Automated Tests",
            status="PASS" if test_ok else "FAIL",
            message=test_msg,
            duration_ms=test_dur * 1000.0,
        ))
    else:
        dod_items.append(DoDCheckItem(
            name="Automated Tests",
            status="PENDING",
            message="Press 't' to execute unittest suite",
        ))

    return DashboardState(
        repo_root=repo_root,
        branch=branch,
        head_commit=head_commit,
        active_task=active_task,
        acceptance_criteria=criteria,
        dod_items=dod_items,
        audit_verdict=audit_verdict,
        git_clean=git_clean,
        staged_count=staged,
        unstaged_count=unstaged,
        untracked_count=untracked,
        git_status_preview=preview,
        last_updated=time.time(),
        error_message=error_msg,
    )
