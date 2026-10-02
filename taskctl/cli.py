#!/usr/bin/env python3
"""
taskctl - Task Lifecycle, Contract Engine & Multi-Agent CLI.

Commands:
  taskctl ws [name] [--preset <name>] [--workers <n>]
                           Create and wire Maestri workspace for current repo with
                           optional multi-agent topology preset (trinity, swarm, audit).
  taskctl init             Initialize .agent/TASK.md and AGENTS.md in current repository.
  taskctl status           Show active task, criteria, git status, and quota route.
  taskctl quota            Display real-time Multigravity quota across all profiles.
  taskctl plan "<prompt>"  Ask the Planner agent to decompose tasks into .agent/TASK.md.
  taskctl next [--weight] [--agent <name>] [--no-handoff]
                           Promote next backlog task to active (RUNNING) and dispatch
                           lifecycle hand-off context to Builder agent.
  taskctl audit [--delegate] [--agent <name>]
                           Trigger Scope Auditor to verify diff with optional canvas
                           agent delegation fallback.
                           Returns semantic exit codes:
                             0: [APPROVED] - Ready for taskctl done.
                             1: [CHANGES REQUIRED] - Prints Required Action for auto-remediation.
                             2: [REJECTED] - Critical failure; escalates to Planner/human.
  taskctl done [msg] [-p] [--agent <name>] [--no-handoff]
                           Validate DoD, create double atomic commit (code + governance),
                           dispatch completion hand-off to Auditor/Planner, and trigger webhooks.
  taskctl lint-commit [msg] [--file <path>] [--rev <rev>] [--range <range>] [--head]
                           Validate commit message against Conventional Commits.
  taskctl sync             Sync current .agent/TASK.md to canvas note.
  taskctl backlog          List upcoming backlog items.
  taskctl graph [--tree] [--mermaid] [--json] [--check-cycles] [--file <path>]
                           Visualize task dependency DAG (ASCII tree, Mermaid, JSON, cycle detector).
  taskctl dashboard [--snapshot] [--interval <sec>] [--tests] [--split] [--dag]
                           Launch interactive terminal dashboard prototype displaying
                           active task contract status, DoD checklist, and scope audit.
                           (Alias: taskctl tui)
  taskctl daemon [--watch <path>...] [--interval <sec>] [--once] [--json]
                           Run cross-repo telemetry aggregation daemon to monitor multiple
                           workspaces and broadcast live events to Vector, Canvas, and Webhooks.
  taskctl broadcast [msg] [--watch <path>...] [--json]
                           Aggregate cross-repo status roll-up and broadcast to configured sinks.
  taskctl trace [--last] [--id <trace_id>] [--json] [--analytics]
                           Display distributed trace spans, waterfall tree, and SLA duration metrics.
  taskctl notify <msg>     Send an ad-hoc notification via configured webhook.
"""

import os
import sys

if __package__ is None or __package__ == "":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from taskctl.core.parser import find_repo_root, get_task_file, parse_task_md
from taskctl.core.auditor import ScopeAuditor, AuditSeverity
from taskctl.core.commits import parse_conventional_commit
from taskctl.providers.multigravity import get_profile_quotas, route_target
from taskctl.providers.maestri import (
    resolve_maestri_cli,
    resolve_maestri_socket,
    run_maestri_cli,
    sync_task_cockpit_note,
    pull_task_cockpit_note,
    send_canvas_notification,
    create_workspace_canvas,
    ask_agent,
    list_topology_presets,
    get_topology_preset,
    apply_topology_to_canvas,
    AgentHandoffResult,
    dispatch_agent_handoff,
    handoff_task_start,
    handoff_task_done,
)
from taskctl.webhooks.dispatcher import WebhookDispatcher
from taskctl.telemetry import (
    get_telemetry_emitter,
    TelemetryEvent,
    CrossRepoAggregator,
    TelemetryBroadcaster,
    TelemetryDaemon,
    get_tracer,
    TraceContext,
    Span,
    DurationAnalyzer,
)
from taskctl.tui import Dashboard

def run_cmd(cmd_str: str, check: bool = False, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd_str,
        shell=True,
        text=True,
        capture_output=capture,
        check=check,
    )

def cmd_init():
    root = find_repo_root()
    agent_dir = os.path.join(root, ".agent")
    os.makedirs(agent_dir, exist_ok=True)
    task_file = os.path.join(agent_dir, "TASK.md")
    created = []
    if not os.path.exists(task_file):
        with open(task_file, "w", encoding="utf-8") as f:
            f.write("""# Tasks & Roadmap

### 📌 Task [XX.Y]: [Short descriptive title]

- **Description:** [Awaiting next planned task]
- **Systems Involved:** []
- **Runtime Target:** Profile 'yegear' | Model: 'gemini-3.8-flash-medium'
- **Action Type:**
  - [ ] Source code changes
- **Status:** READY FOR PLANNING

### Acceptance Criteria
- [ ] Criteria pending next task promotion

---

## Backlog

- [ ] **[01.1]** [First planned task]

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
""")
        created.append(".agent/TASK.md")

    agents_file = os.path.join(root, "AGENTS.md")
    if not os.path.exists(agents_file):
        with open(agents_file, "w", encoding="utf-8") as f:
            f.write("""# Engineering Standards & Agent Directives

## 1. Falsifiable Definition of Done (DoD)
- All automated unit and integration tests must exit with code 0.
- Linter and typecheck commands must pass with zero errors.
- `git diff --check` must be clean (no trailing whitespace or conflict markers).

## 2. Golden Rules (Non-Negotiable)
- **Strict Typing:** No `any` or loose signatures. Strict types required across all modules.
- **Architecture Boundaries:** Business logic belongs in service/domain layers, not HTTP controllers/handlers.
- **Cleanliness:** No placeholder mocks, dead code, syntax errors, or unresolved `TODO` comments.
- **Scope Discipline:** Modify only files directly required for the active task. No unsolicited mass refactorings.
""")
        created.append("AGENTS.md")

    if created:
        print(f"[OK] Initialized template-agent contracts in {root}: {', '.join(created)}")
    else:
        print(f"[OK] Repository in {root} already has .agent/TASK.md and AGENTS.md.")

