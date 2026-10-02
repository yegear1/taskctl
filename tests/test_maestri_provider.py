"""Tests for Maestri canvas topology presets, generators, and workspace provisioning."""

import io
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from taskctl.providers.maestri import (
    CanvasAgent,
    CanvasNote,
    CanvasTopology,
    list_topology_presets,
    get_topology_preset,
    apply_topology_to_canvas,
    create_workspace_canvas,
)
from taskctl.cli import cmd_ws


class TestMaestriTopologyPresets(unittest.TestCase):
    def test_list_topology_presets(self):
        presets = list_topology_presets()
        self.assertIn("trinity", presets)
        self.assertIn("swarm", presets)
        self.assertIn("audit", presets)

    def test_get_trinity_preset(self):
        topo = get_topology_preset("trinity", task_content="# Test Task")
        self.assertEqual(topo.preset, "trinity")
        agent_names = [a.name for a in topo.agents]
        self.assertEqual(agent_names, ["Planner", "Builder", "Auditor"])

        roles = {a.name: a.role for a in topo.agents}
        self.assertEqual(roles["Planner"], "Planner")
        self.assertEqual(roles["Builder"], "Implementer")
        self.assertEqual(roles["Auditor"], "Scope Auditor")

        self.assertEqual(len(topo.notes), 1)
        self.assertEqual(topo.notes[0].name, "task-cockpit-agent-task-md")
        self.assertEqual(topo.notes[0].content, "# Test Task")

        # Verify ropes
        connections = topo.connections
        self.assertIn(("Planner", "Builder"), connections)
        self.assertIn(("Builder", "Auditor"), connections)
        self.assertIn(("Planner", "Auditor"), connections)
        self.assertIn(("task-cockpit-agent-task-md", "Planner"), connections)
        self.assertIn(("task-cockpit-agent-task-md", "Builder"), connections)
        self.assertIn(("task-cockpit-agent-task-md", "Auditor"), connections)

    def test_get_swarm_preset_default_workers(self):
        topo = get_topology_preset("swarm")
        self.assertEqual(topo.preset, "swarm")
        agent_names = [a.name for a in topo.agents]
        self.assertEqual(agent_names, ["SwarmLead", "Worker-1", "Worker-2", "Worker-3"])
        self.assertEqual(topo.metadata.get("workers"), 3)

        self.assertEqual(len(topo.notes), 1)
        self.assertIn(("task-cockpit-agent-task-md", "SwarmLead"), topo.connections)
        for i in range(1, 4):
            self.assertIn(("SwarmLead", f"Worker-{i}"), topo.connections)

    def test_get_swarm_preset_custom_workers(self):
        topo = get_topology_preset("swarm", workers=5)
        self.assertEqual(len(topo.agents), 6)  # 1 lead + 5 workers
        self.assertIn("Worker-5", [a.name for a in topo.agents])
        self.assertIn(("SwarmLead", "Worker-5"), topo.connections)

    def test_get_swarm_preset_clamped_workers(self):
        topo = get_topology_preset("swarm", workers=0)
        self.assertEqual(len(topo.agents), 2)  # clamped to at least 1 worker + 1 lead
        self.assertEqual([a.name for a in topo.agents], ["SwarmLead", "Worker-1"])

    def test_get_audit_preset(self):
        topo = get_topology_preset("audit")
        self.assertEqual(topo.preset, "audit")
        agent_names = [a.name for a in topo.agents]
        self.assertEqual(agent_names, ["ScopeAuditor", "TestVerifier", "SecurityAuditor"])

        self.assertIn(("ScopeAuditor", "TestVerifier"), topo.connections)
        self.assertIn(("TestVerifier", "SecurityAuditor"), topo.connections)
        self.assertIn(("task-cockpit-agent-task-md", "ScopeAuditor"), topo.connections)

    def test_unknown_preset_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            get_topology_preset("quantum-supercomputer")
        self.assertIn("Unknown topology preset", str(ctx.exception))


