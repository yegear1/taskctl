"""Hermetic unit tests for Conventional Commits parser and policy engine."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from taskctl.core.commits import (
    parse_conventional_commit,
    strip_git_comments,
    ConventionalCommit,
    STANDARD_TYPES,
)
from taskctl.cli import cmd_lint_commit


class TestConventionalCommitsParser(unittest.TestCase):
    def test_simple_valid_feat(self):
        msg = "feat: implement conventional commits parser"
        res = parse_conventional_commit(msg)
        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.errors), 0)
        self.assertIsNotNone(res.commit)
        self.assertEqual(res.commit.type, "feat")
        self.assertIsNone(res.commit.scope)
        self.assertFalse(res.commit.is_breaking)
        self.assertEqual(res.commit.description, "implement conventional commits parser")
        self.assertEqual(res.commit.header, "feat: implement conventional commits parser")

    def test_valid_with_scope(self):
        msg = "fix(auditor): handle empty git repository gracefully"
        res = parse_conventional_commit(msg)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.commit.type, "fix")
        self.assertEqual(res.commit.scope, "auditor")
        self.assertFalse(res.commit.is_breaking)
        self.assertEqual(res.commit.description, "handle empty git repository gracefully")

    def test_valid_with_breaking_indicator(self):
        msg = "refactor(api)!: drop legacy v1 endpoints"
        res = parse_conventional_commit(msg)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.commit.type, "refactor")
        self.assertEqual(res.commit.scope, "api")
        self.assertTrue(res.commit.is_breaking)
        self.assertEqual(res.commit.header, "refactor(api)!: drop legacy v1 endpoints")

    def test_valid_without_scope_breaking(self):
        msg = "chore!: change configuration default format"
        res = parse_conventional_commit(msg)
        self.assertTrue(res.is_valid)
        self.assertTrue(res.commit.is_breaking)

    def test_valid_multiline_with_body_and_footers(self):
        msg = (
            "feat(telemetry): add vector direct sink\n"
            "\n"
            "This enables shipping lifecycle audit logs directly to Vector\n"
            "without intermediate syslog forwarding.\n"
            "\n"
            "Signed-off-by: Developer <dev@example.com>\n"
            "BREAKING CHANGE: telemetry payload structure changed"
        )
        res = parse_conventional_commit(msg)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.commit.type, "feat")
        self.assertEqual(res.commit.scope, "telemetry")
        self.assertTrue(res.commit.is_breaking)
        self.assertIn("This enables shipping", res.commit.body)
        self.assertEqual(len(res.commit.footers), 2)
        self.assertEqual(res.commit.footers[0]["token"], "Signed-off-by")
        self.assertEqual(res.commit.footers[1]["token"], "BREAKING CHANGE")

    def test_strip_git_comments(self):
        msg = (
            "docs(task): update task status\n"
            "# Please enter the commit message for your changes.\n"
            "# Lines starting with '#' will be ignored.\n"
        )
        res = parse_conventional_commit(msg)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.commit.type, "docs")
        self.assertEqual(res.commit.scope, "task")
        self.assertEqual(res.commit.description, "update task status")

    def test_all_standard_types_accepted(self):
        for c_type in STANDARD_TYPES:
            msg = f"{c_type}: test commit message for {c_type}"
            res = parse_conventional_commit(msg)
            self.assertTrue(res.is_valid, f"Type '{c_type}' should be valid.")

    def test_empty_message_rejected(self):
        res = parse_conventional_commit("   \n\n  ")
        self.assertFalse(res.is_valid)
        self.assertIn("Commit message is empty.", res.errors)

    def test_missing_colon_rejected(self):
        res = parse_conventional_commit("feat add new feature")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("missing a colon" in err for err in res.errors))

    def test_missing_space_after_colon_rejected(self):
        res = parse_conventional_commit("feat:add new feature")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("space after the colon" in err for err in res.errors))

    def test_uppercase_type_rejected(self):
        res = parse_conventional_commit("FEAT: add new feature")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("must be lowercase" in err for err in res.errors))

    def test_unknown_type_rejected(self):
        res = parse_conventional_commit("customtype: add new feature")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("not recognized" in err for err in res.errors))

    def test_header_too_long_rejected(self):
        long_subject = "a" * 105
        res = parse_conventional_commit(f"feat: {long_subject}")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("exceeds maximum length" in err for err in res.errors))

    def test_missing_blank_line_before_body_rejected(self):
        msg = "feat: header line\nSecond line without empty line separator"
        res = parse_conventional_commit(msg)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("blank line is required" in err for err in res.errors))


class TestLintCommitCLI(unittest.TestCase):
    @patch("taskctl.cli.get_telemetry_emitter")
    def test_cmd_lint_commit_valid(self, mock_emitter):
        mock_emitter.return_value.emit_lifecycle_event = MagicMock()
        exit_code = cmd_lint_commit("feat(core): implement commit linter")
        self.assertEqual(exit_code, 0)

    @patch("taskctl.cli.get_telemetry_emitter")
    def test_cmd_lint_commit_invalid(self, mock_emitter):
        mock_emitter.return_value.emit_lifecycle_event = MagicMock()
        exit_code = cmd_lint_commit("invalid commit message")
        self.assertEqual(exit_code, 1)

    @patch("taskctl.cli.get_telemetry_emitter")
    def test_cmd_lint_commit_file(self, mock_emitter):
        mock_emitter.return_value.emit_lifecycle_event = MagicMock()
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            f.write("fix(cli): correct commit linting exit code\n\nResolves issue with exit codes.")
            file_path = f.name

        try:
            exit_code = cmd_lint_commit(file_path=file_path)
            self.assertEqual(exit_code, 0)
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    def test_cmd_lint_commit_missing_file(self):
        exit_code = cmd_lint_commit(file_path="/path/that/does/not/exist/ever")
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
