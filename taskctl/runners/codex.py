"""Codex / headless code agent runner adapter."""

import os
import shlex
import shutil
import subprocess
from typing import Any, Dict, Optional

from taskctl.runners.base import RunnerResult, TaskRunner


class CodexRunner(TaskRunner):
    """Dispatches task execution to OpenAI Codex or headless code agents."""

    name: str = "codex"

    def run(self, task_data: Dict[str, Any], **kwargs: Any) -> RunnerResult:
        task_id = str(task_data.get("task_id", ""))
        title = task_data.get("title", "")
        repo_path = task_data.get("repo_path") or os.getcwd()
        timeout = float(kwargs.get("timeout", 5.0))
        target_model = task_data.get("target_model", "codex")

        cmd_template = os.environ.get("TASKCTL_CODEX_CMD")

        child_env = os.environ.copy()
        trace_id = task_data.get("trace_id") or os.environ.get("MAESTRI_TRACE_ID") or os.environ.get("TASKCTL_TRACE_ID")
        traceparent = task_data.get("traceparent") or os.environ.get("TRACEPARENT")
        if trace_id:
            child_env["MAESTRI_TRACE_ID"] = trace_id
            child_env["TASKCTL_TRACE_ID"] = trace_id
        if traceparent:
            child_env["TRACEPARENT"] = traceparent

        try:
            if cmd_template:
                cmd_str = cmd_template.format(
                    task_id=task_id,
                    title=title,
                    description=task_data.get("description", ""),
                    model=target_model,
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
                    env=child_env,
                    check=False,
                )
                if res.returncode == 0:
                    return RunnerResult(
                        runner=self.name,
                        task_id=task_id,
                        status="executed",
                        delivered=True,
                        target=target_model,
                        output=res.stdout.strip() if res.stdout else "Codex runner executed successfully.",
                        error=None,
                        details={"command": cmd_str},
                    )
                else:
                    err_msg = res.stderr.strip() if res.stderr else f"Codex runner exited with code {res.returncode}"
                    return RunnerResult(
                        runner=self.name,
                        task_id=task_id,
                        status="degraded",
                        delivered=False,
                        target=target_model,
                        output=res.stdout.strip() if res.stdout else None,
                        error=err_msg,
                        details={"returncode": res.returncode},
                    )

            # Check if codex CLI binary exists in PATH
            codex_bin = shutil.which("codex")
            if codex_bin:
                cmd = [codex_bin, "run", "--task", task_id]
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=repo_path,
                    env=child_env,
                    check=False,
                )
                if res.returncode == 0:
                    return RunnerResult(
                        runner=self.name,
                        task_id=task_id,
                        status="executed",
                        delivered=True,
                        target=target_model,
                        output=res.stdout.strip() if res.stdout else "Codex execution initiated.",
                        error=None,
                        details={"bin": codex_bin},
                    )
                else:
                    err_msg = res.stderr.strip() if res.stderr else f"codex CLI exited with code {res.returncode}"
                    return RunnerResult(
                        runner=self.name,
                        task_id=task_id,
                        status="degraded",
                        delivered=False,
                        target=target_model,
                        output=res.stdout.strip() if res.stdout else None,
                        error=err_msg,
                        details={"returncode": res.returncode},
                    )

            # Degraded fallback when binary is missing
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status="degraded",
                delivered=False,
                target=target_model,
                output=None,
                error="Codex runner binary or TASKCTL_CODEX_CMD not found",
                details={},
            )

        except subprocess.TimeoutExpired:
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status="degraded",
                delivered=False,
                target=target_model,
                output=None,
                error=f"Codex runner timed out after {timeout}s",
                details={},
            )
        except Exception as e:
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status="degraded",
                delivered=False,
                target=target_model,
                output=None,
                error=str(e),
                details={"exception": type(e).__name__},
            )
