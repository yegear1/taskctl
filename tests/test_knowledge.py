"""Hermetic unit tests for Knowledge Cards Engine (SQLite FTS5, BM25, and reflex)."""

import io
import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from taskctl.core.knowledge import (
    KnowledgeCard,
    KnowledgeEngine,
    parse_yaml_frontmatter,
    parse_knowledge_card,
)
from taskctl.cli import cmd_recall, cmd_reflex


class TestKnowledgeCardParsing(unittest.TestCase):
    """Test parsing of Markdown Knowledge Cards with YAML frontmatter."""

    def test_parse_frontmatter_and_markdown_sections(self):
        content = """---
id: K-001
title: SQLite FTS5 Lock Contention
type: gotcha
components:
  - core
  - database
error_keywords:
  - "database is locked"
  - OperationalError
platforms:
  - linux
  - macos
invariants_affected:
  - INV-01
---

# Alternative Title Ignored If In Frontmatter

## Problem
Concurrent write transactions to SQLite FTS5 table can raise OperationalError: database is locked.

## Solution
Always use WAL mode `PRAGMA journal_mode=WAL;` and configure `timeout=10.0` on connection.

## Never Do
Never open unbounded write transactions across threads or processes without busy handler.
"""
        card = parse_knowledge_card(content, filepath="/path/to/K-001.md", mtime=12345.0)

        self.assertEqual(card.id, "K-001")
        self.assertEqual(card.title, "SQLite FTS5 Lock Contention")
        self.assertEqual(card.type, "gotcha")
        self.assertEqual(card.components, ["core", "database"])
        self.assertEqual(card.error_keywords, ["database is locked", "OperationalError"])
        self.assertEqual(card.platforms, ["linux", "macos"])
        self.assertEqual(card.invariants_affected, ["INV-01"])
        self.assertIn("Concurrent write transactions", card.problem)
        self.assertIn("Always use WAL mode", card.solution)
        self.assertIn("Never open unbounded write transactions", card.never_do)
        self.assertEqual(card.filepath, "/path/to/K-001.md")
        self.assertEqual(card.mtime, 12345.0)

        d = card.to_dict()
        self.assertEqual(d["id"], "K-001")
        self.assertEqual(d["type"], "gotcha")

    def test_parse_inline_yaml_lists_and_frontmatter_fields(self):
        content = """---
id: K-002
title: Webhook Timeout Isolation
type: rule
components: [webhooks, telemetry]
error_keywords: ["webhook timeout", "ConnectionRefusedError"]
platforms: [linux]
invariants_affected: [INV-02]
problem: Webhook dispatchers must never block commit execution.
solution: Use non-blocking background threads with strict 2-second timeout.
never_do: Do not call external HTTP sync in CLI main thread.
---

Body text that should be ignored since problem/solution are in frontmatter.
"""
        card = parse_knowledge_card(content, filepath="/path/to/K-002.md")
        self.assertEqual(card.id, "K-002")
        self.assertEqual(card.title, "Webhook Timeout Isolation")
        self.assertEqual(card.type, "rule")
        self.assertEqual(card.components, ["webhooks", "telemetry"])
        self.assertEqual(card.error_keywords, ["webhook timeout", "ConnectionRefusedError"])
        self.assertEqual(card.platforms, ["linux"])
        self.assertEqual(card.invariants_affected, ["INV-02"])
        self.assertEqual(card.problem, "Webhook dispatchers must never block commit execution.")
        self.assertEqual(card.solution, "Use non-blocking background threads with strict 2-second timeout.")
        self.assertEqual(card.never_do, "Do not call external HTTP sync in CLI main thread.")

    def test_parse_card_with_fallback_defaults(self):
        content = """# Inferred H1 Title

Just some raw notes on how to fix git merge conflicts.
"""
        card = parse_knowledge_card(content, filepath="/path/to/git-merge-gotcha.md")
        self.assertEqual(card.id, "git-merge-gotcha")
        self.assertEqual(card.title, "Inferred H1 Title")
        self.assertEqual(card.type, "gotcha")
        self.assertEqual(card.components, [])
        self.assertIn("Just some raw notes", card.problem)


