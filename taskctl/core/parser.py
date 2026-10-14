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

def resolve_repo_path(repo: Optional[str] = None, base_dir: Optional[str] = None) -> str:
    """Resolve repository root directory from a path, relative path, or repository name.

    If repo is None or empty, resolves repository root from base_dir (or current working directory).
    If repo is a path pointing to an existing directory or file, resolves its repository root.
    If repo is a repository name, searches in order:
      1. Current repository root if its basename matches repo.
      2. Direct subdirectories of base_dir or current working directory.
      3. Sibling directories under the parent of the current repository root.
      4. Watch directories and immediate subdirectories in TASKCTL_WATCH_REPOS.

    Raises FileNotFoundError if the repository cannot be resolved or does not contain .agent/TASK.md or .git.
    """
    if not repo or not str(repo).strip():
        return find_repo_root(base_dir)

    raw_repo = str(repo).strip()
    expanded = os.path.expanduser(raw_repo)
    candidate_paths = []
    if os.path.isabs(expanded):
        candidate_paths.append(os.path.abspath(expanded))
    else:
        if base_dir:
            candidate_paths.append(os.path.abspath(os.path.join(base_dir, expanded)))
        candidate_paths.append(os.path.abspath(expanded))

    for cand in candidate_paths:
        if os.path.exists(cand):
            target_dir = os.path.dirname(cand) if os.path.isfile(cand) else cand
            root = find_repo_root(target_dir)
            if os.path.exists(os.path.join(root, ".agent", "TASK.md")) or os.path.exists(os.path.join(root, ".git")):
                return root
            if os.path.isdir(target_dir):
                return target_dir

    # Treat repo as a name
    clean_name = raw_repo.rstrip("/\\")
    curr_root = find_repo_root(base_dir)

    # 1. Matches current repo basename
    if os.path.basename(curr_root) == clean_name:
        return curr_root

    # 2. Direct subdirectory in base_dir or cwd
    for search_base in [base_dir, os.getcwd()]:
        if search_base:
            cand = os.path.abspath(os.path.join(search_base, clean_name))
            if os.path.isdir(cand) and (
                os.path.exists(os.path.join(cand, ".agent", "TASK.md"))
                or os.path.exists(os.path.join(cand, ".git"))
            ):
                return cand

    # 3. Sibling directories of the current repository
    parent = os.path.dirname(curr_root)
    if parent and parent != curr_root:
        sibling = os.path.abspath(os.path.join(parent, clean_name))
        if os.path.isdir(sibling) and (
            os.path.exists(os.path.join(sibling, ".agent", "TASK.md"))
            or os.path.exists(os.path.join(sibling, ".git"))
        ):
            return sibling

    # 4. TASKCTL_WATCH_REPOS environment variable
    env_paths = os.environ.get("TASKCTL_WATCH_REPOS", "").strip()
    if env_paths:
        delimiter = ":" if ":" in env_paths and not env_paths.startswith("C:") else ","
        for item in env_paths.split(delimiter):
            p = os.path.abspath(os.path.expanduser(item.strip()))
            if not p or not os.path.isdir(p):
                continue
            if os.path.basename(p) == clean_name and (
                os.path.exists(os.path.join(p, ".agent", "TASK.md"))
                or os.path.exists(os.path.join(p, ".git"))
            ):
                return p
            sub = os.path.join(p, clean_name)
            if os.path.isdir(sub) and (
                os.path.exists(os.path.join(sub, ".agent", "TASK.md"))
                or os.path.exists(os.path.join(sub, ".git"))
            ):
                return sub

    raise FileNotFoundError(
        f"Repository '{repo}' not found or does not contain .agent/TASK.md or .git"
    )

def get_task_file(root_or_path: Optional[str] = None) -> str:
    if root_or_path and os.path.isfile(root_or_path):
        return root_or_path
    root = resolve_repo_path(root_or_path) if root_or_path else find_repo_root()
    path = os.path.join(root, ".agent", "TASK.md")
    if not os.path.exists(path):
        raise FileNotFoundError(f".agent/TASK.md not found in repository root: {root}")
    return path

def extract_dependencies(text: str) -> List[str]:
    """Extract list of task IDs referenced as dependencies from a string."""
    if not text:
        return []
    annotated = re.search(r"\((?:deps|depends|depends on|after):\s*([^\)]+)\)", text, re.IGNORECASE)
    target = annotated.group(1) if annotated else text
    raw_ids = re.findall(r"\[?(\d{2}\.\d+(?:\.\d+)?)\]?", target)
    seen = set()
    deps = []
    for item in raw_ids:
        if item not in seen:
            seen.add(item)
            deps.append(item)
    return deps

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

        deps_match = re.search(r"-\s*\*\*(?:Depends On|Dependencies):\*\*\s*([^\n]+)", content, re.IGNORECASE)
        active_task["dependencies"] = extract_dependencies(deps_match.group(1)) if deps_match else []

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
            m = re.match(r"^-\s*\[([ xX])\]\s*(?:\*\*|`)?\[([^\]]+)\](?:\*\*|`)?\s*(.*)", line.strip())
            if m:
                raw_title = m.group(3).strip()
                deps = extract_dependencies(raw_title)
                clean_title = re.sub(r"\s*\((?:deps|depends|depends on|after):\s*[^\)]+\)", "", raw_title, flags=re.IGNORECASE).strip()
                backlog.append({
                    "checked": m.group(1).lower() == "x",
                    "id": m.group(2).strip(),
                    "title": clean_title,
                    "dependencies": deps,
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
            raw_title = parts[1].strip()
            deps = extract_dependencies(raw_title)
            clean_title = re.sub(r"\s*\((?:deps|depends|depends on|after):\s*[^\)]+\)", "", raw_title, flags=re.IGNORECASE).strip()
            commits = parts[2].strip() if len(parts) > 2 else ""
            date = parts[3].strip() if len(parts) > 3 else ""
            completed.append({
                "id": task_id,
                "title": clean_title,
                "commits": commits,
                "date": date,
                "dependencies": deps,
            })
    return completed
