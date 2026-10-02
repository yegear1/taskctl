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
from dataclasses import dataclass, field
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


@dataclass
class CanvasAgent:
    name: str
    role: str
    prompt: str = ""
    connections: List[str] = field(default_factory=list)
    x: int = 0
    y: int = 0


@dataclass
class CanvasNote:
    name: str
    content: str = ""
    connections: List[str] = field(default_factory=list)
    x: int = 0
    y: int = 0


@dataclass
class CanvasTopology:
    name: str
    preset: str
    agents: List[CanvasAgent] = field(default_factory=list)
    notes: List[CanvasNote] = field(default_factory=list)
    connections: List[Tuple[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def list_topology_presets() -> List[str]:
    """Return available multi-agent canvas topology presets."""
    return ["trinity", "swarm", "audit"]


def get_topology_preset(name: str, workers: int = 3, task_content: str = "") -> CanvasTopology:
    """Generate a configured CanvasTopology preset.

    Supported presets:
      - 'trinity': Triad of Planner, Builder, and Auditor with interconnected verification ropes.
      - 'swarm': Central SwarmLead coordinator wired to N parallel workers.
      - 'audit': Specialized audit squad: ScopeAuditor, TestVerifier, and SecurityAuditor.
    """
    preset_lower = (name or "").strip().lower()
    if preset_lower == "trinity":
        agents = [
            CanvasAgent(
                name="Planner",
                role="Planner",
                prompt="Decompose active tasks into .agent/TASK.md, maintain roadmap invariants, and oversee task strategy.",
                connections=["Builder", "Auditor"],
                x=100,
                y=100,
            ),
            CanvasAgent(
                name="Builder",
                role="Implementer",
                prompt="Implement codebase changes adhering to strict typing, testability, and task acceptance criteria.",
                connections=["Auditor"],
                x=500,
                y=100,
            ),
            CanvasAgent(
                name="Auditor",
                role="Scope Auditor",
                prompt="Execute taskctl audit, verify Definition of Done (DoD), and enforce Conventional Commits policy.",
                connections=[],
                x=900,
                y=100,
            ),
        ]
        notes = [
            CanvasNote(
                name="task-cockpit-agent-task-md",
                content=task_content,
                connections=["Planner", "Builder", "Auditor"],
                x=500,
                y=-200,
            )
        ]
        connections = [
            ("Planner", "Builder"),
            ("Builder", "Auditor"),
            ("Planner", "Auditor"),
            ("task-cockpit-agent-task-md", "Planner"),
            ("task-cockpit-agent-task-md", "Builder"),
            ("task-cockpit-agent-task-md", "Auditor"),
        ]
        return CanvasTopology(
            name="Trinity Triad",
            preset="trinity",
            agents=agents,
            notes=notes,
            connections=connections,
            metadata={"description": "Planner, Builder, and Auditor triad"},
        )

    elif preset_lower == "swarm":
        count = max(1, workers)
        worker_names = [f"Worker-{i+1}" for i in range(count)]
        swarm_lead = CanvasAgent(
            name="SwarmLead",
            role="Coordinator",
            prompt="Coordinate autonomous worker swarm, decompose workloads, and aggregate worker results.",
            connections=list(worker_names),
            x=500,
            y=100,
        )
        agents = [swarm_lead]
        for i in range(count):
            agents.append(
                CanvasAgent(
                    name=f"Worker-{i+1}",
                    role="Worker",
                    prompt=f"Autonomous swarm worker #{i+1}. Execute assigned work slice and report status to SwarmLead.",
                    connections=[],
                    x=150 + i * 220,
                    y=400,
                )
            )
        notes = [
            CanvasNote(
                name="task-cockpit-agent-task-md",
                content=task_content,
                connections=["SwarmLead"],
                x=500,
                y=-200,
            )
        ]
        connections = [
            ("task-cockpit-agent-task-md", "SwarmLead"),
        ]
        for w in worker_names:
            connections.append(("SwarmLead", w))

        return CanvasTopology(
            name=f"Swarm ({count} workers)",
            preset="swarm",
            agents=agents,
            notes=notes,
            connections=connections,
            metadata={"workers": count, "description": f"Swarm coordinator with {count} parallel workers"},
        )

    elif preset_lower == "audit":
        agents = [
            CanvasAgent(
                name="ScopeAuditor",
                role="Scope Auditor",
                prompt="Audit git diff, check modified paths against active task scope, and prevent regressions.",
                connections=["TestVerifier"],
                x=200,
                y=100,
            ),
            CanvasAgent(
                name="TestVerifier",
                role="Test Verifier",
                prompt="Execute automated unit/integration test suites and verify strict typing and clean diffs.",
                connections=["SecurityAuditor"],
                x=600,
                y=100,
            ),
            CanvasAgent(
                name="SecurityAuditor",
                role="Security Auditor",
                prompt="Inspect code for secrets leakage, webhook isolation, and non-blocking network boundaries.",
                connections=[],
                x=1000,
                y=100,
            ),
        ]
        notes = [
            CanvasNote(
                name="task-cockpit-agent-task-md",
                content=task_content,
                connections=["ScopeAuditor", "TestVerifier", "SecurityAuditor"],
                x=600,
                y=-200,
            )
        ]
        connections = [
            ("ScopeAuditor", "TestVerifier"),
            ("TestVerifier", "SecurityAuditor"),
            ("task-cockpit-agent-task-md", "ScopeAuditor"),
            ("task-cockpit-agent-task-md", "TestVerifier"),
            ("task-cockpit-agent-task-md", "SecurityAuditor"),
        ]
        return CanvasTopology(
            name="Audit & Governance Squad",
            preset="audit",
            agents=agents,
            notes=notes,
            connections=connections,
            metadata={"description": "Triad of ScopeAuditor, TestVerifier, and SecurityAuditor"},
        )

    else:
        valid = ", ".join(list_topology_presets())
        raise ValueError(f"Unknown topology preset '{name}'. Valid presets: {valid}")


def apply_topology_to_canvas(
    topology: CanvasTopology,
    dir_path: str,
    workspace_name: str,
    group: Optional[str] = None,
) -> Dict[str, Any]:
    """Deploy and wire a CanvasTopology preset onto the Maestri spatial canvas.

    Creates the workspace, recruits configured agents, creates context notes,
    and establishes connection ropes between components.
    Gracefully degrades if Maestri IPC socket and CLI are not available.
    """
    start_time = time.perf_counter()
    ipc = MaestriIPCClient()
    ipc_avail = ipc.is_available()
    cli_path = resolve_maestri_cli()
    cli_avail = bool(cli_path and os.path.exists(cli_path))

    agents_created: List[str] = []
    notes_created: List[str] = []
    connections_created: List[Tuple[str, str]] = []

    if not ipc_avail and not cli_avail:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        get_telemetry_emitter().record_provider_call(
            provider="maestri",
            operation=f"apply_topology:{topology.preset}",
            duration_ms=duration_ms,
            success=False,
            metadata={"degraded": True, "reason": "No IPC or CLI available"},
        )
        return {
            "success": False,
            "preset": topology.preset,
            "workspace": workspace_name,
            "agents_created": [],
            "notes_created": [],
            "connections_created": [],
            "degraded": True,
            "error": "Maestri IPC socket and CLI unavailable",
        }

    ws_ok = create_workspace_canvas(name=workspace_name, dir_path=dir_path, group=group)

    # 1. Notes
    for note in topology.notes:
        content = note.content
        if not content and note.name == "task-cockpit-agent-task-md":
            task_file = os.path.join(dir_path, ".agent", "TASK.md")
            if os.path.exists(task_file):
                try:
                    with open(task_file, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    content = ""
        ok = sync_task_cockpit_note(content, note_title=note.name)
        if ok:
            notes_created.append(note.name)

    # 2. Agents
    for agent in topology.agents:
        agent_ok = False
        if ipc_avail:
            if agent.prompt:
                ipc.send_request("role_create", {"name": agent.role, "prompt": agent.prompt})
            resp = ipc.send_request(
                "recruit",
                {
                    "name": agent.name,
                    "role": agent.role,
                    "dir": dir_path,
                    "workspace": workspace_name,
                    "x": agent.x,
                    "y": agent.y,
                },
            )
            if resp and resp.get("result"):
                agent_ok = True
        if not agent_ok and cli_avail:
            if agent.prompt:
                run_maestri_cli(["role", "create", agent.role, agent.prompt])
            res_rec = run_maestri_cli(
                ["recruit", agent.name, "--role", agent.role, "--dir", dir_path]
            )
            if res_rec and res_rec.returncode == 0:
                agent_ok = True
        if agent_ok:
            agents_created.append(agent.name)

    # 3. Connections
    for src, dst in topology.connections:
        conn_ok = False
        if ipc_avail:
            resp = ipc.send_request("connect", {"from": src, "to": dst})
            if resp and resp.get("result"):
                conn_ok = True
        if not conn_ok and cli_avail:
            res_conn = run_maestri_cli(["connect", src, dst])
            if res_conn and res_conn.returncode == 0:
                conn_ok = True
        if conn_ok:
            connections_created.append((src, dst))

    duration_ms = (time.perf_counter() - start_time) * 1000.0
    overall_success = ws_ok and (bool(agents_created) or not topology.agents)
    get_telemetry_emitter().record_provider_call(
        provider="maestri",
        operation=f"apply_topology:{topology.preset}",
        duration_ms=duration_ms,
        success=overall_success,
        metadata={
            "workspace": workspace_name,
            "preset": topology.preset,
            "agents_created": len(agents_created),
            "notes_created": len(notes_created),
            "connections_created": len(connections_created),
        },
    )

    return {
        "success": overall_success,
        "preset": topology.preset,
        "workspace": workspace_name,
        "agents_created": agents_created,
        "notes_created": notes_created,
        "connections_created": connections_created,
        "degraded": not overall_success,
    }


def create_workspace_canvas(
    name: str,
    dir_path: str,
    group: Optional[str] = None,
    preset: Optional[str] = None,
    workers: int = 3,
) -> bool:
    """Provision a new workspace on the Maestri canvas rooted at dir_path.

    If preset is specified, automatically generates and applies the topology.
    """
    ipc = MaestriIPCClient()
    ws_created = False
    if ipc.is_available():
        params: Dict[str, Any] = {"name": name, "dir": dir_path}
        if group:
            params["group"] = group
        resp = ipc.send_request("workspace_create", params)
        if resp and resp.get("result"):
            ws_created = True

    if not ws_created:
        args = ["workspace", "create", name, "--dir", dir_path]
        if group:
            args.extend(["--group", group])

        res = run_maestri_cli(args)
        ws_created = bool(res and res.returncode == 0)

    if preset:
        try:
            topo = get_topology_preset(preset, workers=workers)
            res_topo = apply_topology_to_canvas(topo, dir_path=dir_path, workspace_name=name, group=group)
            return bool(ws_created or res_topo.get("success"))
        except Exception:
            return ws_created

    return ws_created


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


@dataclass
class AgentHandoffResult:
    """Result of an autonomous agent lifecycle hand-off dispatch."""
    phase: str
    task_id: str
    target_agent: Optional[str]
    delivered: bool
    response: Optional[str] = None
    error: Optional[str] = None


def dispatch_agent_handoff(
    phase: str,
    task_data: Dict[str, Any],
    target_agent: Optional[str] = None,
    timeout: float = 2.0,
) -> AgentHandoffResult:
    """Dispatch structured lifecycle hand-off context and instructions across canvas agents.

    Phases supported:
      - 'start': Hand-off to builder/implementer agents when task is promoted to RUNNING.
      - 'completion' (or 'done'): Hand-off to auditor/planner agents when task is marked DONE.

    Guarantees non-blocking fail-safe execution if agents or canvas are offline.
    """
    start_time = time.perf_counter()
    task_id = str(task_data.get("task_id", "XX.Y"))
    title = str(task_data.get("title", "Ad-hoc task"))
    normalized_phase = "completion" if phase in ["done", "completion"] else "start"

    # 1. Determine candidate agents
    if target_agent:
        candidates = [target_agent]
    elif normalized_phase == "start":
        candidates = ["Builder", "Implementer", "Worker-1", "SwarmLead"]
    else:
        candidates = ["Auditor", "ScopeAuditor", "TestVerifier", "Planner"]

    # 2. Build structured prompt & ambient canvas notification
    if normalized_phase == "start":
        criteria_list = task_data.get("criteria", [])
        if isinstance(criteria_list, list):
            criteria_str = "\n".join(
                f"- [{'x' if c.get('checked') else ' '}] {c.get('text', '')}"
                if isinstance(c, dict) else f"- {c}"
                for c in criteria_list
            )
        else:
            criteria_str = str(criteria_list)

        prompt = (
            f"[TASK LIFECYCLE HAND-OFF: START]\n"
            f"Task [{task_id}]: {title}\n"
            f"Status: RUNNING\n"
            f"Runtime Target: {task_data.get('runtime_target', 'Profile default')}\n"
            f"Systems Involved: {task_data.get('systems', 'N/A')}\n"
            f"Description: {task_data.get('description', 'N/A')}\n"
            f"Acceptance Criteria:\n{criteria_str if criteria_str else 'N/A'}\n\n"
            f"Instructions:\n"
            f"You are the assigned agent. Implement the task adhering strictly to task criteria, "
            f"maintain Definition of Done (DoD), and avoid scope creep."
        )
        notif_msg = f"🚀 [TASK START] [{task_id}] '{title}' promoted to RUNNING -> Assigned to {candidates[0]}"
    else:
        commit_hash = task_data.get("commit_hash", "HEAD")
        gov_hash = task_data.get("governance_commit", "HEAD")
        prompt = (
            f"[TASK LIFECYCLE HAND-OFF: COMPLETION]\n"
            f"Task [{task_id}]: {title}\n"
            f"Status: DONE\n"
            f"Feature Commit: {commit_hash}\n"
            f"Governance Commit: {gov_hash}\n\n"
            f"Instructions:\n"
            f"Task execution has concluded and changes have been committed. "
            f"Perform post-completion validation, audit checks, or update roadmap planning."
        )
        notif_msg = f"🏁 [TASK DONE] [{task_id}] '{title}' completed -> Hand-off to {candidates[0]} (commit: {commit_hash})"

    # Ambient canvas broadcast (fail-safe)
    send_canvas_notification(notif_msg)

    # 3. Dispatch to candidate agents
    agent_used: Optional[str] = None
    agent_resp: Optional[str] = None
    delivered = False
    error: Optional[str] = None

    for cand in candidates:
        try:
            resp = ask_agent(cand, prompt, timeout=int(timeout))
            if resp is not None:
                agent_used = cand
                agent_resp = resp
                delivered = True
                break
        except Exception as e:
            error = str(e)
            continue

    if not delivered and error is None:
        error = f"No responsive canvas agent found among candidates: {', '.join(candidates)}"

    duration_ms = (time.perf_counter() - start_time) * 1000.0

    # 4. Telemetry
    try:
        emitter = get_telemetry_emitter()
        emitter.record_provider_call(
            provider="maestri",
            operation=f"handoff:{normalized_phase}",
            duration_ms=duration_ms,
            success=delivered,
            metadata={
                "task_id": task_id,
                "target_agent": agent_used,
                "delivered": delivered,
                "candidates": candidates,
            },
        )
        emitter.emit_lifecycle_event(
            event_type="agent_handoff",
            task_id=task_id,
            message=f"Lifecycle hand-off ({normalized_phase}) for [{task_id}]: agent='{agent_used or 'none'}', delivered={delivered}",
            status="DELIVERED" if delivered else "DEGRADED",
            duration_ms=duration_ms,
            level="info" if delivered else "warn",
            details={
                "phase": normalized_phase,
                "target_agent": agent_used,
                "delivered": delivered,
                "error": error if not delivered else None,
            },
        )
    except Exception:
        pass

    return AgentHandoffResult(
        phase=normalized_phase,
        task_id=task_id,
        target_agent=agent_used,
        delivered=delivered,
        response=agent_resp,
        error=error if not delivered else None,
    )


def handoff_task_start(
    task_data: Dict[str, Any],
    target_agent: Optional[str] = None,
    timeout: float = 2.0,
) -> AgentHandoffResult:
    """Convenience helper for task start hand-offs."""
    return dispatch_agent_handoff(
        phase="start",
        task_data=task_data,
        target_agent=target_agent,
        timeout=timeout,
    )


def handoff_task_done(
    task_data: Dict[str, Any],
    target_agent: Optional[str] = None,
    timeout: float = 2.0,
) -> AgentHandoffResult:
    """Convenience helper for task completion hand-offs."""
    return dispatch_agent_handoff(
        phase="completion",
        task_data=task_data,
        target_agent=target_agent,
        timeout=timeout,
    )