class TestKnowledgeEngineFTS5(unittest.TestCase):
    """Test SQLite FTS5 indexing, BM25 ranking, and incremental mtime sync."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="taskctl_test_kengine_")
        self.knowledge_dir = os.path.join(self.temp_dir, ".agent", "knowledge")
        self.cache_dir = os.path.join(self.temp_dir, ".agent", ".cache")
        self.db_path = os.path.join(self.cache_dir, "knowledge.db")
        os.makedirs(self.knowledge_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_card(self, filename: str, content: str):
        path = os.path.join(self.knowledge_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_sync_and_bm25_search(self):
        self._create_sample_card(
            "k-001.md",
            """---
id: K-001
title: SQLite FTS5 Lock Contention
type: gotcha
components: [core, database]
error_keywords: ["database is locked", "OperationalError"]
---
## Problem
Database locks during concurrent full-text indexing operations.
## Solution
Configure WAL mode and busy timeout handler.
## Never Do
Do not use exclusive lock mode without retry loops.
""",
        )

        self._create_sample_card(
            "k-002.md",
            """---
id: K-002
title: Docker Socket Permission Denied
type: incident
components: [devops, docker]
error_keywords: ["permission denied", "docker.sock"]
---
## Problem
Docker daemon socket /var/run/docker.sock inaccessible to non-root user.
## Solution
Add user to docker group or configure non-root rootless docker daemon.
## Never Do
Do not chmod 777 /var/run/docker.sock in shared host.
""",
        )

        engine = KnowledgeEngine(
            repo_path=self.temp_dir,
            db_path=self.db_path,
            knowledge_dir=self.knowledge_dir,
        )

        total = engine.sync()
        self.assertEqual(total, 2)
        self.assertTrue(os.path.exists(self.db_path))

        # Search for "database lock" (tests Porter stemmer: lock matches locks / locked)
        results = engine.search("database lock")
        self.assertGreaterEqual(len(results), 1)
        top_card, score = results[0]
        self.assertEqual(top_card.id, "K-001")
        self.assertGreater(score, 0.0)

        # Search for docker
        docker_res = engine.search("docker socket")
        self.assertGreaterEqual(len(docker_res), 1)
        self.assertEqual(docker_res[0][0].id, "K-002")

        # Component filtering
        filtered = engine.search("lock", component="devops")
        self.assertEqual(len(filtered), 0)

        filtered_db = engine.search("lock", component="database")
        self.assertEqual(len(filtered_db), 1)
        self.assertEqual(filtered_db[0][0].id, "K-001")

        # Wildcard search returns all
        all_cards = engine.search("*")
        self.assertEqual(len(all_cards), 2)

        engine.close()

    def test_incremental_sync_mtime(self):
        p1 = self._create_sample_card(
            "k-001.md",
            """---
id: K-001
title: Initial Version
type: gotcha
---
## Problem
Initial problem description.
## Solution
Initial solution.
""",
        )

        engine = KnowledgeEngine(
            repo_path=self.temp_dir,
            db_path=self.db_path,
            knowledge_dir=self.knowledge_dir,
        )
        self.assertEqual(engine.sync(), 1)

        # Ensure subsequent sync without changes returns immediately with 1
        self.assertEqual(engine.sync(), 1)

        # Update card content and mtime
        time.sleep(0.05)
        with open(p1, "w", encoding="utf-8") as f:
            f.write(
                """---
