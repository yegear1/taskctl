"""Multigravity profile and worktree runner adapter."""

import os
import shlex
import shutil
import subprocess
from typing import Any, Dict, Optional

from taskctl.providers.multigravity import route_target
from taskctl.runners.base import RunnerResult, TaskRunner


class MultigravityRunner(TaskRunner):
    """Dispatches task execution to Multigravity multi-profile runtime / worktrees."""

    name: str = "multigravity"

    def run(self, task_data: Dict[str, Any], **kwargs: Any) -> RunnerResult:
        task_id = str(task_data.get("task_id", ""))
        profile = task_data.get("target_profile")
        model = task_data.get("target_model")
        weight = kwargs.get("weight") or task_data.get("weight", "medium")
        timeout = float(kwargs.get("timeout", 5.0))

        if not profile or not model:
            best_p, best_m, _ = route_target(weight=weight)
            profile = profile or best_p
            model = model or best_m

        target_label = f"Profile '{profile}' | Model: '{model}'"

        # Check for explicit custom command or default binary
        cmd_template = os.environ.get("TASKCTL_MULTIGRAVITY_CMD")
        repo_path = task_data.get("repo_path") or os.getcwd()

        try:
            if cmd_template:
                cmd_str = cmd_template.format(
                    task_id=task_id,
                    title=task_data.get("title", ""),
                    profile=profile,
                    model=model,
                    repo=task_data.get("repo", ""),
                    repo_path=repo_path,
                )
                args = shlex.split(cmd_str)
                res = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=repo_path,
                    check=False,
                )
                if res.returncode == 0:
                    return RunnerResult(
                        runner=self.name,
                        task_id=task_id,
                        status="executed",
                        delivered=True,
                        target=target_label,
                        output=res.stdout.strip() if res.stdout else "Executed successfully.",
                        error=None,
                        details={"profile": profile, "model": model, "command": cmd_str},
                    )
                else:
                    err_msg = res.stderr.strip() if res.stderr else f"Command exited with code {res.returncode}"
                    return RunnerResult(
                        runner=self.name,
                        task_id=task_id,
                        status="degraded",
                        delivered=False,
                        target=target_label,
                        output=res.stdout.strip() if res.stdout else None,
                        error=err_msg,
                        details={"profile": profile, "model": model, "returncode": res.returncode},
                    )

            # Check if multigravity CLI is available
            mg_bin = shutil.which("multigravity")
            if mg_bin:
                cmd = [mg_bin, "run", "--profile", profile, "--task", task_id]
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=repo_path,
                    check=False,
                )
                if res.returncode == 0:
                    return RunnerResult(
                        runner=self.name,
                        task_id=task_id,
                        status="executed",
                        delivered=True,
                        target=target_label,
                        output=res.stdout.strip() if res.stdout else "Dispatched to Multigravity.",
                        error=None,
                        details={"profile": profile, "model": model},
                    )
                else:
                    err_msg = res.stderr.strip() if res.stderr else f"multigravity exited with code {res.returncode}"
                    return RunnerResult(
                        runner=self.name,
                        task_id=task_id,
                        status="degraded",
                        delivered=False,
                        target=target_label,
                        output=res.stdout.strip() if res.stdout else None,
                        error=err_msg,
                        details={"profile": profile, "model": model, "returncode": res.returncode},
                    )

            # Graceful fallback when CLI is not installed
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status="degraded",
                delivered=False,
                target=target_label,
                output=None,
                error="multigravity CLI binary not found in PATH; task routed locally",
                details={"profile": profile, "model": model},
            )

        except subprocess.TimeoutExpired:
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status="degraded",
                delivered=False,
                target=target_label,
                output=None,
                error=f"multigravity dispatch timed out after {timeout}s",
                details={"profile": profile, "model": model},
            )
        except Exception as e:
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status="degraded",
                delivered=False,
                target=target_label,
                output=None,
                error=str(e),
                details={"exception": type(e).__name__},
            )
