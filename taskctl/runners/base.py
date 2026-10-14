"""Base classes and data models for pluggable task runners."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class RunnerResult:
    """Standard execution result returned by all runner implementations."""

    runner: str
    task_id: str
    status: str  # "delivered", "executed", "degraded", "skipped", "failed"
    delivered: bool
    target: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to a dictionary representation."""
        return {
            "runner": self.runner,
            "task_id": self.task_id,
            "status": self.status,
            "delivered": self.delivered,
            "target": self.target,
            "output": self.output,
            "error": self.error,
            "details": self.details,
        }


class TaskRunner(ABC):
    """Abstract base class for all taskctl runners."""

    name: str = "base"

    @abstractmethod
    def run(self, task_data: Dict[str, Any], **kwargs: Any) -> RunnerResult:
        """Execute or dispatch the task using the runner backend.

        Args:
            task_data: Dictionary containing task metadata (task_id, title, status,
                       description, systems, runtime_target, repo, repo_path, etc.)
            **kwargs: Extra runner-specific keyword arguments (e.g. target_agent, timeout).

        Returns:
            RunnerResult describing dispatch or execution outcome.
        """
        pass