id: K-001
title: Updated Version Title
type: pattern
---
## Problem
Updated problem.
## Solution
Updated solution.
"""
            )
        # Force mtime bump
        new_mtime = os.path.getmtime(p1) + 2.0
        os.utime(p1, (new_mtime, new_mtime))

        self.assertEqual(engine.sync(), 1)
        results = engine.search("Updated")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0].title, "Updated Version Title")

        # Prune deleted file
        os.remove(p1)
        self.assertEqual(engine.sync(), 0)
        self.assertEqual(len(engine.search("*")), 0)

        engine.close()

    def test_graceful_fail_open_when_knowledge_dir_missing(self):
        # Point to a nonexistent directory
        missing_dir = os.path.join(self.temp_dir, "nonexistent", "knowledge")
        engine = KnowledgeEngine(
            repo_path=self.temp_dir,
            db_path=self.db_path,
            knowledge_dir=missing_dir,
        )

        # sync, search, reflex should gracefully return empty results
        self.assertEqual(engine.sync(), 0)
        self.assertEqual(engine.search("anything"), [])
        self.assertEqual(engine.reflex("error trace"), [])
        engine.close()


class TestErrorReflex(unittest.TestCase):
    """Test error signature matching and stack trace reflex detection."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="taskctl_test_reflex_")
        self.knowledge_dir = os.path.join(self.temp_dir, ".agent", "knowledge")
        self.cache_dir = os.path.join(self.temp_dir, ".agent", ".cache")
        self.db_path = os.path.join(self.cache_dir, "knowledge.db")
        os.makedirs(self.knowledge_dir, exist_ok=True)

        card_path = os.path.join(self.knowledge_dir, "k-lock.md")
        with open(card_path, "w", encoding="utf-8") as f:
            f.write(
                """---
id: K-SQLITE-LOCK
title: SQLite Database Is Locked OperationalError
type: gotcha
components: [database, fts5]
error_keywords:
  - "database is locked"
  - "sqlite3.OperationalError"
invariants_affected:
  - INV-01
---
## Problem
Concurrent writes or missing busy handler causing database is locked errors.
## Solution
Execute `PRAGMA journal_mode=WAL;` and pass `timeout=10.0` when opening connection.
## Never Do
Do not keep long-lived write transactions open in daemon threads.
"""
            )

        card_perm = os.path.join(self.knowledge_dir, "k-perm.md")
        with open(card_perm, "w", encoding="utf-8") as f:
            f.write(
                """---
id: K-PERM-DENIED
title: UNIX Socket Permission Denied
type: incident
components: [ipc, daemon]
error_keywords:
  - "Permission denied"
  - "PermissionError"
---
## Problem
Unable to bind or connect to IPC socket due to incorrect file permissions.
## Solution
Verify socket ownership and chmod socket file or parent directory.
## Never Do
Do not run entire CLI as root to bypass permission errors.
"""
            )

        self.engine = KnowledgeEngine(
            repo_path=self.temp_dir,
            db_path=self.db_path,
            knowledge_dir=self.knowledge_dir,
        )
        self.engine.sync()

    def tearDown(self):
        self.engine.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_reflex_matches_exact_keywords_and_exceptions(self):
        stderr = """Traceback (most recent call last):
  File "taskctl/core/knowledge.py", line 120, in sync
    conn.execute("INSERT INTO knowledge_fts VALUES (...)")
sqlite3.OperationalError: database is locked
"""
        matches = self.engine.reflex(stderr)
        self.assertGreaterEqual(len(matches), 1)
        top_card, score, matched_kw = matches[0]
        self.assertEqual(top_card.id, "K-SQLITE-LOCK")
        self.assertIn("database is locked", matched_kw)
        self.assertIn("sqlite3.OperationalError", matched_kw)
        self.assertGreaterEqual(score, 20.0)

    def test_reflex_matches_permission_error(self):
        stderr = "PermissionError: [Errno 13] Permission denied: '/tmp/taskctl.sock'"
        matches = self.engine.reflex(stderr)
        self.assertGreaterEqual(len(matches), 1)
        top_card, score, matched_kw = matches[0]
        self.assertEqual(top_card.id, "K-PERM-DENIED")
        self.assertIn("Permission denied", matched_kw)

    def test_reflex_empty_or_no_match(self):
        self.assertEqual(self.engine.reflex(""), [])
        self.assertEqual(self.engine.reflex("   \n  "), [])
        unmatched = self.engine.reflex("Everything is totally fine with zero errors")
        self.assertEqual(len(unmatched), 0)