class TestApplyTopologyToCanvas(unittest.TestCase):
    @patch("taskctl.providers.maestri.create_workspace_canvas", return_value=True)
    @patch("taskctl.providers.maestri.sync_task_cockpit_note", return_value=True)
    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=True)
    @patch("taskctl.providers.maestri.MaestriIPCClient.send_request")
    def test_apply_topology_ipc_success(self, mock_send, mock_avail, mock_sync_note, mock_create_ws):
        mock_send.return_value = {"result": True}
        topo = get_topology_preset("trinity")

        res = apply_topology_to_canvas(topo, dir_path="/fake/repo", workspace_name="test-repo")

        self.assertTrue(res["success"])
        self.assertFalse(res["degraded"])
        self.assertEqual(res["preset"], "trinity")
        self.assertEqual(res["workspace"], "test-repo")
        self.assertEqual(len(res["agents_created"]), 3)
        self.assertEqual(len(res["connections_created"]), len(topo.connections))

    @patch("taskctl.providers.maestri.create_workspace_canvas", return_value=True)
    @patch("taskctl.providers.maestri.sync_task_cockpit_note", return_value=True)
    @patch("taskctl.providers.maestri.resolve_maestri_cli", return_value="/usr/local/bin/maestri")
    @patch("os.path.exists", return_value=True)
    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=False)
    @patch("taskctl.providers.maestri.run_maestri_cli")
    def test_apply_topology_cli_fallback(
        self, mock_run_cli, mock_ipc_avail, mock_exists, mock_resolve_cli, mock_sync_note, mock_create_ws
    ):
        mock_run_cli.return_value = MagicMock(returncode=0)
        topo = get_topology_preset("audit")

        res = apply_topology_to_canvas(topo, dir_path="/fake/repo", workspace_name="audit-workspace")

        self.assertTrue(res["success"])
        self.assertFalse(res["degraded"])
        self.assertEqual(len(res["agents_created"]), 3)
        self.assertTrue(mock_run_cli.called)

    @patch("taskctl.providers.maestri.resolve_maestri_cli", return_value=None)
    @patch("taskctl.providers.maestri.MaestriIPCClient.is_available", return_value=False)
    def test_apply_topology_degraded_offline(self, mock_ipc_avail, mock_resolve_cli):
        topo = get_topology_preset("swarm", workers=2)
        res = apply_topology_to_canvas(topo, dir_path="/fake/repo", workspace_name="offline-ws")

        self.assertFalse(res["success"])
        self.assertTrue(res["degraded"])
        self.assertEqual(res["agents_created"], [])
        self.assertIn("unavailable", res.get("error", ""))


class TestCreateWorkspaceWithPreset(unittest.TestCase):
    @patch("taskctl.providers.maestri.apply_topology_to_canvas")
    @patch("taskctl.providers.maestri.run_maestri_cli")
    def test_create_workspace_canvas_with_preset(self, mock_cli, mock_apply):
        mock_cli.return_value = MagicMock(returncode=0)
        mock_apply.return_value = {"success": True}

        ok = create_workspace_canvas("my-workspace", "/fake/repo", preset="trinity")
        self.assertTrue(ok)
        mock_apply.assert_called_once()


class TestCLIWorkspacePresetIntegration(unittest.TestCase):
    @patch("taskctl.cli.find_repo_root", return_value="/tmp/test-repo")
    @patch("taskctl.cli.apply_topology_to_canvas")
    def test_cmd_ws_with_preset_success(self, mock_apply, mock_root):
        mock_apply.return_value = {
            "success": True,
            "preset": "trinity",
            "workspace": "test-repo",
            "agents_created": ["Planner", "Builder", "Auditor"],
            "notes_created": ["task-cockpit-agent-task-md"],
            "connections_created": [("Planner", "Builder")],
            "degraded": False,
        }

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = cmd_ws(preset="trinity")
            self.assertEqual(code, 0)
            output = mock_out.getvalue()
            self.assertIn("Topology Preset: trinity", output)
            self.assertIn("Successfully provisioned canvas workspace with 'trinity' topology", output)
            self.assertIn("Agents (3)", output)

    @patch("taskctl.cli.find_repo_root", return_value="/tmp/test-repo")
    @patch("taskctl.cli.apply_topology_to_canvas")
    def test_cmd_ws_with_swarm_workers(self, mock_apply, mock_root):
        mock_apply.return_value = {
            "success": True,
            "preset": "swarm",
            "workspace": "test-repo",
            "agents_created": ["SwarmLead", "Worker-1", "Worker-2", "Worker-3", "Worker-4"],
            "notes_created": ["task-cockpit-agent-task-md"],
            "connections_created": [],
            "degraded": False,
        }

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = cmd_ws(preset="swarm", workers=4)
            self.assertEqual(code, 0)
            output = mock_out.getvalue()
            self.assertIn("Worker Count   : 4", output)

    @patch("taskctl.cli.find_repo_root", return_value="/tmp/test-repo")
    def test_cmd_ws_unknown_preset(self, mock_root):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = cmd_ws(preset="nonexistent-preset")
            self.assertEqual(code, 1)
            output = mock_out.getvalue()
            self.assertIn("Unknown topology preset 'nonexistent-preset'", output)

    @patch("taskctl.cli.find_repo_root", return_value="/tmp/test-repo")
    @patch("taskctl.cli.apply_topology_to_canvas")
    def test_cmd_ws_degraded_offline(self, mock_apply, mock_root):
        mock_apply.return_value = {
            "success": False,
            "preset": "audit",
            "workspace": "test-repo",
            "agents_created": [],
            "notes_created": [],
            "connections_created": [],
            "degraded": True,
        }

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = cmd_ws(preset="audit")
            self.assertEqual(code, 1)
            output = mock_out.getvalue()
            self.assertIn("Remote canvas workspace degraded", output)
            self.assertIn("Topology plan registered locally", output)


if __name__ == "__main__":
    unittest.main()
