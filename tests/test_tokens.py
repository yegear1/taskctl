"""Unit tests for taskctl.telemetry.tokens module."""

import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from taskctl.telemetry.tokens import (
    _chars_to_tokens,
    detect_role_from_text,
    parse_antigravity_transcript,
    parse_scrollback_terminal,
    collect_token_telemetry,
    save_token_telemetry_cache,
    load_token_telemetry_cache,
    SessionTokenRecord,
    RoleTokenAggregation,
)
from taskctl.telemetry.daemon import TelemetryDaemon
from taskctl.cli import cmd_tokens


class TestTokensTelemetry(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="taskctl_test_tokens_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_chars_to_tokens(self):
        self.assertEqual(_chars_to_tokens(""), 0)
        self.assertEqual(_chars_to_tokens("1234"), 1)
        self.assertEqual(_chars_to_tokens("12345678"), 2)

    def test_detect_role_from_text(self):
        self.assertEqual(detect_role_from_text("Role: Planner requirements"), "Planner")
        self.assertEqual(detect_role_from_text("I am a software developer"), "Developer")
        self.assertEqual(detect_role_from_text("Running taskctl audit report"), "Scope Auditor")
        self.assertEqual(detect_role_from_text("Security & vulnerability auditor check"), "Security Auditor")
        self.assertEqual(detect_role_from_text("aether-guard sentinel shield"), "Sentinel")
        self.assertEqual(detect_role_from_text("Orchestrator maestro swarm"), "Orchestrator")
        self.assertIsNone(detect_role_from_text("Just regular text"))

    def test_parse_antigravity_transcript(self):
        brain_dir = os.path.join(self.test_dir, "AntigravityProfiles", "luisfmb", ".gemini", "antigravity", "brain", "conv-123", ".system_generated", "logs")
        os.makedirs(brain_dir, exist_ok=True)
        transcript_path = os.path.join(brain_dir, "transcript.jsonl")

        steps = [
            {
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "created_at": "2026-10-07T01:00:00Z",
                "content": "### Role: Scope Auditor\nPlease audit the pull request.",
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-10-07T01:00:05Z",
                "content": "I am reviewing the changes.",
                "thinking": "Extended thinking block with internal reasoning.",
                "tool_calls": [
                    {"name": "view_file", "args": {"path": "/tmp/test.py"}}
                ],
            },
            {
                "step_index": 2,
                "source": "SYSTEM",
                "type": "GENERIC",
                "created_at": "2026-10-07T01:00:10Z",
                "content": "File contents here...",
            },
        ]

        with open(transcript_path, "w", encoding="utf-8") as f:
            for s in steps:
                f.write(json.dumps(s) + "\n")

        rec = parse_antigravity_transcript(transcript_path, default_profile="luisfmb")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.session_id, "conv-123")
        self.assertEqual(rec.profile, "luisfmb")
        self.assertEqual(rec.role, "Scope Auditor")
        self.assertEqual(rec.agent_type, "agy-cli")
        self.assertEqual(rec.turns, 1)
        self.assertEqual(rec.tool_calls, 1)
        self.assertGreater(rec.prompt_tokens, 0)
        self.assertGreater(rec.completion_tokens, 0)
        self.assertGreater(rec.thinking_tokens, 0)
        self.assertEqual(rec.total_tokens, rec.prompt_tokens + rec.completion_tokens + rec.thinking_tokens)
        self.assertEqual(rec.first_active, "2026-10-07T01:00:00Z")
        self.assertEqual(rec.last_active, "2026-10-07T01:00:10Z")

    def test_parse_scrollback_terminal(self):
        term_file = os.path.join(self.test_dir, "term-abc.scrollback")
        with open(term_file, "w", encoding="utf-8") as f:
            f.write("\x1b[32mPlanner Agent Output\x1b[0m\nLine 2\n")

        rec = parse_scrollback_terminal(term_file, profile="yegear", role="Planner")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.session_id, "term-abc")
        self.assertEqual(rec.profile, "yegear")
        self.assertEqual(rec.role, "Planner")
        self.assertGreater(rec.total_tokens, 0)

    def test_collect_token_telemetry_and_cmd_tokens(self):
        # Create mock profile with transcript
        brain_dir = os.path.join(self.test_dir, "AntigravityProfiles", "testuser", ".gemini", "antigravity", "brain", "mock-sess", ".system_generated", "logs")
        os.makedirs(brain_dir, exist_ok=True)
        transcript_path = os.path.join(brain_dir, "transcript.jsonl")

        steps = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-07T02:00:00Z", "content": "Role: Developer\nBuild feature."},
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": "2026-10-07T02:00:05Z", "content": "Feature built successfully."},
        ]
        with open(transcript_path, "w", encoding="utf-8") as f:
            for s in steps:
                f.write(json.dumps(s) + "\n")

        with patch("os.path.expanduser", return_value=self.test_dir), \
             patch.dict("os.environ", {"REAL_HOME": self.test_dir}):
            sessions, aggs = collect_token_telemetry(profile_filter="testuser")
            self.assertEqual(len(sessions), 1)
            self.assertEqual(len(aggs), 1)
            self.assertEqual(aggs[0].profile, "testuser")
            self.assertEqual(aggs[0].role, "Developer")
            self.assertGreater(aggs[0].total_tokens, 0)

            # Test cmd_tokens with table output
            out = io.StringIO()
            with patch("sys.stdout", out):
                code = cmd_tokens(profile="testuser")
            self.assertEqual(code, 0)
            self.assertIn("MULTI-AGENT TOKEN CONSUMPTION TELEMETRY", out.getvalue())
            self.assertIn("testuser", out.getvalue())
            self.assertIn("Developer", out.getvalue())

            # Test cmd_tokens with --json output
            json_out = io.StringIO()
            with patch("sys.stdout", json_out):
                code = cmd_tokens(profile="testuser", json_output=True)
            self.assertEqual(code, 0)
            data = json.loads(json_out.getvalue())
            self.assertIn("summary", data)
            self.assertIn("aggregations", data)
            self.assertEqual(data["aggregations"][0]["profile"], "testuser")

    def test_save_and_load_cache(self):
        cache_file = os.path.join(self.test_dir, ".maestri", "usage", "token-telemetry.json")
        sessions = [
            SessionTokenRecord(
                session_id="s1",
                profile="luisfmb",
                role="Developer",
                agent_type="agy-cli",
                prompt_tokens=100,
                completion_tokens=200,
                thinking_tokens=0,
                total_tokens=300,
                turns=2,
                first_active="2026-10-07T00:00:00Z",
                last_active="2026-10-07T00:05:00Z",
            )
        ]
        aggs = [
            RoleTokenAggregation(
                profile="luisfmb",
                role="Developer",
                agent_type="agy-cli",
                prompt_tokens=100,
                completion_tokens=200,
                thinking_tokens=0,
                total_tokens=300,
                sessions_count=1,
                turns=2,
                last_active="2026-10-07T00:05:00Z",
            )
        ]
        save_token_telemetry_cache(aggregations=aggs, sessions=sessions, cache_path=cache_file)
        self.assertTrue(os.path.exists(cache_file))

        loaded = load_token_telemetry_cache(cache_path=cache_file)
        self.assertIsNotNone(loaded)
        self.assertIn("sessions", loaded)
        self.assertIn("aggregations", loaded)
        self.assertEqual(len(loaded["sessions"]), 1)
        self.assertEqual(len(loaded["aggregations"]), 1)
        self.assertEqual(loaded["sessions"][0]["session_id"], "s1")
        self.assertEqual(loaded["aggregations"][0]["profile"], "luisfmb")
        self.assertEqual(loaded["aggregations"][0]["agent_type"], "agy-cli")

    def test_daemon_refresh_tokens(self):
        daemon = TelemetryDaemon(watch_paths=[self.test_dir])
        with patch("taskctl.telemetry.tokens.collect_token_telemetry") as mock_collect:
            mock_collect.return_value = ([], [])
            res = daemon.refresh_tokens()
            self.assertTrue(mock_collect.called)
            self.assertEqual(res, {"total_tokens": 0, "aggregations": 0})


if __name__ == "__main__":
    unittest.main()