class TestKnowledgeCLICommands(unittest.TestCase):
    """Test taskctl recall and taskctl reflex CLI subcommands."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="taskctl_test_kcli_")
        self.agent_dir = os.path.join(self.temp_dir, ".agent")
        self.knowledge_dir = os.path.join(self.agent_dir, "knowledge")
        os.makedirs(self.knowledge_dir, exist_ok=True)

        # Write dummy TASK.md so resolve_repo_path recognizes it
        task_md = os.path.join(self.agent_dir, "TASK.md")
        with open(task_md, "w", encoding="utf-8") as f:
            f.write("# TASK.md\n## Active Task\n*(No active task)*\n")

        card_path = os.path.join(self.knowledge_dir, "k-001.md")
        with open(card_path, "w", encoding="utf-8") as f:
            f.write(
                """---
id: K-001
title: SQLite Busy Timeout Pattern
type: solution
components: [core, sqlite]
error_keywords: ["busy timeout", "database locked"]
---
## Problem
Connection fails when multiple agents write simultaneously.
## Solution
Use sqlite3.connect with timeout=10.0 and WAL journal mode.
## Never Do
Never disable WAL mode.
"""
            )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cmd_recall_text_and_json(self):
        # Human-readable stdout
        f = io.StringIO()
        with redirect_stdout(f):
            code = cmd_recall("sqlite", repo=self.temp_dir)
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("KNOWLEDGE BASE RECALL", output)
        self.assertIn("[K-001]", output)
        self.assertIn("SQLite Busy Timeout Pattern", output)

        # Detailed stdout
        f_det = io.StringIO()
        with redirect_stdout(f_det):
            code_det = cmd_recall("sqlite", detailed=True, repo=self.temp_dir)
        self.assertEqual(code_det, 0)
        det_output = f_det.getvalue()
        self.assertIn("📌 Problem:", det_output)
        self.assertIn("💡 Solution:", det_output)
        self.assertIn("⚠️  Never Do:", det_output)

        # JSON output
        f_json = io.StringIO()
        with redirect_stdout(f_json):
            code_json = cmd_recall("sqlite", json_output=True, repo=self.temp_dir)
        self.assertEqual(code_json, 0)
        parsed = json.loads(f_json.getvalue())
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["id"], "K-001")
        self.assertEqual(parsed[0]["type"], "solution")

    def test_cmd_reflex_text_and_json(self):
        stderr_log = "sqlite3.OperationalError: database locked after 5000ms"

        # Text output
        f = io.StringIO()
        with redirect_stdout(f):
            code = cmd_reflex(stderr_content=stderr_log, repo=self.temp_dir)
        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("KNOWLEDGE ERROR REFLEX EVALUATOR", output)
        self.assertIn("[K-001]", output)
        self.assertIn("database locked", output)

        # JSON output
        f_json = io.StringIO()
        with redirect_stdout(f_json):
            code_json = cmd_reflex(stderr_content=stderr_log, json_output=True, repo=self.temp_dir)
        self.assertEqual(code_json, 0)
        parsed = json.loads(f_json.getvalue())
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["id"], "K-001")
        self.assertIn("database locked", parsed[0]["matched_keywords"])

    def test_cmd_reflex_from_file(self):
        err_file = os.path.join(self.temp_dir, "error.log")
        with open(err_file, "w", encoding="utf-8") as f:
            f.write("OperationalError: database locked")

        f = io.StringIO()
        with redirect_stdout(f):
            code = cmd_reflex(file_path=err_file, json_output=True, repo=self.temp_dir)
        self.assertEqual(code, 0)
        parsed = json.loads(f.getvalue())
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["id"], "K-001")


if __name__ == "__main__":
    unittest.main()
