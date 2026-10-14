"""Pluggable runner registry and resolution."""

import os
from typing import Dict, List, Optional, Type

from taskctl.runners.base import TaskRunner
from taskctl.runners.codex import CodexRunner
from taskctl.runners.custom import CustomRunner
from taskctl.runners.maestri import MaestriRunner
from taskctl.runners.multigravity import MultigravityRunner

_REGISTRY: Dict[str, Type[TaskRunner]] = {
    "maestri": MaestriRunner,
    "multigravity": MultigravityRunner,
    "codex": CodexRunner,
    "custom": CustomRunner,
}


def register_runner(name: str, runner_cls: Type[TaskRunner]) -> None:
    """Register a custom or external runner class."""
    _REGISTRY[name.lower().strip()] = runner_cls


def list_runners() -> List[str]:
    """Return the list of all registered runner identifiers."""
    return sorted(list(_REGISTRY.keys()))


def get_runner(name: Optional[str] = None) -> TaskRunner:
    """Resolve and instantiate a runner by name or environment fallback.

    Resolution hierarchy:
    1. Explicit `name` argument.
    2. Environment variable `TASKCTL_DEFAULT_RUNNER`.
    3. Default to 'maestri' for backward compatibility.
    """
    resolved = name or os.environ.get("TASKCTL_DEFAULT_RUNNER") or "maestri"
    key = resolved.lower().strip()

    if key not in _REGISTRY:
        available = ", ".join(list_runners())
        raise ValueError(f"Unknown runner '{resolved}'. Available runners: {available}")

    return _REGISTRY[key]()
