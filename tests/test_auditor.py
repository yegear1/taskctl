"""Hermetic unit tests for Scope Auditor rule-based policy engine."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

from taskctl.core.auditor import (
    AuditSeverity,
    GitHygieneRule,
    TaskContractRule,
    SyntaxCompilationRule,
    SecretsBoundaryRule,
    CommitConventionRule,
    ScopeAuditor,
)


class TestScopeAuditor(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_git_hygiene_rule_pass(self):
        rule = GitHygieneRule()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = rule.evaluate(self.repo_path)
            self.assertEqual(result.severity, AuditSeverity.APPROVED)
            self.assertEqual(result.exit_code, 0)

    def test_git_hygiene_rule_fail(self):
        rule = GitHygieneRule()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="file.py:10: trailing whitespace.\n")
            result = rule.evaluate(self.repo_path)
            self.assertEqual(result.severity, AuditSeverity.CHANGES_REQUIRED)
            self.assertEqual(result.exit_code, 1)

    def test_task_contract_rule_missing_file(self):
        rule = TaskContractRule()
        result = rule.evaluate(self.repo_path)
        self.assertEqual(result.severity, AuditSeverity.REJECTED)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Missing required contract file", result.message)

    def test_task_contract_rule_valid(self):
        agent_dir = self.repo_path / ".agent"
        agent_dir.mkdir(parents=True)
        task_file = agent_dir / "TASK.md"
        task_file.write_text(
            """# TASK.md
### 📌 Task [01.2]: Valid Title
- **Status:** RUNNING
### Acceptance Criteria
- [ ] Criterion 1
""",
            encoding="utf-8",
        )
        rule = TaskContractRule()
        result = rule.evaluate(self.repo_path)
        self.assertEqual(result.severity, AuditSeverity.APPROVED)
        self.assertEqual(result.exit_code, 0)

    def test_task_contract_rule_invalid_id(self):
        agent_dir = self.repo_path / ".agent"
        agent_dir.mkdir(parents=True)
        task_file = agent_dir / "TASK.md"
        task_file.write_text(
            """# TASK.md
### 📌 Task [bad_id]: Valid Title
- **Status:** RUNNING
""",
            encoding="utf-8",
        )
        rule = TaskContractRule()
        result = rule.evaluate(self.repo_path)
        self.assertEqual(result.severity, AuditSeverity.REJECTED)
        self.assertEqual(result.exit_code, 2)

    def test_task_contract_rule_invalid_status(self):
        agent_dir = self.repo_path / ".agent"
        agent_dir.mkdir(parents=True)
        task_file = agent_dir / "TASK.md"
        task_file.write_text(
            """# TASK.md
### 📌 Task [01.2]: Valid Title
- **Status:** INVALID_STATUS
""",
            encoding="utf-8",
        )
        rule = TaskContractRule()
        result = rule.evaluate(self.repo_path)
        self.assertEqual(result.severity, AuditSeverity.CHANGES_REQUIRED)
        self.assertEqual(result.exit_code, 1)

    def test_syntax_compilation_rule_clean(self):
        py_file = self.repo_path / "valid.py"
        py_file.write_text("def hello() -> str:\n    return 'world'\n", encoding="utf-8")
        rule = SyntaxCompilationRule()
        result = rule.evaluate(self.repo_path)
        self.assertEqual(result.severity, AuditSeverity.APPROVED)

    def test_syntax_compilation_rule_error(self):
        py_file = self.repo_path / "broken.py"
        py_file.write_text("def broken(:\n    pass\n", encoding="utf-8")
        rule = SyntaxCompilationRule()
        result = rule.evaluate(self.repo_path)
        self.assertEqual(result.severity, AuditSeverity.CHANGES_REQUIRED)
        self.assertEqual(result.exit_code, 1)

    def test_secrets_boundary_rule_clean(self):
        rule = SecretsBoundaryRule()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="src/main.py\nREADME.md\n.env.example\n")
            result = rule.evaluate(self.repo_path)
            self.assertEqual(result.severity, AuditSeverity.APPROVED)
            self.assertEqual(result.exit_code, 0)

    def test_secrets_boundary_rule_leaked_secret(self):
        rule = SecretsBoundaryRule()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="src/main.py\n.env\nid_rsa\n")
            result = rule.evaluate(self.repo_path)
            self.assertEqual(result.severity, AuditSeverity.REJECTED)
            self.assertEqual(result.exit_code, 2)
            self.assertIn("Security boundary violation", result.message)

    def test_commit_convention_rule_no_commits(self):
        rule = CommitConventionRule()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="fatal: ambiguous argument 'HEAD'")
            result = rule.evaluate(self.repo_path)
            self.assertEqual(result.severity, AuditSeverity.APPROVED)
            self.assertEqual(result.exit_code, 0)
            self.assertIn("skipped", result.message)

    def test_commit_convention_rule_valid_commit(self):
        rule = CommitConventionRule()
        with patch("subprocess.run") as mock_run:
            # First call for rev-parse (rc=0), second for git log
            mock_run.side_effect = [
                MagicMock(returncode=0),
                MagicMock(returncode=0, stdout="feat(core): implement conventional commits\n"),
            ]
            result = rule.evaluate(self.repo_path)
            self.assertEqual(result.severity, AuditSeverity.APPROVED)
            self.assertEqual(result.exit_code, 0)
            self.assertIn("conforms to Conventional Commits", result.message)

    def test_commit_convention_rule_invalid_commit(self):
        rule = CommitConventionRule()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),
                MagicMock(returncode=0, stdout="unconventional commit subject\n"),
            ]
            result = rule.evaluate(self.repo_path)
            self.assertEqual(result.severity, AuditSeverity.CHANGES_REQUIRED)
            self.assertEqual(result.exit_code, 1)
            self.assertIn("violates Conventional Commits", result.message)

    def test_scope_auditor_default_rules(self):
        auditor = ScopeAuditor()
        rule_names = [r.rule_name for r in auditor.rules]
        self.assertIn("commit-convention", rule_names)
        self.assertEqual(len(rule_names), 5)

    def test_scope_auditor_aggregate(self):
        mock_rule1 = MagicMock()
        mock_rule1.evaluate.return_value = MagicMock(severity=AuditSeverity.APPROVED, exit_code=0)

        mock_rule2 = MagicMock()
        mock_rule2.evaluate.return_value = MagicMock(severity=AuditSeverity.CHANGES_REQUIRED, exit_code=1)

        auditor = ScopeAuditor(rules=[mock_rule1, mock_rule2])
        verdict = auditor.run(self.repo_path)
        self.assertEqual(verdict.exit_code, 1)
        self.assertEqual(verdict.status, "CHANGES REQUIRED")
        self.assertFalse(verdict.is_approved)


if __name__ == "__main__":
    unittest.main()
