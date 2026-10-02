"""Maestri Canvas, Role Workspace & Socket Integration Provider."""

import os
import sys
import glob
import shutil
import subprocess
import time
from typing import Optional, List, Dict, Any

from taskctl.telemetry import get_telemetry_emitter

MAESTRI_CLI_PATHS = [
    os.path.expanduser("~/.local/bin/maestri"),
    "/usr/local/bin/maestri",
    shutil.which("maestri") or "",
]

def resolve_maestri_cli() -> Optional[str]:
    for path in MAESTRI_CLI_PATHS:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None

def resolve_maestri_socket() -> Optional[str]:
    env_sock = os.environ.get("MAESTRI_SOCKET")
    if env_sock and os.path.exists(env_sock):
        return env_sock

    uid = os.getuid() if hasattr(os, "getuid") else None
    if uid is not None:
        direct = f"/tmp/maestri-{uid}/maestri.sock"
        if os.path.exists(direct):
            return direct

    matches = glob.glob("/tmp/maestri-*/maestri.sock")
    if matches:
        return matches[0]

    return None

def run_maestri_cli(args: List[str]) -> Optional[subprocess.CompletedProcess]:
    cli = resolve_maestri_cli()
    sock = resolve_maestri_socket()

    if not cli or not sock:
        return None

    cmd = [cli] + args
    env = os.environ.copy()
    env["MAESTRI_SOCKET"] = sock

    start_time = time.perf_counter()
    success = False
    returncode = -1
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
            env=env,
        )
        returncode = res.returncode
        success = (res.returncode == 0)
        return res
    except Exception as e:
        print(f"[Maestri CLI Error] {e}", file=sys.stderr)
        return None
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        get_telemetry_emitter().record_provider_call(
            provider="maestri",
            operation=" ".join(args),
            duration_ms=duration_ms,
            success=success,
            metadata={"returncode": returncode},
        )

def sync_task_cockpit_note(task_content: str, note_title: str = "task-cockpit-agent-task-md") -> bool:
    res = run_maestri_cli(["note", "update", note_title, task_content])
    if res and res.returncode == 0:
        return True

    res_spec = run_maestri_cli(["note", "update", "task-spec", task_content])
    return bool(res_spec and res_spec.returncode == 0)
