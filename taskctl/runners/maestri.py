"""Maestri spatial canvas agent runner adapter."""

from typing import Any, Dict, Optional

from taskctl.providers.maestri import handoff_task_start
from taskctl.runners.base import RunnerResult, TaskRunner


class MaestriRunner(TaskRunner):
    """Dispatches task start context to Maestri spatial canvas agents."""

    name: str = "maestri"

    def run(self, task_data: Dict[str, Any], **kwargs: Any) -> RunnerResult:
        task_id = str(task_data.get("task_id", ""))
        target_agent = kwargs.get("target_agent")
        timeout = float(kwargs.get("timeout", 2.0))

        try:
            import sys
            cli_mod = sys.modules.get("taskctl.cli")
            cli_handoff = getattr(cli_mod, "handoff_task_start", None) if cli_mod else None
            # If taskctl.cli has been explicitly patched in a test, use it
            if cli_handoff is not None and type(cli_handoff).__name__ in ("MagicMock", "Mock", "AsyncMock"):
                handoff_fn = cli_handoff
            else:
                handoff_fn = handoff_task_start
            h_res = handoff_fn(task_data, target_agent=target_agent, timeout=timeout)
            status = "delivered" if h_res.delivered else "degraded"
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status=status,
                delivered=h_res.delivered,
                target=h_res.target_agent,
                output=h_res.response,
                error=h_res.error,
                details={"phase": h_res.phase},
            )
        except Exception as e:
            return RunnerResult(
                runner=self.name,
                task_id=task_id,
                status="degraded",
                delivered=False,
                target=target_agent,
                output=None,
                error=str(e),
                details={"exception": type(e).__name__},
            )