def cmd_status():
    try:
        task_file = get_task_file()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    with open(task_file, "r", encoding="utf-8") as f:
        content = f.read()

    active_task, backlog = parse_task_md(content)

    print("\n" + "="*50)
    print(" 🎯 ACTIVE TASK COCKPIT")
    print("="*50)

    if not active_task:
        print("No active task defined in .agent/TASK.md.")
    else:
        print(f"Task ID      : [{active_task.get('id', 'N/A')}]")
        print(f"Title        : {active_task.get('title', 'N/A')}")
        print(f"Status       : {active_task.get('status', 'N/A')}")
        print(f"Target       : {active_task.get('target', 'N/A')}")
        print(f"Systems      : {active_task.get('systems', 'N/A')}")
        print(f"Description  : {active_task.get('description', 'N/A')}")
        if active_task.get("dependencies"):
            deps_str = ", ".join(f"[{d}]" for d in active_task.get("dependencies"))
            print(f"Dependencies : {deps_str}")
        print("\nCriteria:")
        for c in active_task.get("criteria", []):
            mark = "✔" if c["checked"] else " "
            print(f"  [{mark}] {c['text']}")

    print("\n" + "="*50)
    print(" 🌿 GIT WORKBENCH STATUS")
    print("="*50)
    git_stat = run_cmd("git status -s").stdout.strip()
    if git_stat:
        print(git_stat)
    else:
        print("Working tree clean.")

    print("\n" + "="*50)
    print(" ⚡ RECOMMENDED ROUTE")
    print("="*50)
    best_profile, best_model, reason = route_target()
    print(f"Profile      : {best_profile}")
    print(f"Model        : {best_model}")
    print(f"Routing Note : {reason}")

    webhook = WebhookDispatcher()
    print(f"Webhook      : {'Configured' if webhook.is_configured() else 'Not configured (set TASKCTL_WEBHOOK_URL)'}")

    v_sink = get_telemetry_emitter().vector_sink
    print(f"Vector Sink  : {'Configured (' + v_sink.endpoint_url + ')' if v_sink.is_configured() else 'Not configured (set TASKCTL_VECTOR_URL or VECTOR_URL)'}")
    print("="*50 + "\n")

def cmd_graph(
    tree: bool = True,
    mermaid: bool = False,
    json_output: bool = False,
    check_cycles: bool = False,
    file_path: Optional[str] = None,
    no_infer: bool = False,
) -> int:
    import json
    from taskctl.core.graph import TaskDependencyGraph

    try:
        graph = TaskDependencyGraph.build_from_file(file_path, infer_sequential=not no_infer)
    except Exception as e:
        print(f"[ERROR] Failed to build task dependency graph: {e}")
        return 1

    cycles = graph.find_cycles()

    if check_cycles:
        if cycles:
            print("\n==================================================")
            print(" ❌ [FAIL] Task Dependency Cycles Detected:")
            for c in cycles:
                print("   - " + " -> ".join(f"[{x}]" for x in c))
            print("==================================================\n")
            return 1
        else:
            print(f"[OK] No dependency cycles detected. {len(graph.nodes)} task node(s) verified.")
            return 0

    if mermaid:
        print(graph.render_mermaid())
        return 0

    if json_output:
        print(json.dumps(graph.to_dict(), indent=2))
        return 0

    # Default ASCII Tree View
    print("\n==================================================")
    print(" 🕸️  TASK DEPENDENCY GRAPH")
    print("==================================================")
    total = len(graph.nodes)
    completed = sum(1 for n in graph.nodes.values() if n.is_done)
    active = sum(1 for n in graph.nodes.values() if n.is_active)
    backlog = sum(1 for n in graph.nodes.values() if n.section == "backlog")
    print(f"Total: {total} │ Completed: {completed} │ Active: {active} │ Backlog: {backlog}")

    if cycles:
        print("\n ⚠️  WARNING: Dependency cycles detected:")
        for c in cycles:
            print("    " + " -> ".join(f"[{x}]" for x in c))
    print("--------------------------------------------------")
    print(graph.render_ascii_tree(show_status=True, use_color=True))
    print("==================================================\n")
    return 0

def cmd_dashboard(
    snapshot: bool = False,
    interval: float = 2.0,
    run_tests: bool = False,
    split: bool = False,
    dag: bool = False,
) -> int:
    dashboard = Dashboard(interval=interval, run_tests=run_tests, split_pane=split, view_dag=dag)
    if snapshot:
        sys.stdout.write(dashboard.render_snapshot() + "\n")
        sys.stdout.flush()
        return 0
    return dashboard.run()

def cmd_quota():
    quotas = get_profile_quotas()
    if not quotas:
        print("[WARN] Multigravity CLI not installed or returned no profile data.")
        return

    print("\n" + "="*60)
    print(" 📊 MULTIGRAVITY QUOTA TELEMETRY")
    print("="*60)
    print(f"{'Profile':<12} | {'Gemini Quota':<14} | {'Reset Time':<20}")
    print("-" * 60)

    for p, q in quotas.items():
        gemini = q.get("buckets", {}).get("gemini", {})
        rem_frac = gemini.get("remaining_fraction", 0.0)
        reset_time = gemini.get("reset_time", "N/A")
        pct_str = f"{rem_frac*100:.1f}%"
        print(f"{p:<12} | {pct_str:<14} | {reset_time:<20}")

    best_p, best_m, reason = route_target()
    print("-" * 60)
    print(f"Optimal Allocation: Profile '{best_p}' -> {best_m}")
    print(f"Reason: {reason}\n")

