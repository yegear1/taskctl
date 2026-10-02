"""Maestri Canvas, Role Workspace & Socket Integration Provider."""

import os
import sys
import glob
import json
import re
import socket
import shutil
import subprocess
import time
from typing import Optional, List, Dict, Any, Tuple

from taskctl.telemetry import get_telemetry_emitter

MAESTRI_CLI_PATHS = [
    os.path.expanduser("~/.local/bin/maestri"),
    "/usr/local/bin/maestri",
    shutil.which("maestri") or "",
]


def resolve_maestri_cli() -> Optional[str]:
    """Resolve the path to the maestri executable."""
    env_cli = os.environ.get("MAESTRI_CLI")
    if env_cli and os.path.isfile(env_cli) and os.access(env_cli, os.X_OK):
        return env_cli

    for path in MAESTRI_CLI_PATHS:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def resolve_maestri_socket() -> Optional[str]:
    """Resolve active Maestri UNIX domain socket path."""
    env_sock = os.environ.get("MAESTRI_SOCKET_PATH") or os.environ.get("MAESTRI_SOCKET")
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


class MaestriIPCClient:
    """UNIX Domain Socket JSON-RPC / IPC client for Maestri canvas."""

    def __init__(self, socket_path: Optional[str] = None, timeout: float = 2.0):
        self._socket_path = socket_path
        self.timeout = timeout

    @property
    def socket_path(self) -> Optional[str]:
        if self._socket_path and os.path.exists(self._socket_path):
            return self._socket_path
        resolved = resolve_maestri_socket()
        if resolved:
            self._socket_path = resolved
        return self._socket_path

    def is_available(self) -> bool:
        path = self.socket_path
        return bool(path and os.path.exists(path))

    def send_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Send a JSON-RPC request over the domain socket with fail-safe error handling."""
        path = self.socket_path
        if not path or not os.path.exists(path):
            return None

        effective_timeout = timeout if timeout is not None else self.timeout
        start_time = time.perf_counter()
        success = False
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": method,
            "params": params or {},
        }

        client_sock: Optional[socket.socket] = None
        try:
            client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_sock.settimeout(effective_timeout)
            client_sock.connect(path)

            msg_bytes = (json.dumps(payload) + "\n").encode("utf-8")
            client_sock.sendall(msg_bytes)

            chunks: List[bytes] = []
            while True:
                chunk = client_sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break

            raw = b"".join(chunks).decode("utf-8").strip()
            if not raw:
                return None

            resp = json.loads(raw)
            success = "error" not in resp
            return resp
        except Exception:
            return None
        finally:
            if client_sock:
                try:
                    client_sock.close()
                except Exception:
                    pass
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            get_telemetry_emitter().record_provider_call(
                provider="maestri",
                operation=f"ipc:{method}",
                duration_ms=duration_ms,
                success=success,
            )


def run_maestri_cli(args: List[str], timeout: float = 10.0) -> Optional[subprocess.CompletedProcess]:
    """Execute a command using the maestri CLI with fail-safe telemetry."""
    cli = resolve_maestri_cli()
    sock = resolve_maestri_socket()

    if not cli or not sock:
        return None

    cmd = [cli] + args
    env = os.environ.copy()
    env["MAESTRI_SOCKET"] = sock
    env["MAESTRI_SOCKET_PATH"] = sock

    start_time = time.perf_counter()
    success = False
    returncode = -1
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
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


def strip_note_line_numbers(text: str) -> str:
    """Strip line numbers from 'maestri note read' outputs if formatted with prefixes."""
    lines = text.splitlines()
    if not lines:
        return ""
    pattern = re.compile(r"^\s*\d+\s*[|:]\s?(.*)$")
    matching_lines = [pattern.match(l) for l in lines if l.strip()]
    if matching_lines and len(matching_lines) >= len([l for l in lines if l.strip()]) * 0.7:
        cleaned = []
        for l in lines:
            m = pattern.match(l)
            cleaned.append(m.group(1) if m else l)
        return "\n".join(cleaned)
    return text


def sync_task_cockpit_note(task_content: str, note_title: str = "task-cockpit-agent-task-md") -> bool:
    """Sync task contract to Maestri canvas note, creating it if needed."""
    ipc = MaestriIPCClient()
    if ipc.is_available():
        resp = ipc.send_request("note_write", {"name": note_title, "content": task_content})
        if resp and resp.get("result"):
            return True
        resp_create = ipc.send_request("note_create", {"name": note_title, "content": task_content})
        if resp_create and resp_create.get("result"):
            return True

    # CLI Fallback: Try writing to existing note
    res_write = run_maestri_cli(["note", "write", note_title, task_content])
    if res_write and res_write.returncode == 0:
        return True

    # Try creating the note with pinned name
    res_create = run_maestri_cli(["note", "create", task_content, "--name", note_title])
    if res_create and res_create.returncode == 0:
        return True

    # Backward compatibility with older 'note update' verb
    res_update = run_maestri_cli(["note", "update", note_title, task_content])
    if res_update and res_update.returncode == 0:
        return True

    # Fallback to secondary spec note title if custom title failed
    if note_title != "task-spec":
        res_spec = run_maestri_cli(["note", "write", "task-spec", task_content])
        if res_spec and res_spec.returncode == 0:
            return True
        res_spec_create = run_maestri_cli(["note", "create", task_content, "--name", "task-spec"])
        if res_spec_create and res_spec_create.returncode == 0:
            return True
        res_spec_legacy = run_maestri_cli(["note", "update", "task-spec", task_content])
        return bool(res_spec_legacy and res_spec_legacy.returncode == 0)

    return False


def pull_task_cockpit_note(note_title: str = "task-cockpit-agent-task-md") -> Optional[str]:
    """Pull task contract markdown from Maestri canvas note."""
    ipc = MaestriIPCClient()
    if ipc.is_available():
        resp = ipc.send_request("note_read", {"name": note_title})
        if resp and isinstance(resp.get("result"), dict) and "content" in resp["result"]:
            return strip_note_line_numbers(str(resp["result"]["content"]))

    res = run_maestri_cli(["note", "read", note_title])
    if res and res.returncode == 0 and res.stdout.strip():
        return strip_note_line_numbers(res.stdout.strip())

    if note_title != "task-spec":
        res_spec = run_maestri_cli(["note", "read", "task-spec"])
        if res_spec and res_spec.returncode == 0 and res_spec.stdout.strip():
            return strip_note_line_numbers(res_spec.stdout.strip())

    return None


def send_canvas_notification(message: str) -> bool:
    """Send system notification to Maestri canvas."""
    ipc = MaestriIPCClient()
    if ipc.is_available():
        resp = ipc.send_request("notify", {"message": message})
        if resp and resp.get("result"):
            return True

    res = run_maestri_cli(["notify", message])
    return bool(res and res.returncode == 0)


def create_workspace_canvas(name: str, dir_path: str, group: Optional[str] = None) -> bool:
    """Provision a new workspace on the Maestri canvas rooted at dir_path."""
    ipc = MaestriIPCClient()
    if ipc.is_available():
        params: Dict[str, Any] = {"name": name, "dir": dir_path}
        if group:
            params["group"] = group
        resp = ipc.send_request("workspace_create", params)
        if resp and resp.get("result"):
            return True

    args = ["workspace", "create", name, "--dir", dir_path]
    if group:
        args.extend(["--group", group])

    res = run_maestri_cli(args)
    return bool(res and res.returncode == 0)


def ask_agent(agent_name: str, prompt: str, timeout: int = 60) -> Optional[str]:
    """Send prompt to a connected agent on the Maestri canvas and retrieve response."""
    ipc = MaestriIPCClient()
    if ipc.is_available():
        resp = ipc.send_request("ask", {"name": agent_name, "prompt": prompt}, timeout=float(timeout))
        if resp and isinstance(resp.get("result"), dict) and "output" in resp["result"]:
            return str(resp["result"]["output"]).strip()

    res = run_maestri_cli(["ask", agent_name, prompt], timeout=float(timeout))
    if res and res.returncode == 0:
        return res.stdout.strip()

    return None
