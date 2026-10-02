"""Scope Auditor rule-based policy engine for taskctl.

Evaluates git hygiene, task contracts, syntax validity, and security boundaries.
Returns semantic exit codes:
- 0: APPROVED
- 1: CHANGES REQUIRED
- 2: REJECTED
"""

from __future__ import annotations

import os
import re
import py_compile
import subprocess
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional

from taskctl.core.parser import parse_task_md
from taskctl.core.commits import parse_conventional_commit


class AuditSeverity(IntEnum):
    APPROVED = 0
    CHANGES_REQUIRED = 1
    REJECTED = 2

    @property
    def label(self) -> str:
        if self == AuditSeverity.APPROVED:
            return "APPROVED"
        if self == AuditSeverity.CHANGES_REQUIRED:
            return "CHANGES REQUIRED"
        return "REJECTED"


@dataclass
class RuleResult:
    rule_name: str
    severity: AuditSeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return int(self.severity)


@dataclass
class AuditVerdict:
    status: str
    exit_code: int
    results: List[RuleResult]

    @property
    def is_approved(self) -> bool:
        return self.exit_code == 0


class GitHygieneRule:
    """Verifies that working tree / staged changes have no conflict markers or whitespace errors."""

    rule_name: str = "git-hygiene"

    def evaluate(self, repo_path: Path) -> RuleResult:
        try:
            res = subprocess.run(
                ["git", "diff", "--check"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                err_lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
                return RuleResult(
                    rule_name=self.rule_name,
                    severity=AuditSeverity.CHANGES_REQUIRED,
                    message="git diff --check detected conflict markers, whitespace errors, or unmerged paths.",
                    details={"errors": err_lines[:5]},
                )
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.APPROVED,
                message="Git diff check passed cleanly with zero whitespace or conflict errors.",
            )
        except Exception as e:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Failed to execute git hygiene check: {e}",
            )


class TaskContractRule:
    """Verifies integrity and invariants of .agent/TASK.md."""

    rule_name: str = "task-contract"
    VALID_STATUSES = {"READY FOR PLANNING", "PLANNING", "RUNNING"}
    ID_PATTERN = re.compile(r"^\d{2}\.\d+(\.\d+)*$")

    def evaluate(self, repo_path: Path) -> RuleResult:
        task_file = repo_path / ".agent" / "TASK.md"
        if not task_file.exists():
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.REJECTED,
                message="Missing required contract file: .agent/TASK.md",
            )

        try:
            content = task_file.read_text(encoding="utf-8")
            active_task, backlog = parse_task_md(content)
        except Exception as e:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.REJECTED,
                message=f"Failed to parse .agent/TASK.md: {e}",
            )

        task_id = active_task.get("id", "").strip()
        status = active_task.get("status", "").strip()
        title = active_task.get("title", "").strip()

        if not task_id or (task_id != "XX.Y" and not self.ID_PATTERN.match(task_id)):
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.REJECTED,
                message=f"Invalid task ID schema: '{task_id}'. Expected format '[XX.Y]'.",
            )

        if status not in self.VALID_STATUSES:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Invalid task status: '{status}'. Expected one of {sorted(self.VALID_STATUSES)}.",
            )

        if not title:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message="Active task has an empty title.",
            )

        return RuleResult(
            rule_name=self.rule_name,
            severity=AuditSeverity.APPROVED,
            message=f"Task contract [.agent/TASK.md] verified: Task [{task_id}] '{title}' ({status}).",
            details={"task_id": task_id, "status": status, "backlog_count": len(backlog)},
        )


class SyntaxCompilationRule:
    """Verifies all Python source files in the repository compile cleanly without syntax errors."""

    rule_name: str = "syntax-compilation"
    IGNORED_DIRS = {".git", ".venv", "venv", "build", "dist", "__pycache__", ".tox", ".eggs"}

    def evaluate(self, repo_path: Path) -> RuleResult:
        failed_files: List[Dict[str, str]] = []

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in self.IGNORED_DIRS]
            for file in files:
                if file.endswith(".py"):
                    full_path = Path(root) / file
                    try:
                        py_compile.compile(str(full_path), doraise=True)
                    except py_compile.PyCompileError as e:
                        failed_files.append({"file": str(full_path.relative_to(repo_path)), "error": str(e)})

        if failed_files:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Python syntax compilation failed on {len(failed_files)} file(s).",
                details={"errors": failed_files[:5]},
            )

        return RuleResult(
            rule_name=self.rule_name,
            severity=AuditSeverity.APPROVED,
            message="All Python source files compiled with 0 syntax errors.",
        )