def cmd_next(weight: str = "medium", target_agent: Optional[str] = None, handoff: bool = True):
    task_file = get_task_file()
    with open(task_file, "r", encoding="utf-8") as f:
        content = f.read()

    active_task, backlog = parse_task_md(content)

    pending_backlog = [b for b in backlog if not b["checked"]]
    if not pending_backlog:
        print("[INFO] No pending tasks found in Backlog.")
        return

    next_item = pending_backlog[0]
    next_id = next_item["id"]
    next_title = next_item["title"]

    tracer = get_tracer()
    with tracer.start_span("cli.next", tags={"task_id": next_id, "weight": weight}) as root_span:
        best_profile, best_model, _ = route_target(weight=weight)

        updated = content
        old_task_pat = r"(### 📌 Task )\[([^\]]+)\]:\s*([^\n]+)"
        updated = re.sub(old_task_pat, rf"\1[{next_id}]: {next_title}", updated, count=1)

        updated = re.sub(
            r"(-\s*\*\*Runtime Target:\*\*)[^\n]+",
            rf"\1 Profile '{best_profile}' | Model: '{best_model}'",
            updated,
            count=1
        )

        updated = re.sub(
            r"(-\s*\*\*Status:\*\*)[^\n]+",
            r"\1 RUNNING",
            updated,
            count=1
        )

        backlog_line_pat = rf"-\s*\[ \]\s*(?:\*\*|`)?\[{re.escape(next_id)}\](?:\*\*|`)?\s*[^\n]*\n?"
        updated = re.sub(backlog_line_pat, "", updated)

        with open(task_file, "w", encoding="utf-8") as f:
            f.write(updated)

        print(f"\n[OK] Promoted [{next_id}] '{next_title}' to Active Task (Status: RUNNING).")
        print(f"[Quota Route] Profile: {best_profile} | Model: {best_model} (Weight: {weight})")

        sync_task_cockpit_note(updated)

        webhook = WebhookDispatcher()
        webhook.send_event(
            event_type="task_started",
            task_id=next_id,
            title=next_title,
            status="RUNNING",
            details={"actor": f"{best_profile} ({best_model})"}
        )

        get_telemetry_emitter().emit_lifecycle_event(
            event_type="task_started",
            task_id=next_id,
            message=f"Task [{next_id}] promoted to RUNNING: {next_title}",
            status="RUNNING",
            trace_id=root_span.trace_id,
            span_id=root_span.span_id,
            parent_span_id=root_span.parent_span_id,
            details={
                "actor": f"{best_profile} ({best_model})",
                "weight": weight,
                "profile": best_profile,
                "model": best_model,
            },
        )

        if handoff:
            promoted_active, _ = parse_task_md(updated)
            task_data = {
                "task_id": next_id,
                "title": next_title,
                "status": "RUNNING",
                "target_profile": best_profile,
                "target_model": best_model,
                "description": promoted_active.get("description", "") if promoted_active else "",
                "systems": promoted_active.get("systems", "") if promoted_active else "",
                "criteria": promoted_active.get("criteria", []) if promoted_active else [],
                "runtime_target": f"Profile '{best_profile}' | Model: '{best_model}'",
            }
            with tracer.start_span("provider.handoff_start", tags={"task_id": next_id}):
                h_res = handoff_task_start(task_data, target_agent=target_agent)
            if h_res.delivered:
                print(f"[Hand-off] Successfully dispatched context to canvas agent '{h_res.target_agent}'.")
                if h_res.response:
                    print(f"            Response: {h_res.response}")
            else:
                print(f"[Hand-off] Canvas agent hand-off skipped or degraded (agents offline).")

def cmd_audit(delegate: bool = False, agent_name: Optional[str] = None) -> int:
    from pathlib import Path
    repo_path = Path(find_repo_root())
    task_file = get_task_file()
    active_task = {"id": "XX.Y", "title": "Ad-hoc task"}
    if os.path.exists(task_file):
        try:
            with open(task_file, "r", encoding="utf-8") as f:
                content = f.read()
            active_task, _ = parse_task_md(content)
        except Exception:
            pass

    tracer = get_tracer()
    with tracer.start_span("cli.audit", tags={"task_id": active_task.get("id", "XX.Y"), "hybrid": delegate}) as root_span:
        mode_label = f" [HYBRID / DELEGATED to {agent_name or 'Auditor'}]" if delegate else ""
        print("\n" + "="*58)
        print(f" 🛡️ SCOPE AUDITOR VERIFICATION{mode_label}")
        print("="*58)

        start_audit = time.perf_counter()
        auditor = ScopeAuditor(hybrid=delegate, agent_name=agent_name)
        verdict = auditor.run(repo_path)
        audit_duration_ms = (time.perf_counter() - start_audit) * 1000.0

        for res in verdict.results:
            if res.severity == AuditSeverity.APPROVED:
                icon = "✅ [PASS]"
            elif res.severity == AuditSeverity.CHANGES_REQUIRED:
                icon = "⚠️  [WARN]"
            else:
                icon = "❌ [FAIL]"
            print(f" {icon} {res.rule_name}: {res.message}")

        print("-" * 58)
        print(f" FINAL VERDICT: [{verdict.status}] (exit code {verdict.exit_code})")
        print("=" * 58 + "\n")

        root_span.set_status("OK" if verdict.exit_code == 0 else "ERROR", verdict.status)
        root_span.set_tag("exit_code", verdict.exit_code)
        root_span.set_tag("rule_count", len(verdict.results))

        webhook = WebhookDispatcher()
        webhook.send_event(
            event_type="audit",
            task_id=active_task.get("id", "XX.Y"),
            title=active_task.get("title", "Ad-hoc task"),
            status=verdict.status,
            details={
                "exit_code": verdict.exit_code,
                "rule_count": len(verdict.results),
                "hybrid": delegate,
                "agent": agent_name,
                "rules": [
                    {
                        "rule": r.rule_name,
                        "status": r.severity.label,
                        "message": r.message,
                    }
                    for r in verdict.results
                ],
            },
        )

        get_telemetry_emitter().emit_lifecycle_event(
            event_type="audit",
            task_id=active_task.get("id", "XX.Y"),
            message=f"Scope Auditor finished with verdict: [{verdict.status}] (exit code {verdict.exit_code}) in {audit_duration_ms:.2f}ms",
            status=verdict.status,
            duration_ms=audit_duration_ms,
            level="info" if verdict.exit_code == 0 else "warn",
            trace_id=root_span.trace_id,
            span_id=root_span.span_id,
            parent_span_id=root_span.parent_span_id,
            details={
                "exit_code": verdict.exit_code,
                "rule_count": len(verdict.results),
                "hybrid": delegate,
                "agent": agent_name,
                "rules": [
                    {
                        "rule": r.rule_name,
                        "status": r.severity.label,
                        "message": r.message,
                    }
                    for r in verdict.results
                ],
            },
        )
        return verdict.exit_code

