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
    LocalHeuristicScopeRule,
    HybridScopeRule,
    ScopeAuditor,
    parse_systems_involved,
    is_file_in_scope,
    parse_agent_verdict,
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

    def test_parse_systems_involved(self):
        self.assertEqual(
            parse_systems_involved("[taskctl/core/auditor.py, tests/test_auditor.py]"),
            ["taskctl/core/auditor.py", "tests/test_auditor.py"],
        )
        self.assertEqual(parse_systems_involved("[]"), [])
        self.assertEqual(parse_systems_involved(""), [])
        self.assertEqual(parse_systems_involved("taskctl/cli.py"), ["taskctl/cli.py"])

    def test_is_file_in_scope(self):
        declared = ["taskctl/core/auditor.py", "tests/"]
        # Governance files always in scope
        self.assertTrue(is_file_in_scope(".agent/TASK.md", declared))
        self.assertTrue(is_file_in_scope(".agent/NOTES.md", declared))
        self.assertTrue(is_file_in_scope("AGENTS.md", declared))
        self.assertTrue(is_file_in_scope("README.md", declared))

        # Explicit matches
        self.assertTrue(is_file_in_scope("taskctl/core/auditor.py", declared))
        self.assertTrue(is_file_in_scope("tests/test_auditor.py", declared))

        # Out-of-scope files
        self.assertFalse(is_file_in_scope("taskctl/providers/multigravity.py", declared))
        self.assertFalse(is_file_in_scope("unrelated/secret.txt", declared))

        # Wildcard matches everything
        self.assertTrue(is_file_in_scope("anything.py", ["*"]))

    def test_local_heuristic_scope_rule_clean(self):
        rule = LocalHeuristicScopeRule()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            res = rule.evaluate(self.repo_path)
            self.assertEqual(res.severity, AuditSeverity.APPROVED)
            self.assertEqual(res.exit_code, 0)
            self.assertIn("clean", res.message)

    def test_local_heuristic_scope_rule_matching(self):
        agent_dir = self.repo_path / ".agent"
        agent_dir.mkdir(parents=True)
        task_file = agent_dir / "TASK.md"
        task_file.write_text(
            """# TASK.md
### 📌 Task [03.3]: Test
- **Systems Involved:** [taskctl/core/auditor.py, tests/test_auditor.py]
- **Status:** RUNNING
""",
            encoding="utf-8",
        )
        rule = LocalHeuristicScopeRule()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=" M taskctl/core/auditor.py\n?? tests/test_auditor.py\n",
            )
            res = rule.evaluate(self.repo_path)
            self.assertEqual(res.severity, AuditSeverity.APPROVED)
            self.assertIn("all modified files (2) conform", res.message)

    def test_local_heuristic_scope_rule_out_of_scope(self):
        agent_dir = self.repo_path / ".agent"
        agent_dir.mkdir(parents=True)
        task_file = agent_dir / "TASK.md"
        task_file.write_text(
            """# TASK.md
### 📌 Task [03.3]: Test
- **Systems Involved:** [taskctl/core/auditor.py]
- **Status:** RUNNING
""",
            encoding="utf-8",
        )
        rule = LocalHeuristicScopeRule()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=" M taskctl/core/auditor.py\n M taskctl/unrelated.py\n",
            )
            res = rule.evaluate(self.repo_path)
            self.assertEqual(res.severity, AuditSeverity.CHANGES_REQUIRED)
            self.assertEqual(res.exit_code, 1)
            self.assertIn("outside declared Systems Involved", res.message)
            self.assertIn("taskctl/unrelated.py", str(res.details.get("out_of_scope")))

    def test_parse_agent_verdict(self):
        # Strict format
        v1 = parse_agent_verdict("VERDICT: APPROVED\nREASON: All tests passing cleanly.")
        self.assertIsNotNone(v1)
        self.assertEqual(v1[0], AuditSeverity.APPROVED)
        self.assertIn("All tests passing cleanly", v1[1])

        v2 = parse_agent_verdict("VERDICT: CHANGES REQUIRED\nREASON: Missing unit tests.")
        self.assertIsNotNone(v2)
        self.assertEqual(v2[0], AuditSeverity.CHANGES_REQUIRED)
        self.assertIn("Missing unit tests", v2[1])

        v3 = parse_agent_verdict("VERDICT: REJECTED\nREASON: Breaking contract change.")
        self.assertIsNotNone(v3)
        self.assertEqual(v3[0], AuditSeverity.REJECTED)
        self.assertIn("Breaking contract change", v3[1])

        # Freeform keyword fallback
        v4 = parse_agent_verdict("I have reviewed the code. Everything is APPROVED.")
        self.assertIsNotNone(v4)
        self.assertEqual(v4[0], AuditSeverity.APPROVED)

        # Unparseable
        self.assertIsNone(parse_agent_verdict("Random text with no keyword."))
        self.assertIsNone(parse_agent_verdict(""))

    def test_hybrid_scope_rule_agent_approved(self):
        rule = HybridScopeRule()
        with patch("taskctl.providers.maestri.ask_agent") as mock_ask:
            mock_ask.return_value = "VERDICT: APPROVED\nREASON: Semantic review passed without scope drift."
            res = rule.evaluate(self.repo_path)
            self.assertEqual(res.severity, AuditSeverity.APPROVED)
            self.assertFalse(res.details.get("fallback", False))
            self.assertTrue(res.details.get("delegated"))
            self.assertIn("Auditor", res.rule_name)

    def test_hybrid_scope_rule_agent_changes_required(self):
        rule = HybridScopeRule()
        with patch("taskctl.providers.maestri.ask_agent") as mock_ask:
            mock_ask.return_value = "VERDICT: CHANGES REQUIRED\nREASON: Undeclared file edited."
            res = rule.evaluate(self.repo_path)
            self.assertEqual(res.severity, AuditSeverity.CHANGES_REQUIRED)
            self.assertFalse(res.details.get("fallback", False))
            self.assertTrue(res.details.get("delegated"))

    def test_hybrid_scope_rule_fallback_when_offline(self):
        rule = HybridScopeRule()
        with patch("taskctl.providers.maestri.ask_agent", return_value=None):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="")
                res = rule.evaluate(self.repo_path)
                self.assertEqual(res.severity, AuditSeverity.APPROVED)
                self.assertTrue(res.details.get("fallback"))
                self.assertIn("fell back to local heuristic scope audit", res.message)

    def test_hybrid_scope_rule_with_custom_agent_name(self):
        rule = HybridScopeRule(agent_name="CustomScopeAuditor")
        with patch("taskctl.providers.maestri.ask_agent") as mock_ask:
            mock_ask.return_value = "VERDICT: APPROVED\nREASON: Custom agent approved."
            res = rule.evaluate(self.repo_path)
            self.assertEqual(res.severity, AuditSeverity.APPROVED)
            mock_ask.assert_called_once()
            self.assertEqual(mock_ask.call_args[0][0], "CustomScopeAuditor")

    def test_scope_auditor_hybrid_mode(self):
        auditor = ScopeAuditor(hybrid=True)
        self.assertTrue(auditor.hybrid)

        def fake_run(cmd, *args, **kwargs):
            if "log" in cmd:
                return MagicMock(returncode=0, stdout="feat(core): valid commit\n")
            return MagicMock(returncode=0, stdout="")

        with patch("taskctl.providers.maestri.ask_agent") as mock_ask:
            mock_ask.return_value = "VERDICT: APPROVED\nREASON: All changes approved."
            with patch("subprocess.run", side_effect=fake_run):
                # Write minimal TASK.md so TaskContractRule passes
                agent_dir = self.repo_path / ".agent"
                agent_dir.mkdir(parents=True)
                task_file = agent_dir / "TASK.md"
                task_file.write_text(
                    """# TASK.md
### 📌 Task [03.3]: Valid
- **Status:** RUNNING
""",
                    encoding="utf-8",
                )
                verdict = auditor.run(self.repo_path)
                self.assertEqual(verdict.exit_code, 0)
                self.assertTrue(verdict.is_approved)
                rule_names = [r.rule_name for r in verdict.results]
                self.assertTrue(any("canvas-agent-semantic" in name for name in rule_names))

    def test_scope_auditor_hybrid_mode_skips_when_hard_rejection(self):
        auditor = ScopeAuditor(hybrid=True)
        # Without TASK.md, TaskContractRule causes REJECTED
        with patch("taskctl.providers.maestri.ask_agent") as mock_ask:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="")
                verdict = auditor.run(self.repo_path)
                self.assertEqual(verdict.exit_code, 2)
                self.assertEqual(verdict.status, "REJECTED")
                # ask_agent should NOT have been called due to hard local rejection
                mock_ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
