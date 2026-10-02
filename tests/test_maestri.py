import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from taskctl.providers.maestri import (
    resolve_maestri_cli,
    resolve_maestri_socket,
    run_maestri_cli,
    strip_note_line_numbers,
    MaestriIPCClient,
    sync_task_cockpit_note,
    pull_task_cockpit_note,
    send_canvas_notification,
    create_workspace_canvas,
    ask_agent,
)
from taskctl.cli import cmd_ws, cmd_plan, cmd_sync, cmd_notify


class TestMaestriResolvers(unittest.TestCase):
    def test_resolve_maestri_cli_env(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"#!/bin/sh\nexit 0\n")
            temp_cli = f.name
        os.chmod(temp_cli, 0o755)

        try:
            with patch.dict(os.environ, {"MAESTRI_CLI": temp_cli}):
                self.assertEqual(resolve_maestri_cli(), temp_cli)
        finally:
            os.remove(temp_cli)

    def test_resolve_maestri_cli_missing(self):
        with patch.dict(os.environ, {"MAESTRI_CLI": "/nonexistent/maestri"}, clear=True):
            with patch("shutil.which", return_value=None):
                with patch("os.path.isfile", return_value=False):
                    self.assertIsNone(resolve_maestri_cli())

    def test_resolve_maestri_socket_env(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_sock = f.name

        try:
            with patch.dict(os.environ, {"MAESTRI_SOCKET_PATH": temp_sock}):
                self.assertEqual(resolve_maestri_socket(), temp_sock)

            with patch.dict(os.environ, {"MAESTRI_SOCKET": temp_sock}, clear=True):
                self.assertEqual(resolve_maestri_socket(), temp_sock)
        finally:
            os.remove(temp_sock)

    def test_resolve_maestri_socket_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.path.exists", return_value=False):
                with patch("glob.glob", return_value=[]):
                    self.assertIsNone(resolve_maestri_socket())


class TestMaestriIPCClient(unittest.TestCase):
    def test_ipc_unavailable(self):
        client = MaestriIPCClient(socket_path="/nonexistent.sock")
        self.assertFalse(client.is_available())
        self.assertIsNone(client.send_request("status"))

    @patch("socket.socket")
    def test_ipc_send_request_success(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        resp_payload = {"jsonrpc": "2.0", "id": 1, "result": {"status": "ok", "output": "Done"}}
        mock_sock.recv.side_effect = [json.dumps(resp_payload).encode("utf-8") + b"\n", b""]

        with tempfile.NamedTemporaryFile(delete=False) as f:
            sock_path = f.name

        try:
            client = MaestriIPCClient(socket_path=sock_path)
            res = client.send_request("test_method", {"param": 1})
            self.assertIsNotNone(res)
            self.assertEqual(res["result"]["status"], "ok")
            self.assertTrue(mock_sock.connect.called)
            self.assertTrue(mock_sock.sendall.called)
        finally:
            os.remove(sock_path)

    @patch("socket.socket")
    def test_ipc_send_request_error(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = socket.error("Connection refused")
        mock_socket_cls.return_value = mock_sock

        with tempfile.NamedTemporaryFile(delete=False) as f:
            sock_path = f.name

        try:
            client = MaestriIPCClient(socket_path=sock_path)
            res = client.send_request("test_method")
            self.assertIsNone(res)
        finally:
            os.remove(sock_path)


class TestStripNoteLineNumbers(unittest.TestCase):
    def test_strip_numbered_prefixes(self):
        raw = "    1 | # Header\n    2 | Description\n    3 | - bullet"
        expected = "# Header\nDescription\n- bullet"
        self.assertEqual(strip_note_line_numbers(raw), expected)

    def test_strip_colon_prefixed_lines(self):
        raw = "1: # Header\n2: Description\n3: - bullet"
        expected = "# Header\nDescription\n- bullet"
        self.assertEqual(strip_note_line_numbers(raw), expected)

    def test_unprefixed_text_unchanged(self):
        raw = "# Header\nDescription\n- bullet"
        self.assertEqual(strip_note_line_numbers(raw), raw)

    def test_empty_string(self):
        self.assertEqual(strip_note_line_numbers(""), "")


class TestMaestriCanvasVerbs(unittest.TestCase):
    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=True)
    @patch("taskctl.providers.maestri.MaestriIPCClient.send_request")
    def test_sync_task_cockpit_note_ipc(self, mock_send, mock_avail):
        mock_send.return_value = {"result": {"ok": True}}
        self.assertTrue(sync_task_cockpit_note("# TASK MD CONTENT"))
        mock_send.assert_called_with("note_write", {"name": "task-cockpit-agent-task-md", "content": "# TASK MD CONTENT"})

    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=False)
    @patch("taskctl.providers.maestri.run_maestri_cli")
    def test_sync_task_cockpit_note_cli_write(self, mock_cli, mock_avail):
        mock_cli.return_value = MagicMock(returncode=0)
        self.assertTrue(sync_task_cockpit_note("# TASK MD CONTENT"))
        mock_cli.assert_called_with(["note", "write", "task-cockpit-agent-task-md", "# TASK MD CONTENT"])

    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=False)
    @patch("taskctl.providers.maestri.run_maestri_cli")
    def test_sync_task_cockpit_note_cli_create_fallback(self, mock_cli, mock_avail):
        mock_fail = MagicMock(returncode=1)
        mock_ok = MagicMock(returncode=0)
        mock_cli.side_effect = [mock_fail, mock_ok]

        self.assertTrue(sync_task_cockpit_note("# TASK MD CONTENT"))
        self.assertEqual(mock_cli.call_count, 2)
        self.assertEqual(mock_cli.call_args_list[0][0][0], ["note", "write", "task-cockpit-agent-task-md", "# TASK MD CONTENT"])
        self.assertEqual(mock_cli.call_args_list[1][0][0], ["note", "create", "# TASK MD CONTENT", "--name", "task-cockpit-agent-task-md"])

    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=True)
    @patch("taskctl.providers.maestri.MaestriIPCClient.send_request")
    def test_pull_task_cockpit_note_ipc(self, mock_send, mock_avail):
        mock_send.return_value = {"result": {"content": "1 | # Active Task\n2 | - Description"}}
        content = pull_task_cockpit_note()
        self.assertEqual(content, "# Active Task\n- Description")

    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=False)
    @patch("taskctl.providers.maestri.run_maestri_cli")
    def test_pull_task_cockpit_note_cli(self, mock_cli, mock_avail):
        mock_cli.return_value = MagicMock(returncode=0, stdout="# Pulled Contract\n")
        content = pull_task_cockpit_note()
        self.assertEqual(content, "# Pulled Contract")

    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=False)
    @patch("taskctl.providers.maestri.run_maestri_cli", return_value=None)
    def test_pull_task_cockpit_note_none(self, mock_cli, mock_avail):
        self.assertIsNone(pull_task_cockpit_note())

    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=True)
    @patch("taskctl.providers.maestri.MaestriIPCClient.send_request")
    def test_send_canvas_notification_ipc(self, mock_send, mock_avail):
        mock_send.return_value = {"result": True}
        self.assertTrue(send_canvas_notification("Hello canvas"))

    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=False)
    @patch("taskctl.providers.maestri.run_maestri_cli")
    def test_send_canvas_notification_cli(self, mock_cli, mock_avail):
        mock_cli.return_value = MagicMock(returncode=0)
        self.assertTrue(send_canvas_notification("Hello CLI"))

    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=False)
    @patch("taskctl.providers.maestri.run_maestri_cli")
    def test_create_workspace_canvas(self, mock_cli, mock_avail):
        mock_cli.return_value = MagicMock(returncode=0)
        ok = create_workspace_canvas("my-repo", "/home/user/my-repo", group="Dev")
        self.assertTrue(ok)
        mock_cli.assert_called_with(["workspace", "create", "my-repo", "--dir", "/home/user/my-repo", "--group", "Dev"])

    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=True)
    @patch("taskctl.providers.maestri.MaestriIPCClient.send_request")
    def test_ask_agent_ipc(self, mock_send, mock_avail):
        mock_send.return_value = {"result": {"output": "Decomposition complete."}}
        res = ask_agent("Planner", "Plan task 03.1")
        self.assertEqual(res, "Decomposition complete.")

    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=False)
    @patch("taskctl.providers.maestri.run_maestri_cli")
    def test_ask_agent_cli(self, mock_cli, mock_avail):
        mock_cli.return_value = MagicMock(returncode=0, stdout="Plan draft\n")
        res = ask_agent("Planner", "Plan task")
        self.assertEqual(res, "Plan draft")