class SecretsBoundaryRule:
    """Verifies that no private keys, environment secrets, or socket files are staged."""

    rule_name: str = "secrets-boundary"
    FORBIDDEN_EXACT = {".env", "id_rsa", "id_ed25519", "credentials.json", "token.secret"}
    FORBIDDEN_SUFFIXES = {".key", ".pem", ".pfx", ".p12", ".sock"}

    def evaluate(self, repo_path: Path) -> RuleResult:
        try:
            res = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            staged = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        except Exception as e:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Failed to inspect git index for staged secrets: {e}",
            )

        leaked: List[str] = []
        for file_path in staged:
            basename = os.path.basename(file_path)
            if basename in self.FORBIDDEN_EXACT:
                leaked.append(file_path)
            elif basename.startswith(".env.") and not basename.endswith(".example"):
                leaked.append(file_path)
            elif any(basename.endswith(sfx) for sfx in self.FORBIDDEN_SUFFIXES):
                leaked.append(file_path)

        if leaked:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.REJECTED,
                message=f"Security boundary violation: Sensitive secret/key file(s) staged: {leaked}",
                details={"leaked_files": leaked},
            )

        return RuleResult(
            rule_name=self.rule_name,
            severity=AuditSeverity.APPROVED,
            message="No staged credentials, secret files, or private keys detected.",
        )


class CommitConventionRule:
    """Verifies that the latest git commit on the current branch complies with Conventional Commits."""

    rule_name: str = "commit-convention"

    def evaluate(self, repo_path: Path) -> RuleResult:
        try:
            rev_check = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if rev_check.returncode != 0:
                return RuleResult(
                    rule_name=self.rule_name,
                    severity=AuditSeverity.APPROVED,
                    message="Repository has no commits yet; commit convention check skipped.",
                )

            log_res = subprocess.run(
                ["git", "log", "-1", "--pretty=%B"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if log_res.returncode != 0:
                return RuleResult(
                    rule_name=self.rule_name,
                    severity=AuditSeverity.CHANGES_REQUIRED,
                    message=f"Failed to read git commit log: {log_res.stderr.strip()}",
                )

            commit_msg = log_res.stdout
            validation = parse_conventional_commit(commit_msg)
            if not validation.is_valid:
                return RuleResult(
                    rule_name=self.rule_name,
                    severity=AuditSeverity.CHANGES_REQUIRED,
                    message=f"Latest commit (HEAD) violates Conventional Commits: {'; '.join(validation.errors)}",
                    details={"errors": validation.errors, "raw_message": commit_msg.strip()},
                )

            header = validation.commit.header if validation.commit else "HEAD"
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.APPROVED,
                message=f"Latest commit conforms to Conventional Commits: '{header}'.",
                details={"header": header, "type": validation.commit.type if validation.commit else ""},
            )
        except Exception as e:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Failed to evaluate commit conventions: {e}",
            )


class ScopeAuditor:
    """Orchestrates rule evaluation and resolves final audit verdict."""

    def __init__(self, rules: Optional[List[Any]] = None):
        self.rules = rules or [
            GitHygieneRule(),
            TaskContractRule(),
            SyntaxCompilationRule(),
            SecretsBoundaryRule(),
            CommitConventionRule(),
        ]

    def run(self, repo_path: Path) -> AuditVerdict:
        results: List[RuleResult] = []
        max_severity = AuditSeverity.APPROVED

        for rule in self.rules:
            result = rule.evaluate(repo_path)
            results.append(result)
            if result.severity > max_severity:
                max_severity = result.severity

        return AuditVerdict(
            status=max_severity.label,
            exit_code=int(max_severity),
            results=results,
        )
