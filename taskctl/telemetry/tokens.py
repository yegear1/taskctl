"""Multi-Agent Token Telemetry Collector & Role Breakdown.

Parses local agent session transcripts (Google Antigravity transcript.jsonl,
Claude Code sessions, terminal scrollbacks) and correlates them with Maestri
canvas metadata and persona directives to compute token consumption partitioned
by (Profile, Role).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import glob
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple


def _chars_to_tokens(text: str) -> int:
    """Approximate token count from raw text (approx 4 chars/token)."""
    if not text:
        return 0
    return max(1, int(round(len(text) / 4.0)))


@dataclass
class SessionTokenRecord:
    """Tokens and turn telemetry for a single agent session / conversation."""
    session_id: str
    profile: str
    role: str
    agent_type: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thinking_tokens: int = 0
    total_tokens: int = 0
    turns: int = 0
    tool_calls: int = 0
    repo: Optional[str] = None
    first_active: Optional[str] = None
    last_active: Optional[str] = None
    file_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "profile": self.profile,
            "role": self.role,
            "agent_type": self.agent_type,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "thinking_tokens": self.thinking_tokens,
            "total_tokens": self.total_tokens,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "repo": self.repo,
            "first_active": self.first_active,
            "last_active": self.last_active,
            "file_path": self.file_path,
        }


@dataclass
class RoleTokenAggregation:
    """Aggregated token telemetry group by Profile and Role."""
    profile: str
    role: str
    agent_type: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thinking_tokens: int = 0
    total_tokens: int = 0
    turns: int = 0
    tool_calls: int = 0
    sessions_count: int = 0
    last_active: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile,
            "role": self.role,
            "agent_type": self.agent_type,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "thinking_tokens": self.thinking_tokens,
            "total_tokens": self.total_tokens,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "sessions_count": self.sessions_count,
            "last_active": self.last_active,
        }


def detect_role_from_text(text: str) -> Optional[str]:
    """Detect agent role from system prompt, persona directives, or prompt headers."""
    if not text:
        return None

    lower = text.lower()
    if "security auditor" in lower or "security & vulnerability auditor" in lower or "role: security auditor" in lower:
        return "Security Auditor"
    if "scope auditor" in lower or "task & scope auditor" in lower or "role: scope auditor" in lower:
        return "Scope Auditor"
    if "auditor" in lower or "taskctl audit" in lower or "audit report" in lower:
        return "Scope Auditor"
    if "sentinel" in lower and ("aether-guard" in lower or "shield" in lower or "role: sentinel" in lower):
        return "Sentinel"
    if "orchestrator" in lower or "maestro" in lower or "role: orchestrator" in lower:
        return "Orchestrator"
    if "planner" in lower and ("role: planner" in lower or "task planner" in lower or "requirements decomposition" in lower or ".agent/task.md" in lower or "planner agent" in lower):
        return "Planner"
    if "developer" in lower or "software developer" in lower or "system implementer" in lower or "role: developer" in lower:
        return "Developer"

    return None


def resolve_maestri_workspace_terminal_roles() -> Dict[str, Dict[str, str]]:
    """Scan available Maestri workspaces to build a map of (workingDirectory, profile) -> role."""
    mapping: Dict[str, Dict[str, str]] = {}
    candidates = [
        os.path.expanduser("~/.maestri/workspaces"),
        os.environ.get("MAESTRI_DATA_DIR", ""),
    ]

    if os.path.exists("/mnt/c/Users"):
        for u in os.listdir("/mnt/c/Users"):
            upath = os.path.join("/mnt/c/Users", u, ".maestri", "workspaces")
            if os.path.isdir(upath):
                candidates.append(upath)

    for base_dir in candidates:
        if not base_dir or not os.path.isdir(base_dir):
            continue
        for ws_dir in os.listdir(base_dir):
            ws_json = os.path.join(base_dir, ws_dir, "workspace.json")
            if not os.path.isfile(ws_json):
                continue
            try:
                with open(ws_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                payload = data.get("payload", {})
                nodes = payload.get("nodes", [])
                for node in nodes:
                    content = node.get("content", {})
                    terminal = content.get("terminal", {}).get("_0", {})
                    term_name = terminal.get("name")
                    working_dir = terminal.get("workingDirectory")
                    command = terminal.get("command", "")
                    if term_name and working_dir:
                        prof = "default"
                        m = re.search(r"multigravity\s+agent\s+run\s+([a-zA-Z0-9_\-]+)", command)
                        if m:
                            prof = m.group(1)
                        norm_dir = os.path.abspath(working_dir)
                        if norm_dir not in mapping:
                            mapping[norm_dir] = {}
                        mapping[norm_dir][prof] = term_name
            except Exception:
                continue

    return mapping


def parse_antigravity_transcript(transcript_path: str, default_profile: str = "yegear") -> Optional[SessionTokenRecord]:
    """Parse a single Antigravity transcript.jsonl file into a SessionTokenRecord."""
    if not os.path.isfile(transcript_path):
        return None

    parts = transcript_path.replace("\\", "/").split("/")
    conv_id = "unknown"
    for i, p in enumerate(parts):
        if p == "brain" and i + 1 < len(parts):
            conv_id = parts[i + 1]
            break

    profile = default_profile
    for i, p in enumerate(parts):
        if p == "AntigravityProfiles" and i + 1 < len(parts):
            profile = parts[i + 1]
            break

    prompt_tokens = 0
    completion_tokens = 0
    thinking_tokens = 0
    turns = 0
    tool_calls = 0
    first_active: Optional[str] = None
    last_active: Optional[str] = None
    detected_role: Optional[str] = None
    detected_repo: Optional[str] = None

    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    step = json.loads(line)
                except Exception:
                    continue

                ts = step.get("created_at")
                if ts:
                    if not first_active:
                        first_active = ts
                    last_active = ts

                stype = step.get("type")
                source = step.get("source")
                content = step.get("content") or ""
                thinking = step.get("thinking") or ""
                calls = step.get("tool_calls") or []

                if not detected_repo and "file://" in content:
                    m = re.search(r"file://([^\s\"'>]+)", content)
                    if m:
                        detected_repo = m.group(1)

                if not detected_role:
                    role_candidate = detect_role_from_text(content)
                    if role_candidate:
                        detected_role = role_candidate

                if stype == "USER_INPUT" or source == "USER_EXPLICIT":
                    turns += 1
                    prompt_tokens += _chars_to_tokens(content)
                elif stype == "PLANNER_RESPONSE" or source == "MODEL":
                    if content:
                        completion_tokens += _chars_to_tokens(content)
                    if thinking:
                        thinking_tokens += _chars_to_tokens(thinking)
                    if calls:
                        tool_calls += len(calls)
                        for c in calls:
                            args_str = json.dumps(c.get("args", {}))
                            completion_tokens += _chars_to_tokens(args_str)
                elif stype == "GENERIC":
                    prompt_tokens += _chars_to_tokens(content)

    except Exception:
        return None

    if turns == 0 and prompt_tokens == 0 and completion_tokens == 0:
        return None

    if detected_role:
        agent_type = "agy-cli"
    else:
        detected_role = "IDE Assistant"
        agent_type = "antigravity-ide"

    total = prompt_tokens + completion_tokens + thinking_tokens
    return SessionTokenRecord(
        session_id=conv_id,
        profile=profile,
        role=detected_role,
        agent_type=agent_type,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        thinking_tokens=thinking_tokens,
        total_tokens=total,
        turns=turns,
        tool_calls=tool_calls,
        repo=detected_repo,
        first_active=first_active,
        last_active=last_active,
        file_path=transcript_path,
    )


def parse_scrollback_terminal(scrollback_path: str, profile: str = "default", role: str = "Terminal") -> Optional[SessionTokenRecord]:
    """Parse raw ANSI scrollback file as fallback token estimation."""
    if not os.path.isfile(scrollback_path) or os.path.getsize(scrollback_path) == 0:
        return None

    fname = os.path.basename(scrollback_path)
    term_id = fname.replace(".scrollback", "")

    try:
        with open(scrollback_path, "r", encoding="utf-8", errors="replace") as f:
            raw_text = f.read()

        clean_text = re.sub(r"\[[0-9;]*[a-zA-Z]", "", raw_text)
        if not clean_text.strip():
            return None

        total = _chars_to_tokens(clean_text)
        prompt = int(total * 0.6)
        completion = max(0, total - prompt)
        mtime = datetime.fromtimestamp(os.path.getmtime(scrollback_path), timezone.utc).isoformat()

        return SessionTokenRecord(
            session_id=term_id,
            profile=profile,
            role=role,
            agent_type="custom",
            prompt_tokens=prompt,
            completion_tokens=completion,
            thinking_tokens=0,
            total_tokens=total,
            turns=1,
            tool_calls=0,
            first_active=mtime,
            last_active=mtime,
            file_path=scrollback_path,
        )
    except Exception:
        return None


def get_token_cache_path() -> str:
    """Resolve standard token telemetry cache filepath."""
    candidates = [
        os.path.expanduser("~/.maestri/usage"),
        os.environ.get("MAESTRI_DATA_DIR", ""),
    ]
    if os.path.exists("/mnt/c/Users"):
        for u in os.listdir("/mnt/c/Users"):
            upath = os.path.join("/mnt/c/Users", u, ".maestri", "usage")
            if os.path.isdir(upath):
                candidates.append(upath)

    for c in candidates:
        if c and os.path.isdir(c):
            return os.path.join(c, "token-telemetry.json")

    cache_dir = os.path.expanduser("~/.cache/taskctl")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "token-telemetry.json")


def save_token_telemetry_cache(
    aggregations: List[RoleTokenAggregation],
    sessions: Optional[List[SessionTokenRecord]] = None,
    cache_path: Optional[str] = None,
) -> str:
    """Persist aggregated token telemetry to cache file atomically."""
    target_path = cache_path or get_token_cache_path()
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    payload: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_profiles": len(set(a.profile for a in aggregations)),
            "total_roles": len(aggregations),
            "total_tokens": sum(a.total_tokens for a in aggregations),
            "prompt_tokens": sum(a.prompt_tokens for a in aggregations),
            "completion_tokens": sum(a.completion_tokens for a in aggregations),
            "thinking_tokens": sum(a.thinking_tokens for a in aggregations),
            "turns": sum(a.turns for a in aggregations),
            "tool_calls": sum(a.tool_calls for a in aggregations),
        },
        "aggregations": [a.to_dict() for a in aggregations],
    }
    if sessions is not None:
        payload["sessions"] = [s.to_dict() for s in sessions]

    tmp_path = f"{target_path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, target_path)
    return target_path


def load_token_telemetry_cache(
    max_age_seconds: float = 300.0,
    cache_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load token telemetry from cache if existing and within max_age_seconds."""
    target_path = cache_path or get_token_cache_path()
    if not os.path.isfile(target_path):
        return None

    try:
        mtime = os.path.getmtime(target_path)
        age = time.time() - mtime
        if age > max_age_seconds:
            return None

        with open(target_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def collect_token_telemetry(
    profile_filter: Optional[str] = None,
    role_filter: Optional[str] = None,
    repo_filter: Optional[str] = None,
    search_limit_per_profile: int = 100,
    use_cache: bool = False,
    max_cache_age: float = 300.0,
    save_cache: bool = True,
) -> Tuple[List[SessionTokenRecord], List[RoleTokenAggregation]]:
    """Discover, parse, and aggregate token usage across all profiles and agent sessions."""
    if use_cache:
        cached = load_token_telemetry_cache(max_age_seconds=max_cache_age)
        if cached and "aggregations" in cached:
            aggs = [
                RoleTokenAggregation(
                    profile=item["profile"],
                    role=item["role"],
                    agent_type=item.get("agent_type", "agy"),
                    prompt_tokens=item.get("prompt_tokens", 0),
                    completion_tokens=item.get("completion_tokens", 0),
                    thinking_tokens=item.get("thinking_tokens", 0),
                    total_tokens=item.get("total_tokens", 0),
                    turns=item.get("turns", 0),
                    tool_calls=item.get("tool_calls", 0),
                    sessions_count=item.get("sessions_count", 0),
                    last_active=item.get("last_active"),
                )
                for item in cached["aggregations"]
                if (not profile_filter or item["profile"].lower() == profile_filter.lower())
                and (not role_filter or item["role"].lower() == role_filter.lower())
            ]
            sess_list: List[SessionTokenRecord] = []
            if "sessions" in cached:
                sess_list = [
                    SessionTokenRecord(
                        session_id=s["session_id"],
                        profile=s["profile"],
                        role=s["role"],
                        agent_type=s.get("agent_type", "agy"),
                        prompt_tokens=s.get("prompt_tokens", 0),
                        completion_tokens=s.get("completion_tokens", 0),
                        thinking_tokens=s.get("thinking_tokens", 0),
                        total_tokens=s.get("total_tokens", 0),
                        turns=s.get("turns", 0),
                        tool_calls=s.get("tool_calls", 0),
                        repo=s.get("repo"),
                        first_active=s.get("first_active"),
                        last_active=s.get("last_active"),
                        file_path=s.get("file_path"),
                    )
                    for s in cached["sessions"]
                    if (not profile_filter or s["profile"].lower() == profile_filter.lower())
                    and (not role_filter or s["role"].lower() == role_filter.lower())
                    and (not repo_filter or (s.get("repo") and repo_filter.lower() in s["repo"].lower()))
                ]
            return sess_list, aggs

    sessions: List[SessionTokenRecord] = []
    workspace_role_map = resolve_maestri_workspace_terminal_roles()

    home_dir = os.path.expanduser("~")
    real_home = os.environ.get("REAL_HOME", home_dir)
    profile_dirs: Dict[str, str] = {}

    candidates = [
        os.path.join(home_dir, "AntigravityProfiles"),
        os.path.join(real_home, "AntigravityProfiles"),
        "/home/yegear/AntigravityProfiles",
    ]

    for c in candidates:
        if os.path.isdir(c):
            for entry in os.listdir(c):
                p_path = os.path.join(c, entry)
                if os.path.isdir(p_path) and entry not in profile_dirs:
                    profile_dirs[entry] = p_path

    if "yegear" not in profile_dirs and os.path.isdir(os.path.join(real_home, ".gemini")):
        profile_dirs["yegear"] = real_home

    for p_name, p_dir in profile_dirs.items():
        if profile_filter and p_name.lower() != profile_filter.lower():
            continue

        pattern = os.path.join(p_dir, ".gemini", "antigravity", "brain", "*", ".system_generated", "logs", "transcript.jsonl")
        transcripts = glob.glob(pattern)

        transcripts.sort(key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True)
        selected = transcripts[:search_limit_per_profile]

        for t_path in selected:
            record = parse_antigravity_transcript(t_path, default_profile=p_name)
            if not record:
                continue

            if record.repo and record.repo in workspace_role_map:
                p_roles = workspace_role_map[record.repo]
                if record.profile in p_roles:
                    record.role = p_roles[record.profile]
                    record.agent_type = "agy-cli"

            if role_filter and record.role.lower() != role_filter.lower():
                continue
            if repo_filter and record.repo and repo_filter.lower() not in record.repo.lower():
                continue

            sessions.append(record)

    agg_map: Dict[Tuple[str, str, str], RoleTokenAggregation] = {}
    for s in sessions:
        key = (s.profile, s.role, s.agent_type)
        if key not in agg_map:
            agg_map[key] = RoleTokenAggregation(
                profile=s.profile,
                role=s.role,
                agent_type=s.agent_type,
                prompt_tokens=0,
                completion_tokens=0,
                thinking_tokens=0,
                total_tokens=0,
                turns=0,
                tool_calls=0,
                sessions_count=0,
                last_active=s.last_active,
            )

        agg = agg_map[key]
        agg.prompt_tokens += s.prompt_tokens
        agg.completion_tokens += s.completion_tokens
        agg.thinking_tokens += s.thinking_tokens
        agg.total_tokens += s.total_tokens
        agg.turns += s.turns
        agg.tool_calls += s.tool_calls
        agg.sessions_count += 1
        if s.last_active and (not agg.last_active or s.last_active > agg.last_active):
            agg.last_active = s.last_active

    aggregations = sorted(agg_map.values(), key=lambda a: a.total_tokens, reverse=True)

    if save_cache and not profile_filter and not role_filter and not repo_filter:
        try:
            save_token_telemetry_cache(aggregations, sessions)
        except Exception:
            pass

    return sessions, aggregations

