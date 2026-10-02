"""Cross-repo workspace discovery, state tracking, and lifecycle event aggregator."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from taskctl.core.parser import find_repo_root, parse_task_md, parse_completed_tasks
from taskctl.telemetry.events import get_utc_iso_timestamp


@dataclass
class WorkspaceState:
    """Snapshot of a repository workspace and its active task contract."""
    repo_path: str
    repo_name: str
    task_file_path: str
    task_id: Optional[str] = None
    task_title: Optional[str] = None
    task_status: Optional[str] = None
    target_model: Optional[str] = None
    systems: Optional[str] = None
    criteria_total: int = 0
    criteria_checked: int = 0
    completed_count: int = 0
    backlog_count: int = 0
    last_mtime: float = 0.0
    last_commit_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo_path": self.repo_path,
            "repo_name": self.repo_name,
            "task_file_path": self.task_file_path,
            "task_id": self.task_id,
            "task_title": self.task_title,
            "task_status": self.task_status,
            "target_model": self.target_model,
            "systems": self.systems,
            "criteria_total": self.criteria_total,
            "criteria_checked": self.criteria_checked,
            "completed_count": self.completed_count,
            "backlog_count": self.backlog_count,
            "last_mtime": self.last_mtime,
            "last_commit_hash": self.last_commit_hash,
        }


@dataclass
class WorkspaceEvent:
    """A lifecycle transition or contract delta detected across workspaces."""
    event_type: str
    repo_path: str
    repo_name: str
    message: str
    task_id: Optional[str] = None
    task_title: Optional[str] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=get_utc_iso_timestamp)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "event_type": self.event_type,
            "repo_path": self.repo_path,
            "repo_name": self.repo_name,
            "message": self.message,
            "timestamp": self.timestamp,
        }
        if self.task_id is not None:
            payload["task_id"] = self.task_id
        if self.task_title is not None:
            payload["task_title"] = self.task_title
        if self.old_status is not None:
            payload["old_status"] = self.old_status
        if self.new_status is not None:
            payload["new_status"] = self.new_status
        if self.details:
            payload["details"] = self.details
        return payload


class CrossRepoAggregator:
    """Discovers, scans, and monitors task lifecycle states across multiple repositories."""

    def __init__(self, watch_paths: Optional[List[str]] = None):
        self.watch_paths = self._resolve_watch_paths(watch_paths)
        self._last_states: Optional[Dict[str, WorkspaceState]] = None

    @staticmethod
    def _resolve_watch_paths(paths: Optional[List[str]]) -> List[str]:
        if paths:
            return [os.path.abspath(p) for p in paths if p.strip()]

        env_paths = os.environ.get("TASKCTL_WATCH_REPOS", "").strip()
        if env_paths:
            delimiter = ":" if ":" in env_paths and not env_paths.startswith("C:") else ","
            resolved = []
            for item in env_paths.split(delimiter):
                cleaned = item.strip()
                if cleaned:
                    resolved.append(os.path.abspath(cleaned))
            if resolved:
                return resolved

        # Default fallback to current repository root
        return [os.path.abspath(find_repo_root())]

    def discover_repositories(self) -> List[str]:
        """Discover valid repository workspaces (directories containing .agent/TASK.md)."""
        discovered: Dict[str, bool] = {}

        for base_path in self.watch_paths:
            if not os.path.exists(base_path):
                continue

            base_path = os.path.abspath(base_path)

            # Check if base_path is itself a repository with .agent/TASK.md
            task_md = os.path.join(base_path, ".agent", "TASK.md")
            if os.path.isfile(task_md):
                discovered[base_path] = True
                continue

            # Otherwise, scan immediate subdirectories (depth 1)
            try:
                with os.scandir(base_path) as entries:
                    for entry in entries:
                        if entry.is_dir() and not entry.name.startswith("."):
                            sub_task_md = os.path.join(entry.path, ".agent", "TASK.md")
                            if os.path.isfile(sub_task_md):
                                discovered[os.path.abspath(entry.path)] = True
            except (PermissionError, OSError):
                pass

        return sorted(list(discovered.keys()))

    @staticmethod
    def _get_git_commit(repo_path: str) -> Optional[str]:
        """Retrieve short git HEAD commit hash, fail-safe."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=repo_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=1.5,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return None

    def scan_workspace(self, repo_path: str) -> Optional[WorkspaceState]:
        """Parse and extract current workspace state from .agent/TASK.md."""
        task_file = os.path.join(repo_path, ".agent", "TASK.md")
        if not os.path.isfile(task_file):
            return None

        try:
            mtime = os.path.getmtime(task_file)
            with open(task_file, "r", encoding="utf-8") as f:
                content = f.read()

            active_task, backlog = parse_task_md(content)
            completed_tasks = parse_completed_tasks(content)
            commit_hash = self._get_git_commit(repo_path)
            repo_name = os.path.basename(os.path.abspath(repo_path))

            criteria = active_task.get("criteria", [])
            criteria_total = len(criteria)
            criteria_checked = sum(1 for c in criteria if c.get("checked", False))

            return WorkspaceState(
                repo_path=repo_path,
                repo_name=repo_name,
                task_file_path=task_file,
                task_id=active_task.get("id"),
                task_title=active_task.get("title"),
                task_status=active_task.get("status"),
                target_model=active_task.get("target"),
                systems=active_task.get("systems"),
                criteria_total=criteria_total,
                criteria_checked=criteria_checked,
                completed_count=len(completed_tasks),
                backlog_count=len(backlog),
                last_mtime=mtime,
                last_commit_hash=commit_hash,
            )
        except Exception:
            return None

    def scan_workspaces(self) -> Dict[str, WorkspaceState]:
        """Scan all discovered workspaces and return their current states."""
        states: Dict[str, WorkspaceState] = {}
        for repo_path in self.discover_repositories():
            state = self.scan_workspace(repo_path)
            if state:
                states[repo_path] = state
        return states

    def poll(self) -> List[WorkspaceEvent]:
        """Poll all workspaces and generate events for detected changes/transitions."""
        current_states = self.scan_workspaces()
        events: List[WorkspaceEvent] = []

        if self._last_states is None:
            # First poll: generate initial snapshot events
            for repo_path, state in current_states.items():
                status_str = state.task_status or "UNKNOWN"
                task_id_str = f"[{state.task_id}] " if state.task_id else ""
                events.append(
                    WorkspaceEvent(
                        event_type="workspace_snapshot",
                        repo_path=repo_path,
                        repo_name=state.repo_name,
                        task_id=state.task_id,
                        task_title=state.task_title,
                        new_status=state.task_status,
                        message=f"Workspace '{state.repo_name}' initial state: {task_id_str}{state.task_title or 'No active task'} ({status_str})",
                        details=state.to_dict(),
                    )
                )
            self._last_states = current_states
            return events

        # Compare current against last known states
        for repo_path, curr in current_states.items():
            if repo_path not in self._last_states:
                # Newly added workspace
                events.append(
                    WorkspaceEvent(
                        event_type="workspace_added",
                        repo_path=repo_path,
                        repo_name=curr.repo_name,
                        task_id=curr.task_id,
                        task_title=curr.task_title,
                        new_status=curr.task_status,
                        message=f"Discovered new workspace '{curr.repo_name}' with active task [{curr.task_id}]",
                        details=curr.to_dict(),
                    )
                )
                continue

            old = self._last_states[repo_path]

            # 1. Active task changed (new task started or completed and swapped)
            if old.task_id != curr.task_id:
                events.append(
                    WorkspaceEvent(
                        event_type="task_switched",
                        repo_path=repo_path,
                        repo_name=curr.repo_name,
                        task_id=curr.task_id,
                        task_title=curr.task_title,
                        old_status=old.task_status,
                        new_status=curr.task_status,
                        message=f"Workspace '{curr.repo_name}' switched active task from [{old.task_id}] to [{curr.task_id}] ({curr.task_status})",
                        details={
                            "previous_task_id": old.task_id,
                            "previous_task_title": old.task_title,
                            "current_task": curr.to_dict(),
                        },
                    )
                )

            # 2. Status transition on same task
            elif old.task_status != curr.task_status:
                events.append(
                    WorkspaceEvent(
                        event_type="task_status_changed",
                        repo_path=repo_path,
                        repo_name=curr.repo_name,
                        task_id=curr.task_id,
                        task_title=curr.task_title,
                        old_status=old.task_status,
                        new_status=curr.task_status,
                        message=f"Workspace '{curr.repo_name}' task [{curr.task_id}] transitioned from '{old.task_status}' to '{curr.task_status}'",
                        details={
                            "old_status": old.task_status,
                            "new_status": curr.task_status,
                            "commit": curr.last_commit_hash,
                        },
                    )
                )

            # 3. Acceptance criteria checked count changed
            elif (old.criteria_checked != curr.criteria_checked) or (old.criteria_total != curr.criteria_total):
                events.append(
                    WorkspaceEvent(
                        event_type="criteria_updated",
                        repo_path=repo_path,
                        repo_name=curr.repo_name,
                        task_id=curr.task_id,
                        task_title=curr.task_title,
                        new_status=curr.task_status,
                        message=f"Workspace '{curr.repo_name}' task [{curr.task_id}] progress: {curr.criteria_checked}/{curr.criteria_total} criteria verified",
                        details={
                            "criteria_checked": curr.criteria_checked,
                            "criteria_total": curr.criteria_total,
                        },
                    )
                )

            # 4. Completed tasks count increased (task completed)
            elif curr.completed_count > old.completed_count:
                events.append(
                    WorkspaceEvent(
                        event_type="task_completed",
                        repo_path=repo_path,
                        repo_name=curr.repo_name,
                        task_id=old.task_id,
                        task_title=old.task_title,
                        new_status="DONE",
                        message=f"Workspace '{curr.repo_name}' completed a task (total completed: {curr.completed_count})",
                        details={
                            "completed_count": curr.completed_count,
                            "commit": curr.last_commit_hash,
                        },
                    )
                )

            # 5. File touched or commit changed without status delta
            elif old.last_commit_hash != curr.last_commit_hash:
                events.append(
                    WorkspaceEvent(
                        event_type="workspace_commit",
                        repo_path=repo_path,
                        repo_name=curr.repo_name,
                        task_id=curr.task_id,
                        task_title=curr.task_title,
                        new_status=curr.task_status,
                        message=f"Workspace '{curr.repo_name}' commit updated to {curr.last_commit_hash}",
                        details={
                            "old_commit": old.last_commit_hash,
                            "new_commit": curr.last_commit_hash,
                        },
                    )
                )

        self._last_states = current_states
        return events

    def get_summary(self) -> Dict[str, Any]:
        """Aggregate cross-workspace status summary roll-up."""
        states = self.scan_workspaces()
        status_counts: Dict[str, int] = {}
        active_tasks: List[Dict[str, Any]] = []

        for path, state in states.items():
            status = (state.task_status or "UNKNOWN").upper()
            status_counts[status] = status_counts.get(status, 0) + 1
            active_tasks.append({
                "repo_name": state.repo_name,
                "repo_path": state.repo_path,
                "task_id": state.task_id,
                "task_title": state.task_title,
                "task_status": state.task_status,
                "progress": f"{state.criteria_checked}/{state.criteria_total}",
                "completed": state.completed_count,
                "backlog": state.backlog_count,
                "commit": state.last_commit_hash or "N/A",
            })

        return {
            "total_workspaces": len(states),
            "status_counts": status_counts,
            "active_tasks": active_tasks,
            "workspaces": {p: s.to_dict() for p, s in states.items()},
            "timestamp": get_utc_iso_timestamp(),
        }
