import io
import os
import sys
import unittest
from unittest.mock import patch

from taskctl.core.parser import extract_dependencies, parse_task_md, parse_completed_tasks
from taskctl.core.graph import (
    TaskNode,
    TaskDependencyGraph,
    CycleDetectedError,
)
from taskctl.cli import cmd_graph
from taskctl.tui.state import collect_dashboard_state
from taskctl.tui.renderer import render_dag_view
from taskctl.tui.dashboard import Dashboard

SAMPLE_DAG_TASK_MD = """# TASK.md — Current Task and Roadmap

## Active Task

### 📌 Task [04.2]: Task dependency graph visualizer
- **Description:** Graph visualizer implementation.
- **Systems Involved:** [core, cli, tui]
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash'
- **Status:** RUNNING
- **Depends On:** [04.1], [03.7]

### Acceptance Criteria
- [ ] Criterion 1
- [x] Criterion 2

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [03.7] | Interactive terminal dashboard | [`eac2934`] | 2026-10-02 |
| [04.1] | Telemetry aggregation daemon (deps: [03.7]) | [`c41588f`] | 2026-10-02 |

---

## Backlog (Upcoming, in priority order)

- [ ] `[04.3]` Distributed tracing & telemetry spans (deps: [04.2])
- [ ] **[04.4]** Alert routing engine
"""

SAMPLE_CYCLIC_TASK_MD = """# TASK.md

## Active Task

### 📌 Task [01.2]: Second task
- **Status:** RUNNING
- **Depends On:** [01.3]

### Acceptance Criteria
- [ ] Crit A

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [01.1] | Scaffolding | [`1111111`] | 2026-10-01 |

---

## Backlog

- [ ] `[01.3]` Third task (deps: [01.2])
"""


