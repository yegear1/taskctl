"""Task dependency graph engine, cycle detector, and visualizers for taskctl."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from taskctl.core.parser import parse_task_md, parse_completed_tasks, get_task_file


class CycleDetectedError(Exception):
    """Raised when a dependency cycle is detected in the task graph."""

    def __init__(self, cycles: List[List[str]], message: Optional[str] = None):
        self.cycles = cycles
        formatted = "; ".join(" -> ".join(f"[{x}]" for x in c) for c in cycles)
        msg = message or f"Dependency cycle(s) detected: {formatted}"
        super().__init__(msg)


@dataclass
class TaskNode:
    """Represents a single task in the dependency graph."""

    id: str
    title: str
    status: str = "PENDING"  # "DONE", "RUNNING", "PLANNING", "READY", "BACKLOG", "UNKNOWN"
    section: str = "backlog"  # "completed", "active", "backlog"
    dependencies: List[str] = field(default_factory=list)  # Prerequisites (incoming)
    dependents: List[str] = field(default_factory=list)  # Next tasks (outgoing)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_done(self) -> bool:
        return self.status.upper() in ("DONE", "APPROVED", "COMPLETED")

    @property
    def is_active(self) -> bool:
        return self.status.upper() in ("RUNNING", "PLANNING", "READY", "READY FOR PLANNING")


class TaskDependencyGraph:
    """Directed Acyclic Graph (DAG) of task dependencies with cycle detection."""

    def __init__(self):
        self.nodes: Dict[str, TaskNode] = {}

    def add_node(self, node: TaskNode) -> None:
        """Add or update a task node."""
        if node.id in self.nodes:
            existing = self.nodes[node.id]
            existing.title = node.title or existing.title
            existing.status = node.status or existing.status
            existing.section = node.section or existing.section
            for d in node.dependencies:
                if d not in existing.dependencies:
                    existing.dependencies.append(d)
        else:
            self.nodes[node.id] = node

    def add_edge(self, from_id: str, to_id: str) -> None:
        """Add directed dependency edge: to_id depends on from_id (from_id precedes to_id)."""
        if from_id not in self.nodes:
            self.nodes[from_id] = TaskNode(id=from_id, title=f"Task {from_id}", status="UNKNOWN", section="unknown")
        if to_id not in self.nodes:
            self.nodes[to_id] = TaskNode(id=to_id, title=f"Task {to_id}", status="UNKNOWN", section="unknown")

        if from_id not in self.nodes[to_id].dependencies:
            self.nodes[to_id].dependencies.append(from_id)
        if to_id not in self.nodes[from_id].dependents:
            self.nodes[from_id].dependents.append(to_id)

    @classmethod
    def build_from_content(cls, content: str, infer_sequential: bool = True) -> TaskDependencyGraph:
        """Construct graph from TASK.md content."""
        graph = cls()

        active_task, backlog = parse_task_md(content)
        completed_tasks = parse_completed_tasks(content)

        # 1. Register completed tasks
        for item in completed_tasks:
            t_id = item["id"]
            graph.add_node(
                TaskNode(
                    id=t_id,
                    title=item.get("title", ""),
                    status="DONE",
                    section="completed",
                    dependencies=list(item.get("dependencies", [])),
                    metadata={"commits": item.get("commits", ""), "date": item.get("date", "")},
                )
            )

        # 2. Register active task
        active_id = active_task.get("id", "")
        if active_id and active_id != "XX.Y":
            graph.add_node(
                TaskNode(
                    id=active_id,
                    title=active_task.get("title", ""),
                    status=active_task.get("status", "RUNNING"),
                    section="active",
                    dependencies=list(active_task.get("dependencies", [])),
                    metadata={"target": active_task.get("target", ""), "systems": active_task.get("systems", "")},
                )
            )

        # 3. Register backlog items
        for item in backlog:
            b_id = item["id"]
            if b_id == "XX.Y":
                continue
            graph.add_node(
                TaskNode(
                    id=b_id,
                    title=item.get("title", ""),
                    status="BACKLOG",
                    section="backlog",
                    dependencies=list(item.get("dependencies", [])),
                )
            )

        # 4. Wire explicit dependency edges
        for node in list(graph.nodes.values()):
            for dep_id in list(node.dependencies):
                graph.add_edge(dep_id, node.id)

        # 5. Wire sequential fallback dependencies if enabled
        if infer_sequential:
            cls._infer_sequential_dependencies(graph)

        return graph

    @classmethod
    def build_from_file(cls, path_or_root: Optional[str] = None, infer_sequential: bool = True) -> TaskDependencyGraph:
        """Construct graph from TASK.md file."""
        task_file = get_task_file(path_or_root)
        with open(task_file, "r", encoding="utf-8") as f:
            content = f.read()
        return cls.build_from_content(content, infer_sequential=infer_sequential)

    @classmethod
    def _infer_sequential_dependencies(cls, graph: TaskDependencyGraph) -> None:
        """Infers sequential dependencies for tasks without explicit dependencies."""
        def parse_seq(task_id: str) -> Optional[Tuple[int, int, int]]:
            m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?$", task_id)
            if not m:
                return None
            epic = int(m.group(1))
            seq = int(m.group(2))
            sub = int(m.group(3)) if m.group(3) else 0
            return (epic, seq, sub)

        parsed_keys = {}
        for nid in graph.nodes:
            key = parse_seq(nid)
            if key:
                parsed_keys[nid] = key

        sorted_ids = sorted(parsed_keys.keys(), key=lambda x: parsed_keys[x])

        for i, curr_id in enumerate(sorted_ids):
            node = graph.nodes[curr_id]
            # Only infer if task has no explicit dependencies
            if node.dependencies:
                continue

            curr_epic, curr_seq, curr_sub = parsed_keys[curr_id]

            if curr_sub > 0:
                prev_sub_id = f"{curr_epic:02d}.{curr_seq}.{curr_sub - 1}" if curr_sub > 1 else f"{curr_epic:02d}.{curr_seq}"
                if prev_sub_id in graph.nodes:
                    graph.add_edge(prev_sub_id, curr_id)
            elif curr_seq > 1:
                prev_seq_id = f"{curr_epic:02d}.{curr_seq - 1}"
                if prev_seq_id in graph.nodes:
                    graph.add_edge(prev_seq_id, curr_id)

    def find_cycles(self) -> List[List[str]]:
        """Detect all directed cycles in the graph using DFS coloring."""
        color: Dict[str, int] = {k: 0 for k in self.nodes}
        path: List[str] = []
        cycles: List[List[str]] = []
        seen_cycles: Set[str] = set()

        def dfs(u: str):
            color[u] = 1
            path.append(u)

            for v in self.nodes[u].dependents:
                if v not in color:
                    color[v] = 0
                if color[v] == 1:
                    idx = path.index(v)
                    cycle = path[idx:] + [v]
                    core_nodes = cycle[:-1]
                    min_idx = core_nodes.index(min(core_nodes))
                    norm = core_nodes[min_idx:] + core_nodes[:min_idx]
                    norm_key = "->".join(norm)
                    if norm_key not in seen_cycles:
                        seen_cycles.add(norm_key)
                        cycles.append(norm + [norm[0]])
                elif color[v] == 0:
                    dfs(v)

            path.pop()
            color[u] = 2

        for node_id in sorted(self.nodes.keys()):
            if color.get(node_id, 0) == 0:
                dfs(node_id)

        return cycles

    def has_cycle(self) -> bool:
        """Returns True if any cycle exists in the graph."""
        return len(self.find_cycles()) > 0

    def topological_sort(self) -> List[str]:
        """Perform topological sort on the task DAG using Kahn's algorithm."""
        cycles = self.find_cycles()
        if cycles:
            raise CycleDetectedError(cycles)

        in_degree: Dict[str, int] = {k: len(node.dependencies) for k, node in self.nodes.items()}
        zero_in = [k for k, deg in in_degree.items() if deg == 0]
        zero_in.sort()

        order: List[str] = []
        while zero_in:
            u = zero_in.pop(0)
            order.append(u)
            for v in sorted(self.nodes[u].dependents):
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    zero_in.append(v)
                    zero_in.sort()

        if len(order) < len(self.nodes):
            remaining_cycles = self.find_cycles()
            raise CycleDetectedError(remaining_cycles)

        return order

    def render_ascii_tree(self, show_status: bool = True, use_color: bool = False) -> str:
        """Render a formatted ASCII forest/tree representation of the task graph."""
        lines: List[str] = []
        cycles = self.find_cycles()

        roots = [nid for nid, node in self.nodes.items() if len(node.dependencies) == 0]
        if not roots and self.nodes:
            roots = sorted(self.nodes.keys())[:1]
        else:
            roots.sort()

        visited_nodes: Set[str] = set()

        def format_node_label(node: TaskNode) -> str:
            status_str = f" [{node.status}]" if show_status else ""
            if use_color:
                if node.status in ("DONE", "COMPLETED", "APPROVED"):
                    status_str = f" \033[32m[{node.status}]\033[0m"
                elif node.status in ("RUNNING", "ACTIVE"):
                    status_str = f" \033[36m[{node.status}]\033[0m"
                elif node.status in ("PLANNING", "READY"):
                    status_str = f" \033[33m[{node.status}]\033[0m"
                elif node.status in ("BACKLOG",):
                    status_str = f" \033[90m[{node.status}]\033[0m"
            return f"[{node.id}] {node.title}{status_str}"

        def build_tree(node_id: str, prefix: str = "", is_last: bool = True, branch_path: Optional[List[str]] = None):
            branch_path = branch_path or []
            node = self.nodes.get(node_id)
            if not node:
                return

            branch_char = "└── " if is_last else "├── "
            label = format_node_label(node)

            if node_id in branch_path:
                lines.append(f"{prefix}{branch_char}{label} \033[31m(CYCLE -> [{node_id}])\033[0m" if use_color else f"{prefix}{branch_char}{label} (CYCLE -> [{node_id}])")
                return

            lines.append(f"{prefix}{branch_char}{label}")
            visited_nodes.add(node_id)

            new_prefix = prefix + ("    " if is_last else "│   ")
            deps = sorted(node.dependents)
            new_branch_path = branch_path + [node_id]

            for idx, child_id in enumerate(deps):
                child_is_last = (idx == len(deps) - 1)
                build_tree(child_id, prefix=new_prefix, is_last=child_is_last, branch_path=new_branch_path)

        for r_idx, root_id in enumerate(roots):
            root_node = self.nodes[root_id]
            lines.append(format_node_label(root_node))
            visited_nodes.add(root_id)
            children = sorted(root_node.dependents)
            for c_idx, child_id in enumerate(children):
                build_tree(child_id, prefix="", is_last=(c_idx == len(children) - 1), branch_path=[root_id])
            if r_idx < len(roots) - 1:
                lines.append("")

        remaining = sorted(set(self.nodes.keys()) - visited_nodes)
        if remaining:
            lines.append("")
            lines.append("Disconnected / Cyclic Components:")
            for rem_id in remaining:
                if rem_id not in visited_nodes:
                    build_tree(rem_id, prefix="", is_last=True, branch_path=[])

        return "\n".join(lines)

    def render_mermaid(self) -> str:
        """Render Mermaid diagram representation of the task graph."""
        lines: List[str] = ["```mermaid", "graph TD"]

        completed = [n for n in self.nodes.values() if n.section == "completed"]
        active = [n for n in self.nodes.values() if n.section == "active"]
        backlog = [n for n in self.nodes.values() if n.section == "backlog"]
        other = [n for n in self.nodes.values() if n.section not in ("completed", "active", "backlog")]

        def clean_node_id(nid: str) -> str:
            return "node_" + re.sub(r"[^a-zA-Z0-9_]", "_", nid)

        def clean_text(text: str) -> str:
            return text.replace('"', "'").strip()

        if completed:
            lines.append("    subgraph Completed")
            for n in sorted(completed, key=lambda x: x.id):
                lines.append(f'        {clean_node_id(n.id)}["[{n.id}] {clean_text(n.title)} ({n.status})"]')
            lines.append("    end")

        if active:
            lines.append("    subgraph Active")
            for n in sorted(active, key=lambda x: x.id):
                lines.append(f'        {clean_node_id(n.id)}["[{n.id}] {clean_text(n.title)} ({n.status})"]')
            lines.append("    end")

        if backlog:
            lines.append("    subgraph Backlog")
            for n in sorted(backlog, key=lambda x: x.id):
                lines.append(f'        {clean_node_id(n.id)}["[{n.id}] {clean_text(n.title)} ({n.status})"]')
            lines.append("    end")

        if other:
            lines.append("    subgraph Other")
            for n in sorted(other, key=lambda x: x.id):
                lines.append(f'        {clean_node_id(n.id)}["[{n.id}] {clean_text(n.title)} ({n.status})"]')
            lines.append("    end")

        cycles = self.find_cycles()
        cycle_edges = set()
        for c in cycles:
            for i in range(len(c) - 1):
                cycle_edges.add((c[i], c[i + 1]))

        edge_lines = []
        for nid in sorted(self.nodes.keys()):
            for dep in sorted(self.nodes[nid].dependents):
                from_nid = clean_node_id(nid)
                to_nid = clean_node_id(dep)
                if (nid, dep) in cycle_edges:
                    edge_lines.append(f"    {from_nid} -. cycle .-> {to_nid}")
                else:
                    edge_lines.append(f"    {from_nid} --> {to_nid}")

        if edge_lines:
            lines.extend(edge_lines)

        lines.append("")
        lines.append("    classDef done fill:#238636,stroke:#2ea043,color:#ffffff;")
        lines.append("    classDef running fill:#1f6feb,stroke:#388bfd,color:#ffffff;")
        lines.append("    classDef planning fill:#9e6a03,stroke:#bb8009,color:#ffffff;")
        lines.append("    classDef backlog fill:#30363d,stroke:#8b949e,color:#c9d1d9;")
        lines.append("    classDef cyclic fill:#da3633,stroke:#f85149,color:#ffffff;")

        for n in self.nodes.values():
            cid = clean_node_id(n.id)
            if any(n.id in c for c in cycles):
                lines.append(f"    class {cid} cyclic;")
            elif n.is_done:
                lines.append(f"    class {cid} done;")
            elif n.status.upper() == "RUNNING":
                lines.append(f"    class {cid} running;")
            elif n.status.upper() in ("PLANNING", "READY", "READY FOR PLANNING"):
                lines.append(f"    class {cid} planning;")
            else:
                lines.append(f"    class {cid} backlog;")

        lines.append("```")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph to dictionary for JSON output."""
        cycles = self.find_cycles()
        topological = []
        if not cycles:
            try:
                topological = self.topological_sort()
            except CycleDetectedError:
                pass

        edges = []
        for nid in sorted(self.nodes.keys()):
            for dep in sorted(self.nodes[nid].dependents):
                edges.append({"from": nid, "to": dep})

        return {
            "total_nodes": len(self.nodes),
            "has_cycles": len(cycles) > 0,
            "cycles": cycles,
            "topological_order": topological,
            "nodes": {
                nid: {
                    "id": node.id,
                    "title": node.title,
                    "status": node.status,
                    "section": node.section,
                    "dependencies": node.dependencies,
                    "dependents": node.dependents,
                    "metadata": node.metadata,
                }
                for nid, node in sorted(self.nodes.items())
            },
            "edges": edges,
        }
