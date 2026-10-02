"""Strict Markdown parser and serializer for .agent/TASK.md."""

import re
import os
from typing import Dict, List, Any, Tuple, Optional

def find_repo_root(start_dir: Optional[str] = None) -> str:
    curr = os.path.abspath(start_dir) if start_dir else os.getcwd()
    while curr != "/":
        if os.path.exists(os.path.join(curr, ".agent", "TASK.md")) or os.path.exists(os.path.join(curr, ".git")):
            return curr
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return os.path.abspath(start_dir) if start_dir else os.getcwd()

def get_task_file(root_or_path: Optional[str] = None) -> str:
    if root_or_path and os.path.isfile(root_or_path) and os.path.basename(root_or_path) == "TASK.md":
        return root_or_path
    root = find_repo_root(root_or_path) if root_or_path else find_repo_root()
    path = os.path.join(root, ".agent", "TASK.md")
    if not os.path.exists(path):
        raise FileNotFoundError(f".agent/TASK.md not found in repository root: {root}")
    return path

def parse_task_md(content: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Parse active task and backlog items from .agent/TASK.md."""
    task_match = re.search(r"### 📌 Task \[([^\]]+)\]:\s*([^\n]+)", content)
    active_task: Dict[str, Any] = {}
    if task_match:
        active_task["id"] = task_match.group(1).strip()
        active_task["title"] = task_match.group(2).strip()

        desc_match = re.search(r"-\s*\*\*Description:\*\*\s*([^\n]+)", content)
        active_task["description"] = desc_match.group(1).strip() if desc_match else ""

        sys_match = re.search(r"-\s*\*\*Systems Involved:\*\*\s*([^\n]+)", content)
        active_task["systems"] = sys_match.group(1).strip() if sys_match else ""

        target_match = re.search(r"-\s*\*\*Runtime Target:\*\*\s*([^\n]+)", content)
        active_task["target"] = target_match.group(1).strip() if target_match else ""

        status_match = re.search(r"-\s*\*\*Status:\*\*\s*([^\n]+)", content)
        active_task["status"] = status_match.group(1).strip() if status_match else "UNKNOWN"

        crit_sec = re.search(r"### Acceptance Criteria[^\n]*\n(.*?)(?=\n---|\n## Completed Tasks Log|\n## Backlog|$)", content, re.DOTALL)
        criteria: List[Dict[str, Any]] = []
        if crit_sec:
            for line in crit_sec.group(1).strip().split("\n"):
                m = re.match(r"^-\s*\[([ xX])\]\s*(.*)", line.strip())
                if m:
                    criteria.append({"checked": m.group(1).lower() == "x", "text": m.group(2).strip()})
        active_task["criteria"] = criteria

    backlog: List[Dict[str, Any]] = []
    backlog_sec = re.search(r"## Backlog[^\n]*\n(.*?)(?=\n---|\n## Completed Tasks Log|\n## Release|$)", content, re.DOTALL)
    if backlog_sec:
        for line in backlog_sec.group(1).strip().split("\n"):
            m = re.match(r"^-\s*\[([ xX])\]\s*\*\*\[([^\]]+)\]\*\*\s*(.*)", line.strip())
            if m:
                backlog.append({
                    "checked": m.group(1).lower() == "x",
                    "id": m.group(2).strip(),
                    "title": m.group(3).strip()
                })

    return active_task, backlog

def parse_completed_tasks(content: str) -> List[Dict[str, Any]]:
    """Parse completed tasks from the '## Completed Tasks Log' section table."""
    completed: List[Dict[str, Any]] = []
    log_sec = re.search(r"## Completed Tasks Log[^\n]*\n(.*?)(?=\n---|\n## Backlog|\n## Release|$)", content, re.DOTALL)
    if not log_sec:
        return completed

    for line in log_sec.group(1).strip().split("\n"):
        line = line.strip()
        if not line.startswith("|") or "Task" in line or "---" in line:
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) >= 2:
            task_id = re.sub(r"[\[\]]", "", parts[0]).strip()
            title = parts[1].strip()
            commits = parts[2].strip() if len(parts) > 2 else ""
            date = parts[3].strip() if len(parts) > 3 else ""
            completed.append({
                "id": task_id,
                "title": title,
                "commits": commits,
                "date": date,
            })
    return completed
