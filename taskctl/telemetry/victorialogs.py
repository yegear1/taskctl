"""VictoriaLogs LogsQL client, cycle trace aggregator, and terminal visualizer.

Provides fail-safe, non-blocking querying of VictoriaLogs via LogsQL, aggregating
complete task cycle spans (cli.next, runner.execute, cli.audit, git commits, cli.done),
blocked commands intercepted by guardrails, and token consumption telemetry.
Features seamless local fallback when offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from taskctl.telemetry.events import get_utc_iso_timestamp
from taskctl.telemetry.tracing import (
    Span,
    Tracer,
    get_tracer,
    load_active_trace,
    normalize_trace_id,
)


def _parse_iso_to_dt(ts: Optional[str]) -> Optional[datetime]:
    """Parse ISO-8601 UTC timestamp string to datetime object."""
    if not ts:
        return None
    clean = ts.strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(clean)
    except Exception:
        return None


class VictoriaLogsClient:
    """Client for querying VictoriaLogs HTTP endpoint via LogsQL."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        timeout: float = 2.0,
    ):
        self.endpoint_url = (endpoint_url or self._resolve_endpoint()).rstrip("/")
        self.timeout = float(os.environ.get("TASKCTL_VICTORIALOGS_TIMEOUT", timeout))

    @staticmethod
    def _resolve_endpoint() -> str:
        """Resolve VictoriaLogs endpoint from environment variables or default."""
        explicit = (
            os.environ.get("TASKCTL_VICTORIALOGS_URL")
            or os.environ.get("VICTORIALOGS_URL")
        )
        if explicit and explicit.strip():
            return explicit.strip()

        host = (
            os.environ.get("VICTORIALOGS_HTTP_HOST")
            or os.environ.get("VICTORIALOGS_HOST")
        )
        if host and host.strip():
            port = (
                os.environ.get("VICTORIALOGS_HTTP_PORT")
                or os.environ.get("VICTORIALOGS_PORT")
                or "9428"
            )
            return f"http://{host.strip()}:{port.strip()}"

        return "http://localhost:9428"

    def is_healthy(self, timeout: float = 1.0) -> bool:
        """Non-blocking health probe. Never raises exceptions."""
        try:
            health_url = f"{self.endpoint_url}/health"
            req = urllib.request.Request(
                health_url,
                headers={"User-Agent": "taskctl-trace/0.2.9"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status in (200, 204)
        except Exception:
            return False

    def query_logsql(
        self,
        query: str,
        limit: int = 200,
        time_range: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a LogsQL query against VictoriaLogs /select/logsql/query.

        Returns parsed JSON records from the NDJSON response stream.
        Guaranteed to be fail-safe and never raise exceptions.
        """
        if not query and not time_range:
            return []

        full_query = query.strip()
        if time_range:
            if "_time:" not in full_query:
                full_query = f"({full_query}) AND _time:{time_range}" if full_query else f"_time:{time_range}"

        params = {
            "query": full_query,
            "limit": str(limit),
        }
        query_string = urllib.parse.urlencode(params)
        url = f"{self.endpoint_url}/select/logsql/query?{query_string}"

        records: List[Dict[str, Any]] = []
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/stream+json, application/json",
                    "User-Agent": "taskctl-trace/0.2.9",
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status not in (200, 204):
                    return []
                for line in resp:
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if not decoded:
                        continue
                    try:
                        record = json.loads(decoded)
                        if isinstance(record, dict):
                            records.append(record)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            if os.environ.get("TASKCTL_TELEMETRY_DEBUG") == "1":
                print(f"[DEBUG VictoriaLogsClient] Query failed: {e}", file=sys.stderr)
            return []

        return records


@dataclass
class TaskCycleSummary:
    """Aggregated representation of a task execution cycle."""
    task_id: str
    trace_id: Optional[str] = None
    status: str = "UNKNOWN"  # "COMPLETED", "IN_PROGRESS", "UNKNOWN"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    total_duration_ms: float = 0.0
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    blocked_commands: List[Dict[str, Any]] = field(default_factory=list)
    tokens: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "timeline": self.timeline,
            "blocked_commands": self.blocked_commands,
            "tokens": self.tokens,
        }


class TaskTraceAggregator:
    """Aggregates lifecycle spans, blocked commands, and token telemetry for a task cycle."""

    def __init__(
        self,
        client: Optional[VictoriaLogsClient] = None,
        tracer: Optional[Tracer] = None,
    ):
        self.client = client or VictoriaLogsClient()
        self.tracer = tracer or get_tracer()

    def aggregate_task_cycle(
        self,
        task_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        time_range: str = "7d",
        repo_root: Optional[str] = None,
    ) -> TaskCycleSummary:
        """Query VictoriaLogs or fallback to local trace spans and session transcripts."""
        norm_task_id = task_id.strip("[]") if task_id else None
        norm_trace_id = normalize_trace_id(trace_id) if trace_id else None

        # Resolve missing IDs from active trace cache or TASK.md
        if not norm_task_id or not norm_trace_id:
            from taskctl.core.parser import parse_task_md, resolve_repo_path

            base_dir = resolve_repo_path(repo_root)
            cached_ctx = load_active_trace(base_dir)
            if cached_ctx:
                if not norm_trace_id:
                    norm_trace_id = cached_ctx.trace_id

            task_file = os.path.join(base_dir, ".agent", "TASK.md")
            if os.path.isfile(task_file):
                try:
                    with open(task_file, "r", encoding="utf-8") as f:
                        active_task, _ = parse_task_md(f.read())
                    if not norm_task_id and active_task.get("id") and active_task.get("id") != "XX.Y":
                        norm_task_id = active_task["id"]
                    if not norm_trace_id and active_task.get("trace_id"):
                        norm_trace_id = normalize_trace_id(active_task["trace_id"])
                except Exception:
                    pass

        target_task = norm_task_id or "XX.Y"
        target_trace = norm_trace_id

        # Query VictoriaLogs if available
        remote_records: List[Dict[str, Any]] = []
        if self.client.is_healthy():
            query_parts = []
            if norm_task_id:
                query_parts.append(f'task_id:"{norm_task_id}"')
            if norm_trace_id:
                query_parts.append(f'trace_id:"{norm_trace_id}"')

            if query_parts:
                vl_query = " OR ".join(query_parts)
                remote_records = self.client.query_logsql(
                    query=vl_query,
                    limit=500,
                    time_range=time_range,
                )

        if remote_records:
            return self._build_summary_from_remote_records(
                task_id=target_task,
                trace_id=target_trace,
                records=remote_records,
                repo_root=repo_root,
            )

        # Local fallback
        return self._build_summary_from_local_fallback(
            task_id=target_task,
            trace_id=target_trace,
            repo_root=repo_root,
        )

    def _build_summary_from_remote_records(
        self,
        task_id: str,
        trace_id: Optional[str],
        records: List[Dict[str, Any]],
        repo_root: Optional[str] = None,
    ) -> TaskCycleSummary:
        """Process VictoriaLogs records into a TaskCycleSummary."""
        spans_raw: List[Dict[str, Any]] = []
        blocked_commands: List[Dict[str, Any]] = []
        token_summary: Dict[str, Any] = {}
        status = "UNKNOWN"

        resolved_trace_id = trace_id

        for r in records:
            if not resolved_trace_id and r.get("trace_id"):
                resolved_trace_id = r.get("trace_id")

            event_type = r.get("event_type")
            msg = r.get("message") or ""
            details = r.get("details") or {}
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except Exception:
                    details = {}

            # Blocked commands extraction
            decision = (details.get("decision") or r.get("decision") or "").upper()
            is_blocked = (
                event_type == "command_blocked"
                or decision in ("DENY", "BLOCK")
                or "blocked" in msg.lower()
            )
            if is_blocked and (details.get("command") or r.get("command") or "command" in msg.lower()):
                cmd_str = details.get("command") or r.get("command") or msg
                risk = details.get("risk_level") or r.get("risk_level") or details.get("level") or "CRITICAL"
                score = float(details.get("score") or details.get("risk_score") or r.get("score") or 0.0)
                reason = details.get("reason") or details.get("message") or msg
                ts = r.get("timestamp") or details.get("timestamp") or get_utc_iso_timestamp()
                blocked_commands.append({
                    "command": cmd_str,
                    "risk_level": str(risk).upper(),
                    "score": score,
                    "reason": reason,
                    "timestamp": ts,
                })

            # Spans extraction
            if event_type == "span" or "span_name" in details or ("duration_ms" in r and r.get("span_id")):
                span_name = details.get("span_name") or r.get("span_name") or msg
                m = re.match(r"Span\s+\[([^\]]+)\]", msg)
                if m:
                    span_name = m.group(1)

                spans_raw.append({
                    "name": span_name,
                    "span_id": r.get("span_id") or details.get("span_id") or "00000000",
                    "parent_span_id": r.get("parent_span_id") or details.get("parent_span_id"),
                    "duration_ms": float(r.get("duration_ms") or details.get("duration_ms") or 0.0),
                    "status": (details.get("status") or r.get("status") or "OK").upper(),
                    "timestamp": r.get("timestamp") or get_utc_iso_timestamp(),
                })
            elif event_type in ("task_started", "task_completed", "audit", "runner_dispatched"):
                # Lifecycle events synthesized as phase markers if needed
                phase_name = f"cli.{event_type.replace('task_', '')}"
                spans_raw.append({
                    "name": phase_name,
                    "span_id": r.get("span_id") or "00000000",
                    "parent_span_id": r.get("parent_span_id"),
                    "duration_ms": float(r.get("duration_ms") or 0.0),
                    "status": (details.get("status") or "OK").upper(),
                    "timestamp": r.get("timestamp") or get_utc_iso_timestamp(),
                })

            # Token summary extraction if present in remote events
            if event_type == "token_telemetry_summary" or "token_telemetry" in details:
                token_summary = details.get("summary") or details

            # Status determination
            if event_type == "task_completed" or "cli.done" in msg:
                status = "COMPLETED"
            elif event_type == "task_started" and status != "COMPLETED":
                status = "IN_PROGRESS"

        # If no tokens in remote records, fallback to local token aggregator
        if not token_summary:
            token_summary = self._collect_local_tokens(repo_root)

        timeline, start_ts, end_ts, total_dur = self._build_timeline(spans_raw)
        if any(item.get("name") == "cli.done" for item in timeline):
            status = "COMPLETED"
        elif any(item.get("name") == "cli.next" for item in timeline) and status != "COMPLETED":
            status = "IN_PROGRESS"

        return TaskCycleSummary(
            task_id=task_id,
            trace_id=resolved_trace_id,
            status=status,
            start_time=start_ts,
            end_time=end_ts,
            total_duration_ms=total_dur,
            timeline=timeline,
            blocked_commands=blocked_commands,
            tokens=token_summary,
        )

    def _build_summary_from_local_fallback(
        self,
        task_id: str,
        trace_id: Optional[str],
        repo_root: Optional[str] = None,
    ) -> TaskCycleSummary:
        """Synthesize TaskCycleSummary from in-memory spans and local token records."""
        completed_spans = self.tracer.get_completed_spans()
        selected_spans: List[Span] = []

        for s in completed_spans:
            if trace_id and s.trace_id == trace_id:
                selected_spans.append(s)
            elif task_id and task_id != "XX.Y" and str(s.tags.get("task_id")) == task_id:
                selected_spans.append(s)

        if not selected_spans and not trace_id and not task_id:
            selected_spans = completed_spans

        spans_raw: List[Dict[str, Any]] = []
        blocked_commands: List[Dict[str, Any]] = []
        resolved_trace_id = trace_id

        for s in selected_spans:
            if not resolved_trace_id:
                resolved_trace_id = s.trace_id

            spans_raw.append({
                "name": s.name,
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "duration_ms": s.duration_ms,
                "status": s.status,
                "timestamp": get_utc_iso_timestamp(),
            })

            # Check if span has blocked command event or tag
            for ev in s.events:
                if ev.name == "command_blocked" or "deny" in str(ev.attributes.get("decision", "")).lower():
                    blocked_commands.append({
                        "command": ev.attributes.get("command", "unknown"),
                        "risk_level": str(ev.attributes.get("risk_level", "CRITICAL")).upper(),
                        "score": float(ev.attributes.get("score", 0.0)),
                        "reason": ev.attributes.get("reason", "Intercepted by guardrail"),
                        "timestamp": ev.timestamp,
                    })

        timeline, start_ts, end_ts, total_dur = self._build_timeline(spans_raw)
        status = "UNKNOWN"
        if any(item.get("name") == "cli.done" for item in timeline):
            status = "COMPLETED"
        elif any(item.get("name") == "cli.next" for item in timeline):
            status = "IN_PROGRESS"

        token_summary = self._collect_local_tokens(repo_root)

        return TaskCycleSummary(
            task_id=task_id,
            trace_id=resolved_trace_id,
            status=status,
            start_time=start_ts,
            end_time=end_ts,
            total_duration_ms=total_dur,
            timeline=timeline,
            blocked_commands=blocked_commands,
            tokens=token_summary,
        )

    def _build_timeline(
        self,
        spans_raw: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str], float]:
        """Normalize spans into ordered timeline with relative offsets."""
        if not spans_raw:
            return [], None, None, 0.0

        # Canonical execution phase order for stabilization
        phase_priority = {
            "cli.next": 10,
            "runner.execute": 20,
            "cli.audit": 30,
            "git.feature_commit": 40,
            "git.governance_commit": 50,
            "provider.handoff_done": 60,
            "cli.done": 70,
        }

        # Deduplicate and sort spans
        dedup_spans: List[Dict[str, Any]] = []
        seen = set()
        for s in spans_raw:
            key = (s["name"], s.get("span_id"))
            if key not in seen:
                seen.add(key)
                dedup_spans.append(s)

        # Sort by timestamp, then by canonical phase priority
        def sort_key(s: Dict[str, Any]):
            ts = _parse_iso_to_dt(s.get("timestamp"))
            ts_val = ts.timestamp() if ts else 0.0
            prio = phase_priority.get(s["name"], 99)
            return (ts_val, prio)

        dedup_spans.sort(key=sort_key)

        start_dt = _parse_iso_to_dt(dedup_spans[0].get("timestamp"))
        t0_sec = start_dt.timestamp() if start_dt else 0.0

        timeline: List[Dict[str, Any]] = []
        accumulated_ms = 0.0

        for s in dedup_spans:
            cur_dt = _parse_iso_to_dt(s.get("timestamp"))
            if cur_dt and start_dt and cur_dt >= start_dt:
                offset_sec = cur_dt.timestamp() - t0_sec
            else:
                offset_sec = accumulated_ms / 1000.0

            dur_ms = s.get("duration_ms", 0.0)
            accumulated_ms += dur_ms

            timeline.append({
                "name": s["name"],
                "span_id": s.get("span_id", "00000000"),
                "parent_span_id": s.get("parent_span_id"),
                "duration_ms": round(dur_ms, 2),
                "offset": f"+{offset_sec:.2f}s",
                "offset_seconds": round(offset_sec, 2),
                "status": s.get("status", "OK"),
            })

        start_time_str = dedup_spans[0].get("timestamp")
        end_time_str = dedup_spans[-1].get("timestamp")
        total_duration_ms = max(accumulated_ms, sum(item["duration_ms"] for item in timeline))

        return timeline, start_time_str, end_time_str, round(total_duration_ms, 2)

    def _collect_local_tokens(self, repo_root: Optional[str] = None) -> Dict[str, Any]:
        """Collect local token telemetry partitioned by role."""
        try:
            from taskctl.telemetry.tokens import collect_token_telemetry

            sessions, aggs = collect_token_telemetry(
                repo_filter=repo_root,
                use_cache=True,
                save_cache=False,
            )

            total_tokens = sum(a.total_tokens for a in aggs)
            prompt_tokens = sum(a.prompt_tokens for a in aggs)
            completion_tokens = sum(a.completion_tokens for a in aggs)
            thinking_tokens = sum(a.thinking_tokens for a in aggs)
            turns = sum(a.turns for a in aggs)
            tool_calls = sum(a.tool_calls for a in aggs)

            role_breakdown = [
                {
                    "role": a.role,
                    "profile": a.profile,
                    "tokens": a.total_tokens,
                    "turns": a.turns,
                    "tools": a.tool_calls,
                }
                for a in aggs
            ]

            return {
                "total_tokens": total_tokens,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "thinking_tokens": thinking_tokens,
                "turns": turns,
                "tool_calls": tool_calls,
                "role_breakdown": role_breakdown,
            }
        except Exception:
            return {
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "thinking_tokens": 0,
                "turns": 0,
                "tool_calls": 0,
                "role_breakdown": [],
            }


def render_cycle_waterfall(summary: TaskCycleSummary) -> str:
    """Render clean ASCII waterfall timeline with duration bars and status badges."""
    if not summary.timeline:
        return "  (No phase execution spans recorded)"

    lines = []
    total = len(summary.timeline)
    for idx, item in enumerate(summary.timeline):
        connector = "└── " if idx == total - 1 else "├── "
        status_icon = "✅" if item["status"] == "OK" else "❌"
        name_pad = f"[{item['name']}]".ljust(26)
        offset = item.get("offset", "+0.00s").rjust(7)
        dur = f"({item['duration_ms']:>7.2f}ms)"
        badge = f"[{item['status'].lower()}]"
        lines.append(f"{connector}{status_icon} {name_pad} {offset}  {dur} {badge}")

    return "\n".join(lines)


def render_cycle_summary(summary: TaskCycleSummary) -> str:
    """Render combined terminal dashboard view for taskctl trace."""
    lines = []
    width = 62
    lines.append("=" * width)
    lines.append(f" ⏱️  TASK CYCLE LIFECYCLE TRACE: [{summary.task_id}] ({summary.status})")
    if summary.trace_id:
        lines.append(f" Trace ID: {summary.trace_id}")
    lines.append(f" Duration: {summary.total_duration_ms:.2f}ms | Spans: {len(summary.timeline)}")
    lines.append("=" * width)

    # Timeline section
    lines.append("\nPHASE TIMELINE (t0 -> t1):")
    lines.append(render_cycle_waterfall(summary))

    # Blocked commands section
    lines.append("\n" + "-" * width)
    if summary.blocked_commands:
        lines.append(f"🛡️  BLOCKED COMMANDS INTERCEPTED ({len(summary.blocked_commands)}):")
        total_blocked = len(summary.blocked_commands)
        for i, cmd in enumerate(summary.blocked_commands):
            conn = "└── " if i == total_blocked - 1 else "├── "
            child_prefix = "    " if i == total_blocked - 1 else "│   "
            score_str = f"Score: {cmd['score']:.1f}" if cmd['score'] else "Policy Deny"
            lines.append(f"{conn}⛔ \"{cmd['command']}\" [{cmd['risk_level']} | {score_str}]")
            lines.append(f"{child_prefix}   Reason: {cmd['reason']}")
            lines.append(f"{child_prefix}   Time  : {cmd['timestamp']}")
    else:
        lines.append("🛡️  BLOCKED COMMANDS: None (All guardrail checks passed)")

    # Token summary section
    lines.append("-" * width)
    tokens = summary.tokens or {}
    total_tok = tokens.get("total_tokens", 0)
    prompt_tok = tokens.get("prompt_tokens", 0)
    comp_tok = tokens.get("completion_tokens", 0)
    think_tok = tokens.get("thinking_tokens", 0)
    turns = tokens.get("turns", 0)
    tools = tokens.get("tool_calls", 0)

    lines.append("🪙 TOKEN CONSUMPTION SUMMARY:")
    lines.append(
        f" Total Tokens : {total_tok:,} "
        f"(Prompt: {prompt_tok:,} | Completion: {comp_tok:,} | Thinking: {think_tok:,})"
    )
    lines.append(f" Turns: {turns} | Tool Calls: {tools}")

    roles = tokens.get("role_breakdown", [])
    if roles:
        lines.append(" Role Breakdown:")
        for r in roles:
            role_name = r.get("role", "Unknown")
            r_tokens = r.get("tokens", 0)
            r_turns = r.get("turns", 0)
            r_tools = r.get("tools", 0)
            lines.append(f"   • {role_name:<18}: {r_tokens:>7,} tokens ({r_turns} turns, {r_tools} tools)")

    lines.append("=" * width + "\n")
    return "\n".join(lines)