def cmd_lint_commit(
    msg: Optional[str] = None,
    file_path: Optional[str] = None,
    rev: Optional[str] = None,
    commit_range: Optional[str] = None,
) -> int:
    if commit_range:
        res = subprocess.run(
            ["git", "log", "--pretty=%H", commit_range],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            print(f"[ERROR] Failed to list commits in range '{commit_range}': {res.stderr.strip()}")
            return 1
        shas = [s.strip() for s in res.stdout.splitlines() if s.strip()]
        if not shas:
            print(f"[WARN] No commits found in range '{commit_range}'.")
            return 0

        all_passed = True
        print("\n" + "=" * 58)
        print(f" 📝 CONVENTIONAL COMMITS LINTER (Range: {commit_range})")
        print("=" * 58)
        for sha in shas:
            c_res = subprocess.run(
                ["git", "log", "-1", "--pretty=%B", sha],
                capture_output=True,
                text=True,
                check=False,
            )
            raw_c = c_res.stdout
            val = parse_conventional_commit(raw_c)
            short_sha = sha[:8]
            if val.is_valid and val.commit:
                print(f" ✅ [PASS] {short_sha}: {val.commit.header}")
            else:
                all_passed = False
                print(f" ❌ [FAIL] {short_sha}:")
                for err in val.errors:
                    print(f"     - {err}")
        print("=" * 58 + "\n")
        return 0 if all_passed else 1

    raw_content = ""
    if rev:
        res = subprocess.run(
            ["git", "log", "-1", "--pretty=%B", rev],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            print(f"[ERROR] Failed to read git commit at '{rev}': {res.stderr.strip()}")
            return 1
        raw_content = res.stdout
    elif file_path:
        if not os.path.exists(file_path):
            print(f"[ERROR] Commit message file not found: {file_path}")
            return 1
        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    elif msg:
        raw_content = msg
    elif not sys.stdin.isatty():
        raw_content = sys.stdin.read()
    else:
        print("[ERROR] No commit message provided. Usage: taskctl lint-commit '<message>' or taskctl lint-commit --file <file> or --rev <rev>")
        return 1

    validation = parse_conventional_commit(raw_content)

    print("\n" + "="*58)
    print(" 📝 CONVENTIONAL COMMITS LINTER")
    print("="*58)

    if validation.is_valid and validation.commit:
        c = validation.commit
        scope_str = f"({c.scope})" if c.scope else ""
        break_str = " [BREAKING]" if c.is_breaking else ""
        print(f" ✅ [PASS] Valid Conventional Commit")
        print(f" Type        : {c.type}")
        print(f" Scope       : {c.scope or 'none'}")
        print(f" Breaking    : {'YES' if c.is_breaking else 'no'}")
        print(f" Description : {c.description}")
        if c.body:
            print(f" Body        :\n{c.body}")
        if c.footers:
            print(" Footers     :")
            for f in c.footers:
                print(f"   {f['token']}: {f['value']}")
        print("="*58 + "\n")
        get_telemetry_emitter().emit_lifecycle_event(
            event_type="commit_lint",
            task_id="AUDIT",
            message=f"Commit message valid: {c.header}",
            status="APPROVED",
            level="info",
            details={"type": c.type, "scope": c.scope, "is_breaking": c.is_breaking},
        )
        return 0
    else:
        print(" ❌ [FAIL] Commit message violates Conventional Commits:")
        for err in validation.errors:
            print(f"   - {err}")
        print("\n Schema Requirement: <type>[optional scope][!]: <description>")
        print(" Standard Types     : feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert")
        print("="*58 + "\n")
        get_telemetry_emitter().emit_lifecycle_event(
            event_type="commit_lint",
            task_id="AUDIT",
            message=f"Commit message lint failed: {len(validation.errors)} error(s)",
            status="CHANGES REQUIRED",
            level="warn",
            details={"errors": validation.errors},
        )
        return 1

def cmd_done(
    custom_msg: Optional[str] = None,
    promote: bool = False,
    weight: str = "medium",
    notify_planner: bool = True,
    target_agent: Optional[str] = None,
    handoff: bool = True,
):
    task_file = get_task_file()
    with open(task_file, "r", encoding="utf-8") as f:
        content = f.read()

    active_task, backlog = parse_task_md(content)
    task_id = active_task.get("id", "XX.Y")
    title = active_task.get("title", "Ad-hoc task")

    tracer = get_tracer()
    with tracer.start_span("cli.done", tags={"task_id": task_id, "promote": promote}) as root_span:
        # Step 1: Feature commit
        staged = run_cmd("git diff --cached --name-only").stdout.strip().splitlines()
        staged = [f.strip() for f in staged if f.strip() and not f.endswith(".agent/TASK.md")]

        commit_hash = "HEAD"
        if staged:
            commit_msg = custom_msg or f"feat(task): resolve [{task_id}] {title}"
            val = parse_conventional_commit(commit_msg)
            if not val.is_valid:
                print("\n" + "="*58)
                print(" ❌ [ERROR] Commit message violates Conventional Commits:")
                for err in val.errors:
                    print(f"   - {err}")
                print("\n Schema Requirement: <type>[optional scope][!]: <description>")
                print(" Standard Types     : feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert")
                print("="*58)
                print("Aborting commit. Please supply a valid Conventional Commit message.\n")
                root_span.set_status("ERROR", "Invalid commit message")
                return
            with tracer.start_span("git.feature_commit", tags={"task_id": task_id}):
                run_cmd(f'git commit -m "{commit_msg}"', check=True)
            commit_hash = run_cmd("git rev-parse --short HEAD").stdout.strip()
            print(f"[COMMIT 1/2] Feature commit created: {commit_hash} - {commit_msg}")
        else:
            commit_hash = run_cmd("git rev-parse --short HEAD").stdout.strip()
            print(f"[INFO] No staged feature changes detected; linking task [{task_id}] to commit: {commit_hash}")

        # Step 2: Update TASK.md completed log
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_entry = f"| [{task_id}] | {title} | [`{commit_hash}`] | {today} |\n"

        updated = content
        if "## Completed Tasks Log" in updated:
            lines = updated.split("\n")
            idx = -1
            for i, l in enumerate(lines):
                if "|---|" in l:
                    idx = i
                    break
            if idx != -1:
                lines.insert(idx + 1, log_entry.strip())
                updated = "\n".join(lines)

        # Reset active task
        updated = re.sub(r"(### 📌 Task )\[([^\]]+)\]:\s*([^\n]+)", r"\1[XX.Y]: [Short descriptive title]", updated, count=1)
        updated = re.sub(r"(-\s*\*\*Status:\*\*)[^\n]+", r"\1 READY FOR PLANNING", updated, count=1)

        with open(task_file, "w", encoding="utf-8") as f:
            f.write(updated)

        gov_msg = f"docs(task): log completion of [{task_id}] and reset active task"
        with tracer.start_span("git.governance_commit", tags={"task_id": task_id}):
            run_cmd("git add ':(top).agent/TASK.md'", check=True)
            run_cmd(f'git commit -m "{gov_msg}"', check=True)
        gov_hash = run_cmd("git rev-parse --short HEAD").stdout.strip()
        print(f"[COMMIT 2/2] Governance commit created: {gov_hash}")

        sync_task_cockpit_note(updated)

        webhook = WebhookDispatcher()
        webhook.send_event(
            event_type="task_completed",
            task_id=task_id,
            title=title,
            status="DONE",
            details={"commit": commit_hash, "governance_commit": gov_hash}
        )

        get_telemetry_emitter().emit_lifecycle_event(
            event_type="task_completed",
            task_id=task_id,
            message=f"Task [{task_id}] marked DONE: {title}",
            status="DONE",
            trace_id=root_span.trace_id,
            span_id=root_span.span_id,
            parent_span_id=root_span.parent_span_id,
            details={"commit": commit_hash, "governance_commit": gov_hash},
        )

        if handoff:
            task_data = {
                "task_id": task_id,
                "title": title,
                "status": "DONE",
                "commit_hash": commit_hash,
                "governance_commit": gov_hash,
                "notify_planner": notify_planner,
            }
            with tracer.start_span("provider.handoff_done", tags={"task_id": task_id}):
                h_res = handoff_task_done(task_data, target_agent=target_agent)
            if h_res.delivered:
                print(f"[Hand-off] Completion context dispatched to canvas agent '{h_res.target_agent}'.")
                if h_res.response:
                    print(f"            Response: {h_res.response}")
            else:
                print(f"[Hand-off] Canvas agent hand-off skipped or degraded (agents offline).")

    if promote:
        cmd_next(weight=weight, target_agent=target_agent, handoff=handoff)

def cmd_backlog():
    task_file = get_task_file()
    with open(task_file, "r", encoding="utf-8") as f:
        content = f.read()
    _, backlog = parse_task_md(content)
    print("\n" + "="*50)
    print(" 📋 UPCOMING BACKLOG")
    print("="*50)
    if not backlog:
        print("No backlog tasks found.")
    for item in backlog:
        mark = "✔" if item["checked"] else " "
        print(f"  [{mark}] [{item['id']}] {item['title']}")
    print("="*50 + "\n")

def cmd_ws(name: Optional[str] = None, preset: Optional[str] = None, workers: int = 3):
    root = find_repo_root()
    ws_name = name or os.path.basename(root)

    print("\n" + "="*58)
    print(" 🎨 MAESTRI CANVAS WORKSPACE PROVISIONING")
    print("="*58)
    print(f" Workspace Name : {ws_name}")
    print(f" Directory Root : {root}")
    if preset:
        print(f" Topology Preset: {preset}")
        if preset.lower() == "swarm":
            print(f" Worker Count   : {workers}")

    task_file = os.path.join(root, ".agent", "TASK.md")
    task_content = ""
    if os.path.exists(task_file):
        try:
            with open(task_file, "r", encoding="utf-8") as f:
                task_content = f.read()
        except Exception:
            task_content = ""

    if preset:
        valid_presets = list_topology_presets()
        if preset.lower() not in valid_presets:
            print(f" ❌ [ERROR] Unknown topology preset '{preset}'. Valid presets: {', '.join(valid_presets)}")
            print("="*58 + "\n")
            return 1
        topo = get_topology_preset(preset, workers=workers, task_content=task_content)
        res = apply_topology_to_canvas(topo, dir_path=root, workspace_name=ws_name)
        ok = res.get("success", False)
        if ok:
            print(f" ✅ [OK] Successfully provisioned canvas workspace with '{preset}' topology.")
        elif res.get("degraded"):
            print(" ⚠️  [WARN] Remote canvas workspace degraded (Maestri daemon or CLI unavailable).")
            print(f"          Topology plan registered locally ({len(topo.agents)} agents, {len(topo.connections)} connections).")
        else:
            print(f" ❌ [ERROR] Failed to apply topology preset '{preset}'.")

        print("\n Topology Breakdown:")
        print(f"   - Agents ({len(topo.agents)}): {', '.join(a.name for a in topo.agents)}")
        print(f"   - Notes  ({len(topo.notes)}): {', '.join(n.name for n in topo.notes)}")
        print(f"   - Ropes  ({len(topo.connections)}): {', '.join(f'{s} -> {d}' for s, d in topo.connections)}")
    else:
        ok = create_workspace_canvas(name=ws_name, dir_path=root)
        if ok:
            print(f" ✅ [OK] Provisioned Maestri workspace '{ws_name}'.")
        else:
            print(" ⚠️  [WARN] Remote canvas workspace creation skipped or daemon unavailable.")

        if task_content:
            synced = sync_task_cockpit_note(task_content)
            if synced:
                print(" ✅ [OK] Initialized and synced cockpit note on canvas.")
            else:
                print(" ⚠️  [WARN] Note sync skipped (Maestri CLI or socket not detected).")

    print("="*58 + "\n")
    get_telemetry_emitter().emit_lifecycle_event(
        event_type="workspace_provision",
        task_id="WORKSPACE",
        message=f"Provisioned canvas workspace '{ws_name}' in {root}" + (f" with preset '{preset}'" if preset else ""),
        status="APPROVED" if ok else "DEGRADED",
        details={
            "workspace": ws_name,
            "root": root,
            "preset": preset,
            "workers": workers if preset and preset.lower() == "swarm" else None,
            "success": ok,
        },
    )
    return 0 if ok else 1

def cmd_plan(prompt: str):
    task_file = get_task_file()
    with open(task_file, "r", encoding="utf-8") as f:
        content = f.read()

    active, _ = parse_task_md(content)
    task_id = active.get("id", "XX.Y") if active else "XX.Y"

    print("\n" + "="*58)
    print(" 🧭 TASK PLANNING & AGENT DELEGATION")
    print("="*58)
    print(f" Target Task  : [{task_id}]")
    print(f" Prompt       : {prompt}")

    updated = re.sub(
        r"(-\s*\*\*Status:\*\*)[^\n]+",
        r"\1 PLANNING",
        content,
        count=1
    )

    with open(task_file, "w", encoding="utf-8") as f:
        f.write(updated)
    print(" [OK] Updated active task status to PLANNING in .agent/TASK.md.")

    planner_resp = ask_agent("Planner", prompt)
    if planner_resp:
        print("\n [Maestri Planner Agent Response]")
        print("-" * 58)
        print(planner_resp)
        print("-" * 58)
    else:
        print(" [INFO] Maestri Planner agent offline or not connected; planning registered locally.")

    sync_task_cockpit_note(updated)

    webhook = WebhookDispatcher()
    if webhook.is_configured():
        webhook.send_event(
            event_type="task_planning",
            task_id=task_id,
            title=active.get("title", "Ad-hoc task") if active else "Ad-hoc task",
            status="PLANNING",
            details={"prompt": prompt, "planner_contacted": planner_resp is not None}
        )

    get_telemetry_emitter().emit_lifecycle_event(
        event_type="task_planning",
        task_id=task_id,
        message=f"Task [{task_id}] transitioned to PLANNING: {prompt}",
        status="PLANNING",
        details={"prompt": prompt, "planner_contacted": planner_resp is not None},
    )
    print("="*58 + "\n")

def cmd_sync(pull: bool = False):
    task_file = get_task_file()
    print("\n" + "="*58)
    print(" 🔄 REAL-TIME CANVAS CONTRACT SYNC")
    print("="*58)

    if pull:
        print(" [MODE] Pulling remote canvas note to local .agent/TASK.md...")
        remote_content = pull_task_cockpit_note()
        if not remote_content:
            print(" ❌ [ERROR] Unable to fetch task note from Maestri canvas (socket/CLI unreachable or note not found).")
            print("="*58 + "\n")
            return

        active, _ = parse_task_md(remote_content)
        if not active or not active.get("id"):
            print(" ❌ [ERROR] Remote note content does not contain valid TASK.md schema. Aborting pull.")
            print("="*58 + "\n")
            return

        with open(task_file, "w", encoding="utf-8") as f:
            f.write(remote_content)
        print(f" ✅ [OK] Successfully pulled and updated local {task_file} from canvas note.")
        get_telemetry_emitter().emit_lifecycle_event(
            event_type="canvas_sync",
            task_id=active.get("id", "XX.Y"),
            message="Pulled task contract from canvas to local TASK.md",
            status="PULLED",
            details={"direction": "pull", "task_id": active.get("id")},
        )
    else:
        print(" [MODE] Pushing local .agent/TASK.md to remote canvas note...")
        with open(task_file, "r", encoding="utf-8") as f:
            content = f.read()

        active, _ = parse_task_md(content)
        ok = sync_task_cockpit_note(content)
        if ok:
            print(" ✅ [OK] Successfully synced .agent/TASK.md to Maestri canvas note.")
        else:
            print(" ⚠️  [WARN] Note sync skipped or degraded (Maestri CLI or socket not available).")

        get_telemetry_emitter().emit_lifecycle_event(
            event_type="canvas_sync",
            task_id=active.get("id", "XX.Y") if active else "XX.Y",
            message="Pushed local TASK.md to canvas note",
            status="PUSHED" if ok else "DEGRADED",
            details={"direction": "push", "success": ok},
        )
    print("="*58 + "\n")

def cmd_notify(msg: str):
    canvas_ok = send_canvas_notification(msg)
    webhook = WebhookDispatcher()
    hook_ok = False
    if webhook.is_configured():
        hook_ok = webhook.send_event(
            event_type="notification",
            task_id="MANUAL",
            title=msg,
            status="INFO",
            details={"summary": msg}
        )

    get_telemetry_emitter().emit_lifecycle_event(
        event_type="notification",
        task_id="MANUAL",
        message=msg,
        status="INFO",
        details={"summary": msg, "canvas_notified": canvas_ok, "webhook_sent": hook_ok},
    )
    print(f"[OK] Notification dispatched (Canvas: {'sent' if canvas_ok else 'skipped'}, Webhook: {'sent' if hook_ok else 'skipped/not configured'}).")

def cmd_daemon(
    watch_paths: Optional[List[str]] = None,
    interval: float = 5.0,
    once: bool = False,
    json_output: bool = False,
    broadcast_canvas: bool = True,
    broadcast_vector: bool = True,
    broadcast_webhook: bool = True,
) -> int:
    daemon = TelemetryDaemon(
        watch_paths=watch_paths,
        interval=interval,
        broadcast_vector=broadcast_vector,
        broadcast_canvas=broadcast_canvas,
        broadcast_webhook=broadcast_webhook,
        output_format="json" if json_output else "text",
    )
    if once:
        daemon.run_once()
        return 0
    daemon.run()
    return 0

def cmd_broadcast(
    msg: Optional[str] = None,
    watch_paths: Optional[List[str]] = None,
    json_output: bool = False,
    broadcast_canvas: bool = True,
    broadcast_vector: bool = True,
    broadcast_webhook: bool = True,
) -> int:
    aggregator = CrossRepoAggregator(watch_paths=watch_paths)
    broadcaster = TelemetryBroadcaster(
        broadcast_vector=broadcast_vector,
        broadcast_canvas=broadcast_canvas,
        broadcast_webhook=broadcast_webhook,
    )
    summary = aggregator.get_summary()
    results = broadcaster.broadcast_summary(summary, custom_msg=msg)

    if json_output:
        import json
        print(json.dumps({"summary": summary, "dispatch_results": results}, indent=2))
    else:
        daemon_helper = TelemetryDaemon(watch_paths=watch_paths)
        print(daemon_helper.format_summary_table(summary))
        canvas_status = "sent" if results.get("canvas") else "skipped"
        vector_status = "sent" if results.get("vector") else "skipped/unconfigured"
        webhook_status = "sent" if results.get("webhook") else "skipped/unconfigured"
        print(f"[OK] Broadcaster dispatched summary (Canvas: {canvas_status}, Vector: {vector_status}, Webhook: {webhook_status}).")
    return 0

def cmd_trace(
    trace_id: Optional[str] = None,
    last: bool = False,
    json_output: bool = False,
    analytics: bool = False,
) -> int:
    import json
    tracer = get_tracer()
    spans = tracer.get_completed_spans()

    if not spans:
        print("[INFO] No telemetry spans currently in memory.")
        return 0

    target_trace_id = trace_id
    if not target_trace_id and last:
        target_trace_id = spans[-1].trace_id

    selected_spans = tracer.get_completed_spans(trace_id=target_trace_id) if target_trace_id else spans

    if json_output:
        payload = [s.to_dict() for s in selected_spans]
        if analytics:
            stats = DurationAnalyzer.analyze_spans(selected_spans)
            print(json.dumps({"trace_id": target_trace_id, "analytics": stats, "spans": payload}, indent=2))
        else:
            print(json.dumps(payload, indent=2))
        return 0

    print("\n" + "=" * 58)
    print(f" ⏱️  DISTRIBUTED TRACE INSPECTOR")
    if target_trace_id:
        print(f" Trace ID: {target_trace_id}")
    print("=" * 58)
    print(DurationAnalyzer.render_tree(selected_spans))

    if analytics:
        stats = DurationAnalyzer.analyze_spans(selected_spans)
        print("-" * 58)
        print(f" Total Spans    : {stats['total_spans']}")
        print(f" Total Duration : {stats['total_duration_ms']:.2f}ms")
        print(f" Avg Duration   : {stats['avg_duration_ms']:.2f}ms")
        print(f" Max Duration   : {stats['max_duration_ms']:.2f}ms")
        print(f" Min Duration   : {stats['min_duration_ms']:.2f}ms")

    print("=" * 58 + "\n")
    return 0

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ["-h", "--help", "help"]:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    if cmd == "init":
        cmd_init()
    elif cmd == "status":
        cmd_status()
    elif cmd == "backlog":
        cmd_backlog()
    elif cmd == "quota":
        cmd_quota()
    elif cmd == "ws":
        ws_name = None
        preset = None
        workers = 3
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["--preset", "-p"] and i + 1 < len(args):
                preset = args[i + 1]
                i += 2
            elif args[i] in ["--workers", "-w"] and i + 1 < len(args):
                try:
                    workers = int(args[i + 1])
                except ValueError:
                    print(f"[WARN] Invalid worker count '{args[i + 1]}', defaulting to 3.")
                    workers = 3
                i += 2
            elif not args[i].startswith("-") and ws_name is None:
                ws_name = args[i]
                i += 1
            else:
                i += 1
        sys.exit(cmd_ws(name=ws_name, preset=preset, workers=workers))
    elif cmd == "plan":
        if len(sys.argv) < 3:
            print("[ERROR] Please provide a planning prompt: taskctl plan '<prompt>'")
            sys.exit(1)
        plan_prompt = " ".join(sys.argv[2:])
        cmd_plan(prompt=plan_prompt)
    elif cmd == "next":
        weight = "medium"
        target_agent = None
        handoff = True
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["light", "medium", "heavy"]:
                weight = args[i]
                i += 1
            elif args[i] in ["--agent", "-a"] and i + 1 < len(args):
                target_agent = args[i + 1]
                i += 2
            elif args[i] in ["--no-handoff", "--skip-handoff"]:
                handoff = False
                i += 1
            else:
                i += 1
        cmd_next(weight=weight, target_agent=target_agent, handoff=handoff)
    elif cmd == "audit":
        delegate = False
        agent_name = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["--delegate", "--hybrid", "-d"]:
                delegate = True
                i += 1
            elif args[i] in ["--agent", "-a"] and i + 1 < len(args):
                agent_name = args[i + 1]
                delegate = True
                i += 2
            else:
                i += 1
        sys.exit(cmd_audit(delegate=delegate, agent_name=agent_name))
    elif cmd == "done":
        promote = False
        custom_msg = None
        target_agent = None
        handoff = True
        weight = "medium"
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["-p", "--promote"]:
                promote = True
                i += 1
            elif args[i] in ["--agent", "-a"] and i + 1 < len(args):
                target_agent = args[i + 1]
                i += 2
            elif args[i] in ["--no-handoff", "--skip-handoff"]:
                handoff = False
                i += 1
            elif args[i] in ["--weight", "-w"] and i + 1 < len(args):
                weight = args[i + 1]
                i += 2
            elif not args[i].startswith("-") and custom_msg is None:
                custom_msg = args[i]
                i += 1
            else:
                i += 1
        cmd_done(custom_msg=custom_msg, promote=promote, weight=weight, target_agent=target_agent, handoff=handoff)
    elif cmd == "sync":
        pull = "--pull" in sys.argv[2:]
        cmd_sync(pull=pull)
    elif cmd == "notify":
        msg = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Test notification"
        cmd_notify(msg)
    elif cmd in ["lint-commit", "commit-lint"]:
        file_path = None
        rev = None
        commit_range = None
        msg_parts = []
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["-f", "--file"] and i + 1 < len(args):
                file_path = args[i + 1]
                i += 2
            elif args[i] in ["-r", "--rev"] and i + 1 < len(args):
                rev = args[i + 1]
                i += 2
            elif args[i] in ["--range"] and i + 1 < len(args):
                commit_range = args[i + 1]
                i += 2
            elif args[i] in ["--head"]:
                rev = "HEAD"
                i += 1
            else:
                msg_parts.append(args[i])
                i += 1
        msg = " ".join(msg_parts) if msg_parts else None
        sys.exit(cmd_lint_commit(msg=msg, file_path=file_path, rev=rev, commit_range=commit_range))
    elif cmd == "graph":
        mermaid = False
        json_output = False
        check_cycles = False
        no_infer = False
        file_path = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["-m", "--mermaid"]:
                mermaid = True
                i += 1
            elif args[i] in ["--json"]:
                json_output = True
                i += 1
            elif args[i] in ["-c", "--check-cycles", "--cycles"]:
                check_cycles = True
                i += 1
            elif args[i] in ["--no-infer", "--explicit-only"]:
                no_infer = True
                i += 1
            elif args[i] in ["-f", "--file"] and i + 1 < len(args):
                file_path = args[i + 1]
                i += 2
            elif args[i] in ["--tree", "-t"]:
                i += 1
            elif not args[i].startswith("-") and file_path is None:
                file_path = args[i]
                i += 1
            else:
                i += 1
        sys.exit(cmd_graph(
            mermaid=mermaid,
            json_output=json_output,
            check_cycles=check_cycles,
            file_path=file_path,
            no_infer=no_infer,
        ))
    elif cmd in ["dashboard", "tui"]:
        snapshot = False
        interval = 2.0
        run_tests = False
        split = False
        dag = False
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["--snapshot", "--once", "-s"]:
                snapshot = True
                i += 1
            elif args[i] in ["--interval", "-i"] and i + 1 < len(args):
                try:
                    interval = float(args[i + 1])
                except ValueError:
                    interval = 2.0
                i += 2
            elif args[i] in ["--tests", "-t", "--heavy"]:
                run_tests = True
                i += 1
            elif args[i] in ["--split", "-d"]:
                split = True
                i += 1
            elif args[i] in ["--no-split"]:
                split = False
                i += 1
            elif args[i] in ["--dag", "-g"]:
                dag = True
                i += 1
            else:
                i += 1
        sys.exit(cmd_dashboard(snapshot=snapshot, interval=interval, run_tests=run_tests, split=split, dag=dag))
    elif cmd == "daemon":
        watch_paths: List[str] = []
        interval = 5.0
        once = False
        json_output = False
        broadcast_canvas = True
        broadcast_vector = True
        broadcast_webhook = True
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["-w", "--watch"] and i + 1 < len(args):
                watch_paths.append(args[i + 1])
                i += 2
            elif args[i] in ["-i", "--interval"] and i + 1 < len(args):
                try:
                    interval = float(args[i + 1])
                except ValueError:
                    interval = 5.0
                i += 2
            elif args[i] in ["-s", "--snapshot", "--once"]:
                once = True
                i += 1
            elif args[i] in ["--json"]:
                json_output = True
                i += 1
            elif args[i] in ["--no-canvas"]:
                broadcast_canvas = False
                i += 1
            elif args[i] in ["--no-vector"]:
                broadcast_vector = False
                i += 1
            elif args[i] in ["--no-webhook"]:
                broadcast_webhook = False
                i += 1
            elif not args[i].startswith("-"):
                watch_paths.append(args[i])
                i += 1
            else:
                i += 1
        sys.exit(cmd_daemon(
            watch_paths=watch_paths or None,
            interval=interval,
            once=once,
            json_output=json_output,
            broadcast_canvas=broadcast_canvas,
            broadcast_vector=broadcast_vector,
            broadcast_webhook=broadcast_webhook,
        ))
    elif cmd == "broadcast":
        watch_paths: List[str] = []
        custom_msg = None
        json_output = False
        broadcast_canvas = True
        broadcast_vector = True
        broadcast_webhook = True
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["-w", "--watch"] and i + 1 < len(args):
                watch_paths.append(args[i + 1])
                i += 2
            elif args[i] in ["--json"]:
                json_output = True
                i += 1
            elif args[i] in ["--no-canvas"]:
                broadcast_canvas = False
                i += 1
            elif args[i] in ["--no-vector"]:
                broadcast_vector = False
                i += 1
            elif args[i] in ["--no-webhook"]:
                broadcast_webhook = False
                i += 1
            elif not args[i].startswith("-") and custom_msg is None:
                custom_msg = args[i]
                i += 1
            elif not args[i].startswith("-"):
                watch_paths.append(args[i])
                i += 1
            else:
                i += 1
        sys.exit(cmd_broadcast(
            msg=custom_msg,
            watch_paths=watch_paths or None,
            json_output=json_output,
            broadcast_canvas=broadcast_canvas,
            broadcast_vector=broadcast_vector,
            broadcast_webhook=broadcast_webhook,
        ))
    elif cmd == "trace":
        trace_id = None
        last = False
        json_output = False
        analytics = False
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["--id", "-i"] and i + 1 < len(args):
                trace_id = args[i + 1]
                i += 2
            elif args[i] in ["--last", "-l"]:
                last = True
                i += 1
            elif args[i] in ["--json"]:
                json_output = True
                i += 1
            elif args[i] in ["--analytics", "-a"]:
                analytics = True
                i += 1
            elif not args[i].startswith("-") and trace_id is None:
                trace_id = args[i]
                i += 1
            else:
                i += 1
        sys.exit(cmd_trace(
            trace_id=trace_id,
            last=last,
            json_output=json_output,
            analytics=analytics,
        ))
    else:
        print(f"Unknown command: '{cmd}'. Run 'taskctl --help' for usage.")
        sys.exit(1)

if __name__ == "__main__":
    main()