class TestGraphEngine(unittest.TestCase):
    def test_extract_dependencies(self):
        self.assertEqual(extract_dependencies(""), [])
        self.assertEqual(extract_dependencies("Plain text"), [])
        self.assertEqual(extract_dependencies("[04.1], [03.7]"), ["04.1", "03.7"])
        self.assertEqual(extract_dependencies("(deps: [04.1], [04.2])"), ["04.1", "04.2"])
        self.assertEqual(extract_dependencies("(depends on: 04.1, 04.2)"), ["04.1", "04.2"])
        self.assertEqual(extract_dependencies("(after: [02.1])"), ["02.1"])

    def test_parse_task_md_with_dependencies(self):
        active, backlog = parse_task_md(SAMPLE_DAG_TASK_MD)
        self.assertEqual(active["id"], "04.2")
        self.assertEqual(active["dependencies"], ["04.1", "03.7"])
        self.assertEqual(len(backlog), 2)
        self.assertEqual(backlog[0]["id"], "04.3")
        self.assertEqual(backlog[0]["dependencies"], ["04.2"])
        self.assertEqual(backlog[1]["id"], "04.4")
        self.assertEqual(backlog[1]["dependencies"], [])

    def test_parse_completed_tasks_with_dependencies(self):
        completed = parse_completed_tasks(SAMPLE_DAG_TASK_MD)
        self.assertEqual(len(completed), 2)
        self.assertEqual(completed[0]["id"], "03.7")
        self.assertEqual(completed[0]["dependencies"], [])
        self.assertEqual(completed[1]["id"], "04.1")
        self.assertEqual(completed[1]["dependencies"], ["03.7"])

    def test_build_graph_explicit_and_sequential(self):
        graph = TaskDependencyGraph.build_from_content(SAMPLE_DAG_TASK_MD, infer_sequential=True)
        self.assertFalse(graph.has_cycle())
        self.assertIn("04.2", graph.nodes)
        self.assertIn("04.1", graph.nodes)
        self.assertIn("03.7", graph.nodes)
        self.assertIn("04.3", graph.nodes)

        # 04.2 depends on 04.1 and 03.7
        self.assertIn("04.1", graph.nodes["04.2"].dependencies)
        self.assertIn("03.7", graph.nodes["04.2"].dependencies)
        # 04.4 had no explicit deps, so sequentially depends on 04.3 in epic 04
        self.assertIn("04.3", graph.nodes["04.4"].dependencies)

    def test_subtask_sequential_inference(self):
        content = """# TASK.md
### 📌 Task [05.1]: Parent
- **Status:** RUNNING

---
## Backlog
- [ ] [05.1.1] Subtask 1
- [ ] [05.1.2] Subtask 2
"""
        graph = TaskDependencyGraph.build_from_content(content, infer_sequential=True)
        self.assertIn("05.1", graph.nodes["05.1.1"].dependencies)
        self.assertIn("05.1.1", graph.nodes["05.1.2"].dependencies)

    def test_cycle_detection_and_reporting(self):
        g = TaskDependencyGraph()
        g.add_node(TaskNode(id="A", title="Node A"))
        g.add_node(TaskNode(id="B", title="Node B"))
        g.add_node(TaskNode(id="C", title="Node C"))

        g.add_edge("A", "B")
        g.add_edge("B", "C")
        self.assertFalse(g.has_cycle())
        self.assertEqual(g.topological_sort(), ["A", "B", "C"])

        # Add cycle C -> A
        g.add_edge("C", "A")
        self.assertTrue(g.has_cycle())
        cycles = g.find_cycles()
        self.assertTrue(any("A" in c and "B" in c and "C" in c for c in cycles))
        with self.assertRaises(CycleDetectedError):
            g.topological_sort()

    def test_self_cycle(self):
        g = TaskDependencyGraph()
        g.add_node(TaskNode(id="A", title="Node A"))
        g.add_edge("A", "A")
        self.assertTrue(g.has_cycle())
        cycles = g.find_cycles()
        self.assertEqual(len(cycles), 1)

    def test_ascii_tree_rendering(self):
        graph = TaskDependencyGraph.build_from_content(SAMPLE_DAG_TASK_MD)
        tree = graph.render_ascii_tree(show_status=True, use_color=False)
        self.assertIn("[03.7]", tree)
        self.assertIn("[04.1]", tree)
        self.assertIn("[04.2]", tree)
        self.assertIn("[04.3]", tree)
        self.assertIn("└── ", tree)

    def test_ascii_tree_handles_cycles_safely(self):
        graph = TaskDependencyGraph.build_from_content(SAMPLE_CYCLIC_TASK_MD)
        tree = graph.render_ascii_tree(show_status=True, use_color=False)
        self.assertIn("CYCLE", tree)

    def test_mermaid_rendering(self):
        graph = TaskDependencyGraph.build_from_content(SAMPLE_DAG_TASK_MD)
        mermaid = graph.render_mermaid()
        self.assertTrue(mermaid.startswith("```mermaid\ngraph TD"))
        self.assertIn("subgraph Completed", mermaid)
        self.assertIn("subgraph Active", mermaid)
        self.assertIn("subgraph Backlog", mermaid)
        self.assertIn("node_04_1 --> node_04_2", mermaid)
        self.assertTrue(mermaid.endswith("```"))

    def test_to_dict_serialization(self):
        graph = TaskDependencyGraph.build_from_content(SAMPLE_DAG_TASK_MD)
        data = graph.to_dict()
        self.assertIn("total_nodes", data)
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        self.assertFalse(data["has_cycles"])
        self.assertIsInstance(data["topological_order"], list)
        self.assertIn("04.2", data["nodes"])

    def test_cmd_graph_flags(self):
        # 1. Tree output
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = cmd_graph(tree=True)
            self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("TASK DEPENDENCY GRAPH", out)

        # 2. Mermaid output
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = cmd_graph(mermaid=True)
            self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("graph TD", out)

        # 3. JSON output
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = cmd_graph(json_output=True)
            self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn('"total_nodes":', out)

        # 4. Check cycles on clean graph
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = cmd_graph(check_cycles=True)
            self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("No dependency cycles detected", out)

    def test_cmd_graph_check_cycles_failure(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(SAMPLE_CYCLIC_TASK_MD)
            tmp_path = f.name
        try:
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = cmd_graph(check_cycles=True, file_path=tmp_path)
                self.assertEqual(code, 1)
            out = buf.getvalue()
            self.assertIn("Cycles Detected", out)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_tui_dag_view_and_toggle(self):
        state = collect_dashboard_state(run_tests=False, run_audit=False)
        self.assertIsNotNone(state.task_graph)
        dag_output = render_dag_view(state, use_color=False, term_width=80)
        self.assertIn("TASKCTL DAG VISUALIZER", dag_output)

        dash = Dashboard(view_dag=False)
        self.assertEqual(dash.view_mode, "dashboard")
        # Press 'v' to toggle to DAG
        action = dash.handle_input("v")
        self.assertEqual(action, "refresh")
        self.assertEqual(dash.view_mode, "dag")
        # Press 'V' to toggle back
        action = dash.handle_input("V")
        self.assertEqual(action, "refresh")
        self.assertEqual(dash.view_mode, "dashboard")

    def test_export_execution_plan_concurrent_stages(self):
        graph = TaskDependencyGraph()
        # Completed prerequisite
        graph.add_node(TaskNode(id="01.1", title="Setup Base", status="DONE", section="completed"))
        # Stage 0: 01.2 and 01.3 both depend on 01.1 (concurrent wave!)
        graph.add_node(TaskNode(id="01.2", title="Worker A", status="RUNNING", section="active", dependencies=["01.1"]))
        graph.add_node(TaskNode(id="01.3", title="Worker B", status="BACKLOG", section="backlog", dependencies=["01.1"]))
        # Stage 1: 01.4 depends on both 01.2 and 01.3
        graph.add_node(TaskNode(id="01.4", title="Integration", status="BACKLOG", section="backlog", dependencies=["01.2", "01.3"]))

        plan = graph.export_execution_plan(only_pending=True, repo="/test/repo")

        self.assertEqual(plan["version"], "1.0.0")
        self.assertEqual(plan["repository"], "/test/repo")
        self.assertFalse(plan["summary"]["has_cycles"])
        self.assertTrue(plan["summary"]["is_executable"])
        self.assertEqual(plan["summary"]["total_tasks"], 4)
        self.assertEqual(plan["summary"]["completed_count"], 1)
        self.assertEqual(plan["summary"]["pending_count"], 3)
        self.assertEqual(plan["summary"]["total_stages"], 2)
        self.assertEqual(plan["summary"]["max_concurrency"], 2)

        # Stage 0 check (concurrent)
        stage0 = plan["stages"][0]
        self.assertEqual(stage0["stage_index"], 0)
        self.assertEqual(stage0["concurrency"], 2)
        self.assertTrue(stage0["parallel"])
        stage0_ids = [t["id"] for t in stage0["tasks"]]
        self.assertEqual(stage0_ids, ["01.2", "01.3"])
        for t in stage0["tasks"]:
            self.assertTrue(t["ready"])
            self.assertTrue(t["suggested_branch"].startswith("task/"))

        # Stage 1 check (waits for stage 0)
        stage1 = plan["stages"][1]
        self.assertEqual(stage1["stage_index"], 1)
        self.assertEqual(stage1["concurrency"], 1)
        self.assertFalse(stage1["parallel"])
        self.assertEqual(stage1["tasks"][0]["id"], "01.4")
        self.assertFalse(stage1["tasks"][0]["ready"])

    def test_export_execution_plan_with_cycles(self):
        graph = TaskDependencyGraph.build_from_content(SAMPLE_CYCLIC_TASK_MD)
        plan = graph.export_execution_plan()
        self.assertTrue(plan["summary"]["has_cycles"])
        self.assertFalse(plan["summary"]["is_executable"])
        self.assertIn("error", plan)
        self.assertGreater(len(plan["cycles"]), 0)
        self.assertEqual(plan["stages"], [])

    def test_export_execution_plan_unresolved_dependencies(self):
        graph = TaskDependencyGraph()
        graph.add_node(TaskNode(id="01.1", title="Task 1", status="RUNNING", dependencies=["99.9"]))

        plan = graph.export_execution_plan(only_pending=True)
        self.assertFalse(plan["summary"]["is_executable"])
        self.assertIn("blocked_tasks", plan)
        self.assertEqual(len(plan["blocked_tasks"]), 1)
        self.assertEqual(plan["blocked_tasks"][0]["id"], "01.1")
        self.assertEqual(plan["blocked_tasks"][0]["unmet_dependencies"], ["99.9"])

    def test_export_execution_plan_all_stages(self):
        graph = TaskDependencyGraph()
        graph.add_node(TaskNode(id="A", title="Node A", status="DONE", section="completed"))
        graph.add_node(TaskNode(id="B", title="Node B", status="BACKLOG", section="backlog", dependencies=["A"]))

        plan = graph.export_execution_plan(only_pending=False)
        self.assertEqual(plan["summary"]["total_stages"], 2)
        self.assertEqual(plan["stages"][0]["tasks"][0]["id"], "A")
        self.assertEqual(plan["stages"][1]["tasks"][0]["id"], "B")

    def test_cmd_graph_export_plan_stdout_and_file(self):
        import json
        import tempfile

        # Test stdout export
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = cmd_graph(export_plan=True)
            self.assertEqual(code, 0)
        out = buf.getvalue()
        data = json.loads(out)
        self.assertEqual(data["version"], "1.0.0")
        self.assertIn("summary", data)
        self.assertIn("stages", data)

        # Test file export
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            tmp_out = f.name

        try:
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = cmd_graph(export_plan=True, out_file=tmp_out)
                self.assertEqual(code, 0)
            self.assertIn("[OK] Agnostic DAG execution plan exported to", buf.getvalue())
            with open(tmp_out, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["version"], "1.0.0")
            self.assertIn("summary", saved)
        finally:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)

    def test_cmd_graph_export_plan_cyclic_failure(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(SAMPLE_CYCLIC_TASK_MD)
            tmp_md = f.name

        try:
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = cmd_graph(export_plan=True, file_path=tmp_md)
                self.assertEqual(code, 1)
            out = buf.getvalue()
            self.assertIn("Dependency cycle(s) detected", out)
        finally:
            if os.path.exists(tmp_md):
                os.remove(tmp_md)


if __name__ == "__main__":
    unittest.main()