class TestCLICanvasCommands(unittest.TestCase):
    @patch("taskctl.cli.create_workspace_canvas", return_value=True)
    @patch("taskctl.cli.sync_task_cockpit_note", return_value=True)
    def test_cmd_ws(self, mock_sync, mock_create):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cmd_ws("custom-ws")
            mock_create.assert_called_once()
            output = mock_out.getvalue()
            self.assertIn("custom-ws", output)
            self.assertIn("Provisioned Maestri workspace", output)

    @patch("taskctl.cli.pull_task_cockpit_note")
    @patch("taskctl.cli.get_task_file")
    def test_cmd_sync_pull_success(self, mock_get_task, mock_pull):
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write("# old\n")
            temp_path = f.name

        try:
            mock_get_task.return_value = temp_path
            valid_content = """# Tasks

### 📌 Task [03.1]: New Remote Task
- **Status:** PLANNING

### Acceptance Criteria
- [ ] Criteria 1
"""
            mock_pull.return_value = valid_content

            with patch("sys.stdout", new_callable=io.StringIO):
                cmd_sync(pull=True)

            with open(temp_path, "r") as f:
                saved = f.read()
            self.assertIn("New Remote Task", saved)
        finally:
            os.remove(temp_path)

    @patch("taskctl.cli.pull_task_cockpit_note", return_value="invalid garbage without schema")
    @patch("taskctl.cli.get_task_file")
    def test_cmd_sync_pull_invalid_schema(self, mock_get_task, mock_pull):
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write("# local original\n")
            temp_path = f.name

        try:
            mock_get_task.return_value = temp_path
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                cmd_sync(pull=True)
                out = mock_out.getvalue()
                self.assertIn("does not contain valid TASK.md schema", out)

            with open(temp_path, "r") as f:
                saved = f.read()
            self.assertEqual(saved, "# local original\n")
        finally:
            os.remove(temp_path)

    @patch("taskctl.cli.ask_agent", return_value="Decomposed into 2 subtasks.")
    @patch("taskctl.cli.sync_task_cockpit_note")
    @patch("taskctl.cli.get_task_file")
    def test_cmd_plan(self, mock_get_task, mock_sync, mock_ask):
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write("""# Tasks

### 📌 Task [03.1]: Contract engine integration
- **Status:** READY FOR PLANNING

### Acceptance Criteria
- [ ] Test
""")
            temp_path = f.name

        try:
            mock_get_task.return_value = temp_path
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                cmd_plan("Decompose task 03.1")
                out = mock_out.getvalue()
                self.assertIn("Decomposed into 2 subtasks.", out)
                self.assertIn("Updated active task status to PLANNING", out)

            with open(temp_path, "r") as f:
                updated = f.read()
            self.assertIn("- **Status:** PLANNING", updated)
        finally:
            os.remove(temp_path)

    @patch("taskctl.cli.send_canvas_notification", return_value=True)
    def test_cmd_notify_with_canvas(self, mock_canvas_notif):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cmd_notify("Deployment finished")
            out = mock_out.getvalue()
            self.assertIn("Notification dispatched", out)
            self.assertIn("Canvas: sent", out)
            mock_canvas_notif.assert_called_with("Deployment finished")


if __name__ == "__main__":
    unittest.main()

