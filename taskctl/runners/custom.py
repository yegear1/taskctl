"""Custom shell command template runner adapter."""

import os
import shlex
import subprocess
from typing import Any, Dict, Optional

from taskctl.runners.base import RunnerResult, TaskRunner


class CustomRunner(TaskRunner):
    """Executes a custom shell command template with task metadata interpolation."""

    name: str = "custom"

    def run(self, task_data: Dict[str, Any], **kwargs: Any) -> RunnerResult:
        task_id = str(task_data.get("task_id", ""))
        repo_path = task_data.get("repo_path") or os.getcwd()
        timeout = float(kwargs.get("timeout", 5.0))

        cmd_template = kwargs.get("command") or os.environ.get("TASKCTL_RUNNER_COMMAND")
        if not cmd_template:
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status="failed",
                delivered=False,
                target="custom",
                output=None,
                error="No custom runner command specified. Set TASKCTL_RUNNER_COMMAND or provide command.",
                details={},
            )

        try:
            cmd_str = cmd_template.format(
                task_id=task_id,
                title=task_data.get("title", ""),
                status=task_data.get("status", ""),
                profile=task_data.get("target_profile", ""),
                model=task_data.get("target_model", ""),
                repo=task_data.get("repo", ""),
                repo_path=repo_path,
                description=task_data.get("description", ""),
                systems=task_data.get("systems", ""),
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
                    target=cmd_str,
                    output=res.stdout.strip() if res.stdout else "Executed successfully.",
                    error=None,
                    details={"command": cmd_str, "returncode": 0},
                )
            else:
                err_msg = res.stderr.strip() if res.stderr else f"Command exited with code {res.returncode}"
                return RunnerResult(
                    runner=self.name,
                    task_id=task_id,
                    status="failed",
                    delivered=False,
                    target=cmd_str,
                    output=res.stdout.strip() if res.stdout else None,
                    error=err_msg,
                    details={"command": cmd_str, "returncode": res.returncode},
                )
        except subprocess.TimeoutExpired:
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status="degraded",
                delivered=False,
                target=cmd_template,
                output=None,
                error=f"Custom runner command timed out after {timeout}s",
                details={"command": cmd_template},
            )
        except Exception as e:
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status="failed",
                delivered=False,
                target=cmd_template,
                output=None,
                error=str(e),
                details={"exception": type(e).__name__},
            )
