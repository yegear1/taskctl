"""Strict Markdown parser and serializer for .agent/TASK.md."""

import re
import os
from typing import Dict, List, Any, Tuple, Optional

def find_repo_root() -> str:
    curr = os.getcwd()
    while curr != "/":
        if os.path.exists(os.path.join(curr, ".agent", "TASK.md")) or os.path.exists(os.path.join(curr, ".git")):
            return curr
        curr = os.path.dirname(curr)
    return os.getcwd()

def get_task_file() -> str:
    root = find_repo_root()
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
