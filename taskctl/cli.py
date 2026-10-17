#!/usr/bin/env python3
"""
taskctl - Task Lifecycle, Contract Engine & Multi-Agent CLI.

Commands:
  taskctl ws [name] [--preset <name>] [--workers <n>]
                           Create and wire Maestri workspace for current repo with
                           optional multi-agent topology preset (trinity, swarm, audit).
  taskctl init             Initialize .agent/TASK.md and AGENTS.md in current repository.
  taskctl status [--repo <path|name>]
                           Show active task, criteria, git status, and quota route.
  taskctl quota            Display real-time Multigravity quota across all profiles.
  taskctl plan "<prompt>" [--repo <path|name>]
                           Ask the Planner agent to decompose tasks into .agent/TASK.md.
  taskctl next [--weight] [--agent <name>] [--no-handoff] [--repo <path|name>] [--runner <name>]
                           Promote next backlog task to active (RUNNING) and dispatch
                           lifecycle hand-off or runner execution (maestri, multigravity, codex, custom).
  taskctl audit [--delegate] [--agent <name>] [--domain-lint] [--repo <path|name>]
                           Trigger Scope Auditor to verify diff with optional canvas
                           agent delegation fallback. --domain-lint (or
                           TASKCTL_DOMAIN_LINT=1) also checks acceptance criteria.
                           Returns semantic exit codes:
                             0: [APPROVED] - Ready for taskctl done.
                             1: [CHANGES REQUIRED] - Prints Required Action for auto-remediation.
                             2: [REJECTED] - Critical failure; escalates to Planner/human.
  taskctl done [msg] [-p] [--agent <name>] [--no-handoff] [--repo <path|name>] [--runner <name>]
                           Validate DoD, create double atomic commit (code + governance),
                           dispatch completion hand-off to Auditor/Planner, and trigger webhooks.
  taskctl lint-commit [msg] [--file <path>] [--rev <rev>] [--range <range>] [--head]
                           Validate commit message against Conventional Commits.
  taskctl sync [--pull] [--hud]
                           Sync current .agent/TASK.md or real-time Live Telemetry HUD to canvas note.
  taskctl backlog          List upcoming backlog items.
  taskctl graph [--tree] [--mermaid] [--json] [--check-cycles] [--file <path>] [--export-plan [<file>]] [--out <file>] [--repo <path|name>]
                           Visualize task dependency DAG or export agnostic execution plan for concurrent runners.
  taskctl dashboard [--snapshot] [--interval <sec>] [--tests] [--split] [--dag]
                           Launch interactive terminal dashboard prototype displaying
                           active task contract status, DoD checklist, and scope audit.
                           (Alias: taskctl tui)
  taskctl daemon [--watch <path>...] [--interval <sec>] [--once] [--json]
                           Run cross-repo telemetry aggregation daemon to monitor multiple
                           workspaces and broadcast live events to Vector, Canvas, and Webhooks.
  taskctl broadcast [msg] [--watch <path>...] [--json]
                           Aggregate cross-repo status roll-up and broadcast to configured sinks.
  taskctl notify <msg>     Send an ad-hoc notification via configured webhook.
  taskctl tokens [--profile <p>] [--role <r>] [--repo <path>] [--json] [--detailed]
                           Aggregate multi-agent token consumption partitioned by Profile and Role.
  taskctl guard [eval|status|test]
                           Inspect guardrail status, evaluate commands against active policy,
                           and run diagnostic test matrix for terminal interception.
  taskctl worktree [list|create|remove|prune] [--repo <path|name>] [--json]
                           Manage ephemeral Git worktrees for isolated task execution.
  taskctl stage verify [--stage <n>] [--plan <file>] [--base <ref>] [--repo <path|name>] [--json]
                           Verify DAG stage tasks for disjoint file scopes and clean mergeability.
  taskctl recall "<query>" [--component <c>] [--json] [--detailed] [--repo <path|name>]
                           Search Knowledge Cards via SQLite FTS5 BM25 full-text ranking.
  taskctl reflex [--stderr "<log>"] [--file <path>] [--json] [--repo <path|name>]
                           Detect immediate solutions and gotchas from error signatures and stack traces.
"""

import os
import sys

if __package__ is None or __package__ == "":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from taskctl.core.parser import find_repo_root, get_task_file, parse_task_md, resolve_repo_path
from taskctl.core.auditor import ScopeAuditor, AuditSeverity, domain_lint_enabled
from taskctl.core.commits import parse_conventional_commit
from taskctl.core.knowledge import KnowledgeEngine, KnowledgeCard
from taskctl.core.worktree import (
    WorktreeManager,
    WorktreeInfo,
    DisjointScopeConflict,
    StageVerificationResult,
    MergeVerificationResult,
)
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
    sync_hud_note,
    generate_hud_markdown,
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
from taskctl.runners import get_runner, list_runners, RunnerResult
from taskctl.tui import Dashboard

def run_cmd(cmd_str: str, check: bool = False, capture: bool = True, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd_str,
        shell=True,
        text=True,
        capture_output=capture,
        check=check,
        cwd=cwd,
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

def cmd_status(repo: Optional[str] = None):
    try:
        repo_root = resolve_repo_path(repo)
        task_file = get_task_file(repo_root)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    with open(task_file, "r", encoding="utf-8") as f:
        content = f.read()

    active_task, backlog = parse_task_md(content)

    print("\n" + "="*50)
    repo_header = f" [{os.path.basename(repo_root)}]" if repo else ""
    print(f" 🎯 ACTIVE TASK COCKPIT{repo_header}")
    print("="*50)

    if repo:
        print(f"Repository   : {repo_root}")

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
    git_stat = run_cmd("git status -s", cwd=repo_root).stdout.strip()
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
    export_plan: bool = False,
    out_file: Optional[str] = None,
    repo: Optional[str] = None,
) -> int:
    import json
    from taskctl.core.graph import TaskDependencyGraph

    repo_root = None
    if repo:
        try:
            repo_root = resolve_repo_path(repo)
            if file_path is None:
                file_path = get_task_file(repo_root)
        except FileNotFoundError as e:
            print(f"[ERROR] {e}")
            return 1

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

    if export_plan:
        effective_repo = repo_root or (os.path.dirname(os.path.abspath(file_path)) if file_path else os.getcwd())
        plan = graph.export_execution_plan(only_pending=True, repo=effective_repo)
        plan_json = json.dumps(plan, indent=2)
        if out_file:
            try:
                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(plan_json + "\n")
                stages_count = plan["summary"]["total_stages"]
                max_conc = plan["summary"]["max_concurrency"]
                print(f"[OK] Agnostic DAG execution plan exported to {out_file} ({stages_count} stage(s), max concurrency: {max_conc}).")
            except Exception as e:
                print(f"[ERROR] Failed to write execution plan to {out_file}: {e}")
                return 1
        else:
            print(plan_json)

        if plan.get("has_cycles") or plan.get("summary", {}).get("has_cycles") or plan.get("cycles"):
            return 1
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

def cmd_quota(refresh: bool = False):
    quotas = get_profile_quotas(refresh=refresh)
    if not quotas:
        print("[WARN] Multigravity CLI not installed or returned no profile data.")
        return

    print("\n" + "="*71)
    print(" 📊 MULTIGRAVITY QUOTA TELEMETRY")
    print("="*71)
    print(f"{'Profile':<12} | {'Gemini Quota':<14} | {'Reset Time':<20} | {'Source':<8}")
    print("-" * 71)

    for p, q in quotas.items():
        gemini = q.get("buckets", {}).get("gemini", {})
        rem_frac = gemini.get("remaining_fraction", 0.0)
        reset_time = gemini.get("reset_time", "N/A")
        source = str(q.get("source", "live")).title()
        pct_str = f"{rem_frac*100:.1f}%"
        print(f"{p:<12} | {pct_str:<14} | {reset_time:<20} | {source:<8}")

    best_p, best_m, reason = route_target(refresh=refresh)
    print("-" * 71)
    print(f"Optimal Allocation: Profile '{best_p}' -> {best_m}")
    print(f"Reason: {reason}\n")

def cmd_next(
    weight: str = "medium",
    target_agent: Optional[str] = None,
    handoff: bool = True,
    repo: Optional[str] = None,
    runner: Optional[str] = None,
):
    try:
        repo_root = resolve_repo_path(repo)
        task_file = get_task_file(repo_root)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

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
    repo_name = os.path.basename(repo_root)
    with tracer.start_span("cli.next", tags={"task_id": next_id, "weight": weight, "repo": repo_name}) as root_span:
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

        repo_prefix = f"[{repo_name}] " if repo else ""
        print(f"\n[OK] {repo_prefix}Promoted [{next_id}] '{next_title}' to Active Task (Status: RUNNING).")
        print(f"[Quota Route] Profile: {best_profile} | Model: {best_model} (Weight: {weight})")

        sync_task_cockpit_note(updated)
        try:
            sync_hud_note(generate_hud_markdown(repo_root))
        except Exception:
            pass

        webhook = WebhookDispatcher()
        webhook.send_event(
            event_type="task_started",
            task_id=next_id,
            title=next_title,
            status="RUNNING",
            details={
                "actor": f"{best_profile} ({best_model})",
                "repo": repo_name,
                "repo_path": repo_root,
            }
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
                "repo": repo_name,
                "repo_path": repo_root,
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
                "repo": repo_name,
                "repo_path": repo_root,
                "weight": weight,
            }

            try:
                runner_instance = get_runner(runner)
            except ValueError as e:
                print(f"[ERROR] {e}")
                sys.exit(1)

            with tracer.start_span("runner.execute", tags={"runner": runner_instance.name, "task_id": next_id, "repo": repo_name}) as runner_span:
                r_res = runner_instance.run(task_data, target_agent=target_agent, weight=weight)

            get_telemetry_emitter().emit_lifecycle_event(
                event_type="runner_dispatched",
                task_id=next_id,
                message=f"Task [{next_id}] dispatched via {runner_instance.name} runner: {r_res.status}",
                status="RUNNING",
                trace_id=runner_span.trace_id,
                span_id=runner_span.span_id,
                parent_span_id=runner_span.parent_span_id,
                details={
                    "runner": runner_instance.name,
                    "status": r_res.status,
                    "delivered": r_res.delivered,
                    "target": r_res.target,
                    "error": r_res.error,
                    "repo": repo_name,
                    "repo_path": repo_root,
                },
            )

            if runner_instance.name == "maestri":
                if r_res.delivered:
                    print(f"[Hand-off] Successfully dispatched context to canvas agent '{r_res.target}'.")
                    if r_res.output:
                        print(f"            Response: {r_res.output}")
                else:
                    print(f"[Hand-off] Canvas agent hand-off skipped or degraded (agents offline).")
            else:
                status_str = r_res.status.upper()
                print(f"[Runner:{runner_instance.name}] Status: {status_str} | Target: {r_res.target or 'N/A'}")
                if r_res.output:
                    print(f"            Output: {r_res.output}")
                if r_res.error:
                    print(f"            Notice: {r_res.error}")

def cmd_audit(
    delegate: bool = False,
    agent_name: Optional[str] = None,
    domain_lint: bool = False,
    repo: Optional[str] = None,
) -> int:
    from pathlib import Path
    try:
        repo_root = resolve_repo_path(repo)
        repo_path = Path(repo_root)
        task_file = get_task_file(repo_root)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return 1

    active_task = {"id": "XX.Y", "title": "Ad-hoc task"}
    if os.path.exists(task_file):
        try:
            with open(task_file, "r", encoding="utf-8") as f:
                content = f.read()
            active_task, _ = parse_task_md(content)
        except Exception:
            pass

    tracer = get_tracer()
    with tracer.start_span("cli.audit", tags={"task_id": active_task.get("id", "XX.Y"), "hybrid": delegate, "repo": repo_path.name}) as root_span:
        mode_label = f" [HYBRID / DELEGATED to {agent_name or 'Auditor'}]" if delegate else ""
        repo_label = f" [{repo_path.name}]" if repo else ""
        print("\n" + "="*58)
        print(f" 🛡️ SCOPE AUDITOR VERIFICATION{repo_label}{mode_label}")
        print("="*58)
        if repo:
            print(f" Repository   : {repo_path}")

        start_audit = time.perf_counter()
        domain_lint_on = domain_lint_enabled(domain_lint)
        auditor = ScopeAuditor(
            hybrid=delegate,
            agent_name=agent_name,
            domain_lint=domain_lint_on,
        )
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
                "repo": repo_path.name,
                "repo_path": str(repo_path),
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
                "repo": repo_path.name,
                "repo_path": str(repo_path),
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
        try:
            sync_hud_note(generate_hud_markdown(str(repo_path)))
        except Exception:
            pass
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
    repo: Optional[str] = None,
    runner: Optional[str] = None,
):
    try:
        repo_root = resolve_repo_path(repo)
        task_file = get_task_file(repo_root)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    with open(task_file, "r", encoding="utf-8") as f:
        content = f.read()

    active_task, backlog = parse_task_md(content)
    task_id = active_task.get("id", "XX.Y")
    title = active_task.get("title", "Ad-hoc task")

    tracer = get_tracer()
    repo_name = os.path.basename(repo_root)
    with tracer.start_span("cli.done", tags={"task_id": task_id, "promote": promote, "repo": repo_name}) as root_span:
        # Step 1: Feature commit
        staged = run_cmd("git diff --cached --name-only", cwd=repo_root).stdout.strip().splitlines()
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
            with tracer.start_span("git.feature_commit", tags={"task_id": task_id, "repo": repo_name}):
                run_cmd(f'git commit -m "{commit_msg}"', check=True, cwd=repo_root)
            commit_hash = run_cmd("git rev-parse --short HEAD", cwd=repo_root).stdout.strip()
            print(f"[COMMIT 1/2] Feature commit created: {commit_hash} - {commit_msg}")
        else:
            commit_hash = run_cmd("git rev-parse --short HEAD", cwd=repo_root).stdout.strip()
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
        with tracer.start_span("git.governance_commit", tags={"task_id": task_id, "repo": repo_name}):
            run_cmd("git add ':(top).agent/TASK.md'", check=True, cwd=repo_root)
            run_cmd(f'git commit -m "{gov_msg}"', check=True, cwd=repo_root)
        gov_hash = run_cmd("git rev-parse --short HEAD", cwd=repo_root).stdout.strip()
        print(f"[COMMIT 2/2] Governance commit created: {gov_hash}")

        sync_task_cockpit_note(updated)
        try:
            sync_hud_note(generate_hud_markdown(repo_root))
        except Exception:
            pass

        webhook = WebhookDispatcher()
        webhook.send_event(
            event_type="task_completed",
            task_id=task_id,
            title=title,
            status="DONE",
            details={
                "commit": commit_hash,
                "governance_commit": gov_hash,
                "repo": repo_name,
                "repo_path": repo_root,
            }
        )

        get_telemetry_emitter().emit_lifecycle_event(
            event_type="task_completed",
            task_id=task_id,
            message=f"Task [{task_id}] marked DONE: {title}",
            status="DONE",
            trace_id=root_span.trace_id,
            span_id=root_span.span_id,
            parent_span_id=root_span.parent_span_id,
            details={
                "commit": commit_hash,
                "governance_commit": gov_hash,
                "repo": repo_name,
                "repo_path": repo_root,
            },
        )

        if handoff:
            task_data = {
                "task_id": task_id,
                "title": title,
                "status": "DONE",
                "commit_hash": commit_hash,
                "governance_commit": gov_hash,
                "notify_planner": notify_planner,
                "repo": repo_name,
                "repo_path": repo_root,
            }
            with tracer.start_span("provider.handoff_done", tags={"task_id": task_id, "repo": repo_name}):
                h_res = handoff_task_done(task_data, target_agent=target_agent)
            if h_res.delivered:
                print(f"[Hand-off] Completion context dispatched to canvas agent '{h_res.target_agent}'.")
                if h_res.response:
                    print(f"            Response: {h_res.response}")
            else:
                print(f"[Hand-off] Canvas agent hand-off skipped or degraded (agents offline).")

    if promote:
        if runner is not None:
            cmd_next(weight=weight, target_agent=target_agent, handoff=handoff, repo=repo, runner=runner)
        else:
            cmd_next(weight=weight, target_agent=target_agent, handoff=handoff, repo=repo)

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

def cmd_plan(prompt: str, repo: Optional[str] = None):
    try:
        repo_root = resolve_repo_path(repo)
        task_file = get_task_file(repo_root)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    with open(task_file, "r", encoding="utf-8") as f:
        content = f.read()

    active, _ = parse_task_md(content)
    task_id = active.get("id", "XX.Y") if active else "XX.Y"

    print("\n" + "="*58)
    repo_label = f" [{os.path.basename(repo_root)}]" if repo else ""
    print(f" 🧭 TASK PLANNING & AGENT DELEGATION{repo_label}")
    print("="*58)
    if repo:
        print(f" Repository   : {repo_root}")
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
            details={
                "prompt": prompt,
                "planner_contacted": planner_resp is not None,
                "repo": os.path.basename(repo_root),
                "repo_path": repo_root,
            }
        )

    get_telemetry_emitter().emit_lifecycle_event(
        event_type="task_planning",
        task_id=task_id,
        message=f"Task [{task_id}] transitioned to PLANNING: {prompt}",
        status="PLANNING",
        details={
            "prompt": prompt,
            "planner_contacted": planner_resp is not None,
            "repo": os.path.basename(repo_root),
            "repo_path": repo_root,
        },
    )
    print("="*58 + "\n")

def cmd_sync(pull: bool = False, hud: bool = False):
    task_file = get_task_file()
    print("\n" + "="*58)
    print(" 🔄 REAL-TIME CANVAS CONTRACT SYNC")
    print("="*58)

    if hud:
        print(" [MODE] Syncing real-time HUD telemetry to remote canvas note...")
        hud_content = generate_hud_markdown()
        ok = sync_hud_note(hud_content)
        if ok:
            print(" ✅ [OK] Successfully synced Live Telemetry HUD to Maestri canvas note.")
        else:
            print(" ⚠️  [WARN] HUD sync skipped or degraded (Maestri CLI or socket not available).")
        get_telemetry_emitter().emit_lifecycle_event(
            event_type="hud_sync",
            task_id="HUD",
            message="Synced Live Telemetry HUD to canvas note",
            status="SYNCED" if ok else "DEGRADED",
            details={"success": ok},
        )
    elif pull:
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

        # Also opportunistically refresh HUD note
        try:
            sync_hud_note(generate_hud_markdown())
        except Exception:
            pass

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

def cmd_guard(subcmd: str, args: List[str]) -> int:
    """Diagnostic CLI for inspecting guardrails, evaluating commands, and testing."""
    repo_root = find_repo_root()
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    try:
        from scripts.aether_guard import AetherGuard, RiskLevel
    except ImportError:
        alt_roots = [
            os.path.expanduser("~/github/ia-maestri"),
            "/home/yegear/github/ia-maestri",
        ]
        loaded = False
        for alt in alt_roots:
            if os.path.isfile(os.path.join(alt, "scripts", "aether_guard.py")):
                if alt not in sys.path:
                    sys.path.insert(0, alt)
                try:
                    from scripts.aether_guard import AetherGuard, RiskLevel
                    loaded = True
                    break
                except ImportError:
                    pass
        if not loaded:
            print("[ERROR] Could not import 'aether-guard' module. Ensure scripts/aether_guard.py exists.")
            return 1

    guard = AetherGuard()

    if subcmd == "status":
        json_output = "--json" in args
        status = guard.get_status()
        if json_output:
            import json
            print(json.dumps(status, indent=2))
            return 0
        print("=" * 60)
        print(" 🛡️  TASKCTL GUARD: STATUS & POLICY TELEMETRY")
        print("=" * 60)
        print(f" Config File    : {status['config_file']}")
        print(f" Safe Limit     : {status['safe_limit']:.2f}")
        print(f" Audit Limit    : {status['audit_limit']:.2f}")
        print(f" Fast-Path Rules: {status['fast_path_patterns_count']} compiled regexes")
        print(f" Denylist Rules : {status['denylist_patterns_count']} critical signatures")
        print(f" Suspicious Rls : {status['suspicious_patterns_count']} patterns with weights")
        print(f" Roles Loaded   : {', '.join(status['configured_roles']) or 'none'}")
        print(f" Maestri Socket : {status['socket_path']} (Available: {status['socket_available']})")
        print(f" Telemetry Sinks: file={status['telemetry_log_file']} | http={status['telemetry_sink_url']}")
        print("=" * 60)
        return 0

    elif subcmd == "eval":
        if not args:
            print("[ERROR] Please specify a command to evaluate: taskctl guard eval '<cmd>' [--role <role>]")
            return 1
        role = "developer"
        json_output = False
        cmd_parts = []
        i = 0
        while i < len(args):
            if args[i] in ["--role", "-r"] and i + 1 < len(args):
                role = args[i + 1]
                i += 2
            elif args[i] == "--json":
                json_output = True
                i += 1
            else:
                cmd_parts.append(args[i])
                i += 1
        target_cmd = " ".join(cmd_parts)
        res = guard.evaluate(target_cmd, role=role)
        if json_output:
            import json
            print(json.dumps(res.to_dict(), indent=2))
            return 0 if res.action != RiskLevel.BLOCK else 1

        print("=" * 60)
        print(" 🛡️  TASKCTL GUARD: COMMAND EVALUATION")
        print("=" * 60)
        print(f" Command : {res.command}")
        print(f" Role    : {role}")
        color = "\033[32m" if res.action == RiskLevel.SAFE else ("\033[33m" if res.action == RiskLevel.AUDIT else "\033[31m")
        reset = "\033[0m"
        print(f" Decision: {color}{res.action.value}{reset} (Score: {res.score:.2f})")
        print(f" Latency : {res.latency_ms:.2f}ms (Fast-path: {res.fast_path})")
        print(f" Reason  : {res.reason}")
        print("=" * 60)
        return 0 if res.action != RiskLevel.BLOCK else 1

    elif subcmd == "test":
        json_output = "--json" in args
        results = guard.run_diagnostic_matrix()
        if json_output:
            import json
            print(json.dumps([r.to_dict() for r in results], indent=2))
            return 0
        print("=" * 72)
        print(" 🧪 TASKCTL GUARD: DIAGNOSTIC TEST MATRIX")
        print("=" * 72)
        print(f" {'ACTION':<7} | {'SCORE':<5} | {'LATENCY':<8} | {'ROLE':<16} | {'COMMAND'}")
        print("-" * 72)
        for r in results:
            color = "\033[32m" if r.action == RiskLevel.SAFE else ("\033[33m" if r.action == RiskLevel.AUDIT else "\033[31m")
            reset = "\033[0m"
            print(f" {color}{r.action.value:<7}{reset} | {r.score:<5.2f} | {r.latency_ms:<6.2f}ms | {r.role:<16} | {r.command}")
        print("=" * 72)
        return 0

    elif subcmd in ["monitor", "live"]:
        from scripts.aether_guard import cmd_monitor
        import argparse
        m_args = argparse.Namespace(
            config=None,
            file=None,
            lines=15,
            once="--once" in args,
        )
        return cmd_monitor(m_args)

    else:
        print(f"[ERROR] Unknown guard subcommand '{subcmd}'. Available: eval, status, test, live")
        return 1


def cmd_tokens(
    profile: Optional[str] = None,
    role: Optional[str] = None,
    repo: Optional[str] = None,
    json_output: bool = False,
    detailed: bool = False,
    limit: int = 100,
) -> int:
    """Aggregate multi-agent token consumption partitioned by Profile and Role."""
    from taskctl.telemetry.tokens import collect_token_telemetry

    sessions, aggregations = collect_token_telemetry(
        profile_filter=profile,
        role_filter=role,
        repo_filter=repo,
        search_limit_per_profile=limit,
    )

    if json_output:
        tot_prompt = sum(a.prompt_tokens for a in aggregations)
        tot_comp = sum(a.completion_tokens for a in aggregations)
        tot_think = sum(a.thinking_tokens for a in aggregations)
        tot_tokens = sum(a.total_tokens for a in aggregations)
        tot_turns = sum(a.turns for a in aggregations)
        tot_tools = sum(a.tool_calls for a in aggregations)
        payload: Dict[str, Any] = {
            "summary": {
                "total_profiles": len(set(a.profile for a in aggregations)),
                "total_roles": len(aggregations),
                "total_sessions": len(sessions),
                "prompt_tokens": tot_prompt,
                "completion_tokens": tot_comp,
                "thinking_tokens": tot_think,
                "total_tokens": tot_tokens,
                "turns": tot_turns,
                "tool_calls": tot_tools,
            },
            "aggregations": [a.to_dict() for a in aggregations],
        }
        if detailed:
            payload["sessions"] = [s.to_dict() for s in sessions]
        print(json.dumps(payload, indent=2))
        return 0

    if not aggregations:
        print("\n[INFO] No token telemetry or agent sessions found.")
        if profile or role or repo:
            print(f"       Filters: profile={profile}, role={role}, repo={repo}")
        return 0

    print("\n" + "=" * 115)
    print(" 📊 MULTI-AGENT TOKEN CONSUMPTION TELEMETRY (PROFILE & ROLE BREAKDOWN)")
    print("=" * 115)
    print(f" {'PROFILE':<11} | {'ROLE':<18} | {'AGENT':<6} | {'SESS':<5} | {'TURNS':<6} | {'TOOLS':<6} | {'PROMPT TOK':>12} | {'OUTPUT TOK':>12} | {'TOTAL TOK':>12} | {'LAST ACTIVE'}")
    print("-" * 115)

    tot_sess = 0
    tot_turns = 0
    tot_tools = 0
    tot_prompt = 0
    tot_comp = 0
    tot_tokens = 0

    for a in aggregations:
        tot_sess += a.sessions_count
        tot_turns += a.turns
        tot_tools += a.tool_calls
        tot_prompt += a.prompt_tokens
        tot_comp += a.completion_tokens
        tot_tokens += a.total_tokens
        last_str = a.last_active or "N/A"
        if len(last_str) > 20:
            last_str = last_str[:19] + "Z"
        print(f" {a.profile:<11} | {a.role:<18} | {a.agent_type:<6} | {a.sessions_count:<5} | {a.turns:<6} | {a.tool_calls:<6} | {a.prompt_tokens:>12,} | {a.completion_tokens:>12,} | {a.total_tokens:>12,} | {last_str}")

    print("-" * 115)
    print(f" {'TOTAL':<11} | {'':<18} | {'':<6} | {tot_sess:<5} | {tot_turns:<6} | {tot_tools:<6} | {tot_prompt:>12,} | {tot_comp:>12,} | {tot_tokens:>12,} |")
    print("=" * 115)

    if detailed and sessions:
        print("\n" + "-" * 115)
        print(" 🔍 DETAILED INDIVIDUAL SESSIONS")
        print("-" * 115)
        for s in sessions[:30]:
            print(f" • [{s.profile}:{s.role}] {s.session_id} ({s.agent_type}): {s.total_tokens:,} tokens ({s.turns} turns, {s.tool_calls} tools)")
        if len(sessions) > 30:
            print(f"   ... and {len(sessions) - 30} more sessions.")
        print("-" * 115 + "\n")
    else:
        print()

    return 0


def cmd_worktree(
    action: str = "list",
    task_id: Optional[str] = None,
    branch: Optional[str] = None,
    base_ref: str = "HEAD",
    worktree_path: Optional[str] = None,
    force: bool = False,
    delete_branch: bool = False,
    repo: Optional[str] = None,
    json_output: bool = False,
    extra_args: Optional[List[str]] = None,
) -> int:
    try:
        repo_root = resolve_repo_path(repo)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return 1

    try:
        mgr = WorktreeManager(repo_root=repo_root)
    except Exception as e:
        print(f"[ERROR] Failed to initialize WorktreeManager: {e}")
        return 1

    repo_label = f" [{os.path.basename(repo_root)}]" if repo else ""

    if action in ["list", "ls"]:
        wts = mgr.list_worktrees()
        if json_output:
            print(json.dumps([wt.to_dict() for wt in wts], indent=2))
            return 0

        print("\n" + "=" * 90)
        print(f" 🌲 ACTIVE GIT WORKTREES{repo_label}")
        print("=" * 90)
        if not wts:
            print(" [INFO] No allocated git worktrees found.")
        else:
            print(f" {'TASK ID':<12} | {'BRANCH':<25} | {'HEAD':<9} | {'STATUS':<8} | {'PATH'}")
            print("-" * 90)
            for wt in wts:
                status_str = "locked" if wt.is_locked else ("bare" if wt.is_bare else "active")
                head_str = (wt.head_commit[:8] if wt.head_commit else "N/A")
                branch_str = wt.branch or "(detached)"
                print(f" {wt.task_id:<12} | {branch_str:<25} | {head_str:<9} | {status_str:<8} | {wt.path}")
        print("=" * 90 + "\n")
        return 0

    elif action in ["create", "add", "new"]:
        if not task_id:
            print("[ERROR] 'taskctl worktree create' requires a task ID.")
            return 1
        try:
            wt = mgr.create_worktree(
                task_id=task_id,
                branch=branch,
                base_ref=base_ref,
                worktree_path=worktree_path,
                force=force,
            )
            if json_output:
                print(json.dumps(wt.to_dict(), indent=2))
            else:
                head_str = f" (HEAD: {wt.head_commit[:8]})" if wt.head_commit else ""
                print(f"[OK]{repo_label} Provisioned worktree for task [{wt.task_id}] at {wt.path} (branch: {wt.branch}){head_str}")
            return 0
        except Exception as e:
            print(f"[ERROR]{repo_label} Failed to create worktree: {e}")
            return 1

    elif action in ["remove", "rm", "delete"]:
        if not task_id:
            print("[ERROR] 'taskctl worktree remove' requires a task ID.")
            return 1
        try:
            success = mgr.remove_worktree(task_id=task_id, force=force, delete_branch=delete_branch)
            if success:
                print(f"[OK]{repo_label} Removed worktree for task [{task_id}].")
                return 0
            else:
                print(f"[WARN]{repo_label} No worktree found matching task [{task_id}].")
                return 1
        except Exception as e:
            print(f"[ERROR]{repo_label} Failed to remove worktree: {e}")
            return 1

    elif action in ["prune"]:
        try:
            out = mgr.prune_worktrees()
            print(f"[OK]{repo_label} Pruned stale git worktree metadata.")
            if out:
                print(f"       {out}")
            return 0
        except Exception as e:
            print(f"[ERROR]{repo_label} Failed to prune worktrees: {e}")
            return 1

    elif action in ["verify", "verify-stage"]:
        return cmd_stage_verify_from_args(extra_args or [], repo=repo, json_output=json_output)

    else:
        print(f"[ERROR] Unknown worktree action: '{action}'. Available: list, create, remove, prune, verify.")
        return 1


def cmd_stage_verify(
    stage_index: Optional[int] = None,
    plan_file: Optional[str] = None,
    base_ref: str = "HEAD",
    repo: Optional[str] = None,
    json_output: bool = False,
) -> int:
    from taskctl.core.graph import TaskDependencyGraph

    try:
        repo_root = resolve_repo_path(repo)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return 2

    repo_label = f" [{os.path.basename(repo_root)}]" if repo else ""

    if plan_file:
        try:
            with open(plan_file, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
        except Exception as e:
            print(f"[ERROR] Failed to read DAG execution plan from '{plan_file}': {e}")
            return 2
    else:
        try:
            task_file = get_task_file(repo_root)
            graph = TaskDependencyGraph.build_from_file(task_file, infer_sequential=True)
            cycles = graph.find_cycles()
            if cycles:
                print(f"\n[ERROR] Task dependency graph contains cycles; cannot execute stage verification:")
                for c in cycles:
                    print("   - " + " -> ".join(f"[{x}]" for x in c))
                return 2
            plan_data = graph.export_execution_plan(only_pending=True, repo=repo_root)
        except Exception as e:
            print(f"[ERROR] Failed to build DAG execution plan: {e}")
            return 2

    mgr = WorktreeManager(repo_root=repo_root)
    results = mgr.verify_plan(plan_data, stage_index=stage_index, base_ref=base_ref)

    if json_output:
        print(json.dumps([r.to_dict() for r in results], indent=2))
        if any(r.status == "ERROR" for r in results):
            return 2
        elif any(r.status == "CHANGES REQUIRED" for r in results):
            return 1
        return 0

    print("\n" + "=" * 70)
    print(f" 🔍 STAGE MERGE & DISJOINT SCOPE VERIFICATION{repo_label}")
    print("=" * 70)
    print(f" Base Reference : {base_ref}")
    print(f" Stages Checked : {len(results)}")
    print("-" * 70)

    if not results:
        print(" [INFO] No stages to verify (all tasks completed or stage filter empty).")
        print("=" * 70 + "\n")
        return 0

    has_error = False
    has_changes_required = False

    for r in results:
        parallel_str = " (Parallel: True)" if len(r.task_merge_results) > 1 else ""
        print(f" Stage {r.stage_index} (Concurrency: {len(r.task_merge_results)}{parallel_str}):")

        for t in r.task_merge_results:
            t_id = t.get("task_id", "")
            branch = t.get("branch", "")
            status = t.get("status", "")
            if status == "clean":
                ins = t.get("insertions", 0)
                dels = t.get("deletions", 0)
                cnt = len(t.get("files", []))
                print(f"   • Task [{t_id}] ({branch}): ✅ CLEAN ({cnt} file(s), +{ins}/-{dels})")
            elif status == "conflict":
                print(f"   • Task [{t_id}] ({branch}): ❌ MERGE CONFLICT")
                for cf in t.get("conflict_files", []):
                    print(f"       - Conflict: {cf}")
            elif status == "missing_branch":
                print(f"   • Task [{t_id}] ({branch}): ⚠️  BRANCH NOT FOUND LOCALLY")
            else:
                msg = t.get("message") or status
                print(f"   • Task [{t_id}] ({branch}): ❌ ERROR ({msg})")

        if r.disjoint_scopes_clean:
            if len(r.task_merge_results) > 1:
                print("   Scopes: ✅ DISJOINT (0 overlapping files)")
        else:
            print(f"   Scopes: ❌ OVERLAPPING ({len(r.scope_conflicts)} conflict(s)):")
            for sc in r.scope_conflicts:
                tasks_str = ", ".join(f"[{tid}]" for tid in sc.conflicting_tasks)
                branches_str = ", ".join(sc.conflicting_branches)
                print(f"       - {sc.file_path} (modified by {tasks_str} in branches: {branches_str})")

        print("-" * 70)

        if r.status == "ERROR":
            has_error = True
        elif r.status == "CHANGES REQUIRED":
            has_changes_required = True

    if has_error:
        print(" FINAL VERDICT: [ERROR] (exit code 2)")
        print("=" * 70 + "\n")
        return 2
    elif has_changes_required:
        print(" FINAL VERDICT: [CHANGES REQUIRED] (exit code 1)")
        print("=" * 70 + "\n")
        return 1
    else:
        print(" FINAL VERDICT: [APPROVED] (exit code 0)")
        print("=" * 70 + "\n")
        return 0


def cmd_stage_verify_from_args(
    args: List[str],
    repo: Optional[str] = None,
    json_output: bool = False,
) -> int:
    stage_idx = None
    plan_file = None
    base_ref = "HEAD"
    i = 0
    while i < len(args):
        if args[i] in ["--stage", "-s"] and i + 1 < len(args):
            try:
                stage_idx = int(args[i + 1])
            except ValueError:
                print(f"[ERROR] Invalid stage index '{args[i + 1]}'")
                return 2
            i += 2
        elif args[i] in ["--plan", "-p"] and i + 1 < len(args):
            plan_file = args[i + 1]
            i += 2
        elif args[i] in ["--base", "-b"] and i + 1 < len(args):
            base_ref = args[i + 1]
            i += 2
        elif args[i] in ["--repo", "-r"] and i + 1 < len(args):
            repo = args[i + 1]
            i += 2
        elif args[i] in ["--json"]:
            json_output = True
            i += 1
        elif not args[i].startswith("-") and stage_idx is None:
            try:
                stage_idx = int(args[i])
            except ValueError:
                pass
            i += 1
        else:
            i += 1
    return cmd_stage_verify(
        stage_index=stage_idx,
        plan_file=plan_file,
        base_ref=base_ref,
        repo=repo,
        json_output=json_output,
    )


def cmd_recall(
    query: str,
    component: Optional[str] = None,
    json_output: bool = False,
    detailed: bool = False,
    repo: Optional[str] = None,
    limit: int = 10,
) -> int:
    """Recall knowledge cards matching query term with SQLite FTS5 BM25 ranking."""
    try:
        with KnowledgeEngine(repo_path=repo) as engine:
            results = engine.search(query=query, component=component, limit=limit)
    except Exception as e:
        if json_output:
            print(json.dumps({"error": str(e), "results": []}))
        else:
            print(f"[ERROR] Failed to search knowledge cards: {e}")
        return 1

    if json_output:
        payload = [
            {
                "id": card.id,
                "title": card.title,
                "type": card.type,
                "score": score,
                "components": card.components,
                "error_keywords": card.error_keywords,
                "platforms": card.platforms,
                "invariants_affected": card.invariants_affected,
                "problem": card.problem,
                "solution": card.solution,
                "never_do": card.never_do,
                "filepath": card.filepath,
            }
            for card, score in results
        ]
        print(json.dumps(payload, indent=2))
        return 0

    print("\n" + "=" * 70)
    print(" 🧠 KNOWLEDGE BASE RECALL (SQLite FTS5 / BM25)")
    print(f' Query     : "{query}"')
    if component:
        print(f" Component : {component}")
    print(f" Matches   : {len(results)} card(s)")
    print("=" * 70)

    if not results:
        print("\n [INFO] No knowledge cards found matching query.")
        print("=" * 70 + "\n")
        return 0

    for idx, (card, score) in enumerate(results, start=1):
        score_str = f"BM25: {score:.6f}" if score > 0 else "all"
        print(f"\n[{idx}] 🎯 [{card.id}] {card.title} ({card.type}) [{score_str}]")
        if card.components:
            print(f"    Components : {', '.join(card.components)}")
        if card.platforms:
            print(f"    Platforms  : {', '.join(card.platforms)}")
        if card.invariants_affected:
            print(f"    Invariants : {', '.join(card.invariants_affected)}")
        if card.error_keywords:
            print(f"    Keywords   : {', '.join(card.error_keywords)}")

        if detailed:
            if card.problem:
                print("\n    📌 Problem:")
                for l in card.problem.splitlines():
                    print(f"       {l}")
            if card.solution:
                print("\n    💡 Solution:")
                for l in card.solution.splitlines():
                    print(f"       {l}")
            if card.never_do:
                print("\n    ⚠️  Never Do:")
                for l in card.never_do.splitlines():
                    print(f"       {l}")
        else:
            if card.solution:
                sol_first = card.solution.strip().splitlines()[0] if card.solution.strip() else ""
                if len(card.solution.strip().splitlines()) > 1:
                    sol_first += " [...]"
                print(f"    💡 Solution : {sol_first}")
            elif card.problem:
                prob_first = card.problem.strip().splitlines()[0] if card.problem.strip() else ""
                print(f"    📌 Problem  : {prob_first}")

    print("\n" + "=" * 70 + "\n")
    return 0


def cmd_reflex(
    stderr_content: Optional[str] = None,
    file_path: Optional[str] = None,
    json_output: bool = False,
    repo: Optional[str] = None,
    limit: int = 5,
) -> int:
    """Headless error signature reflex evaluator against stack traces and error logs."""
    raw_stderr = ""
    if stderr_content is not None:
        raw_stderr = stderr_content
    elif file_path:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                raw_stderr = f.read()
        except OSError as e:
            if json_output:
                print(json.dumps({"error": f"Failed to read file: {e}", "matches": []}))
            else:
                print(f"[ERROR] Failed to read stderr file '{file_path}': {e}")
            return 1
    elif not sys.stdin.isatty():
        try:
            raw_stderr = sys.stdin.read()
        except Exception:
            raw_stderr = ""

    if not raw_stderr.strip():
        if json_output:
            print(json.dumps({"error": "No stderr content provided", "matches": []}))
        else:
            print("[WARN] No stderr log provided to reflex evaluator. Use --stderr \"<log>\" or pipe via stdin.")
        return 1

    try:
        with KnowledgeEngine(repo_path=repo) as engine:
            matches = engine.reflex(stderr_content=raw_stderr, limit=limit)
    except Exception as e:
        if json_output:
            print(json.dumps({"error": str(e), "matches": []}))
        else:
            print(f"[ERROR] Reflex evaluation error: {e}")
        return 1

    if json_output:
        payload = [
            {
                "id": card.id,
                "title": card.title,
                "type": card.type,
                "score": score,
                "matched_keywords": matched_kw,
                "components": card.components,
                "problem": card.problem,
                "solution": card.solution,
                "never_do": card.never_do,
                "invariants_affected": card.invariants_affected,
            }
            for card, score, matched_kw in matches
        ]
        print(json.dumps(payload, indent=2))
        return 0

    print("\n" + "=" * 70)
    print(f" ⚡ KNOWLEDGE ERROR REFLEX EVALUATOR ({len(matches)} match(es))")
    print("=" * 70)

    if not matches:
        print("\n [INFO] No matching error reflex knowledge card found for provided stderr.")
        print("=" * 70 + "\n")
        return 0

    for idx, (card, score, matched_kw) in enumerate(matches, start=1):
        print(f"\n[{idx}] 🎯 [{card.id}] {card.title} ({card.type}) [Reflex Score: {score:.1f}]")
        if matched_kw:
            sigs = ", ".join(f'"{k}"' for k in matched_kw)
            print(f"    Matched Signatures : {sigs}")
        if card.components:
            print(f"    Components         : {', '.join(card.components)}")

        if card.solution:
            print("\n    💡 IMMEDIATE SOLUTION:")
            for l in card.solution.splitlines():
                print(f"       {l}")

        if card.never_do:
            print("\n    ⚠️  NEVER DO:")
            for l in card.never_do.splitlines():
                print(f"       {l}")

        if card.problem:
            print("\n    📌 Failure Mode / Problem:")
            for l in card.problem.splitlines():
                print(f"       {l}")

    print("\n" + "=" * 70 + "\n")
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ["-h", "--help", "help"]:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    if cmd == "init":
        cmd_init()
    elif cmd == "status":
        repo = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["--repo", "-r"] and i + 1 < len(args):
                repo = args[i + 1]
                i += 2
            else:
                i += 1
        cmd_status(repo=repo)
    elif cmd == "backlog":
        cmd_backlog()
    elif cmd == "quota":
        refresh = "--refresh" in sys.argv[2:]
        cmd_quota(refresh=refresh)
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
        repo = None
        prompt_parts = []
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["--repo", "-r"] and i + 1 < len(args):
                repo = args[i + 1]
                i += 2
            else:
                prompt_parts.append(args[i])
                i += 1
        if not prompt_parts:
            print("[ERROR] Please provide a planning prompt: taskctl plan '<prompt>' [--repo <path|name>]")
            sys.exit(1)
        plan_prompt = " ".join(prompt_parts)
        cmd_plan(prompt=plan_prompt, repo=repo)
    elif cmd == "next":
        weight = "medium"
        target_agent = None
        handoff = True
        repo = None
        runner = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["light", "medium", "heavy"]:
                weight = args[i]
                i += 1
            elif args[i] in ["--weight", "-w"] and i + 1 < len(args):
                weight = args[i + 1]
                i += 2
            elif args[i] in ["--agent", "-a"] and i + 1 < len(args):
                target_agent = args[i + 1]
                i += 2
            elif args[i] in ["--repo", "-r"] and i + 1 < len(args):
                repo = args[i + 1]
                i += 2
            elif args[i] in ["--runner", "-R"] and i + 1 < len(args):
                runner = args[i + 1]
                i += 2
            elif args[i] in ["--no-handoff", "--skip-handoff"]:
                handoff = False
                i += 1
            else:
                i += 1
        if runner is not None:
            cmd_next(weight=weight, target_agent=target_agent, handoff=handoff, repo=repo, runner=runner)
        else:
            cmd_next(weight=weight, target_agent=target_agent, handoff=handoff, repo=repo)
    elif cmd == "audit":
        delegate = False
        agent_name = None
        domain_lint = False
        repo = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["--delegate", "--hybrid", "-d"]:
                delegate = True
                i += 1
            elif args[i] in ["--domain-lint"]:
                domain_lint = True
                i += 1
            elif args[i] in ["--agent", "-a"] and i + 1 < len(args):
                agent_name = args[i + 1]
                delegate = True
                i += 2
            elif args[i] in ["--repo", "-r"] and i + 1 < len(args):
                repo = args[i + 1]
                i += 2
            else:
                i += 1
        sys.exit(cmd_audit(delegate=delegate, agent_name=agent_name, domain_lint=domain_lint, repo=repo))
    elif cmd == "done":
        promote = False
        custom_msg = None
        target_agent = None
        handoff = True
        weight = "medium"
        repo = None
        runner = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["-p", "--promote"]:
                promote = True
                i += 1
            elif args[i] in ["--agent", "-a"] and i + 1 < len(args):
                target_agent = args[i + 1]
                i += 2
            elif args[i] in ["--repo", "-r"] and i + 1 < len(args):
                repo = args[i + 1]
                i += 2
            elif args[i] in ["--runner", "-R"] and i + 1 < len(args):
                runner = args[i + 1]
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
        if runner is not None:
            cmd_done(custom_msg=custom_msg, promote=promote, weight=weight, target_agent=target_agent, handoff=handoff, repo=repo, runner=runner)
        else:
            cmd_done(custom_msg=custom_msg, promote=promote, weight=weight, target_agent=target_agent, handoff=handoff, repo=repo)
    elif cmd == "sync":
        pull = "--pull" in sys.argv[2:]
        hud = "--hud" in sys.argv[2:]
        cmd_sync(pull=pull, hud=hud)
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
        export_plan = False
        out_file = None
        repo = None
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
            elif args[i] in ["--export-plan", "-p", "--plan"]:
                export_plan = True
                if i + 1 < len(args) and not args[i + 1].startswith("-"):
                    out_file = args[i + 1]
                    i += 2
                else:
                    i += 1
            elif args[i] in ["-o", "--out", "--output"] and i + 1 < len(args):
                out_file = args[i + 1]
                i += 2
            elif args[i] in ["--repo", "-r"] and i + 1 < len(args):
                repo = args[i + 1]
                i += 2
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
            export_plan=export_plan,
            out_file=out_file,
            repo=repo,
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
    elif cmd == "guard":
        if len(sys.argv) == 2:
            subcmd = "status"
            args = []
        elif sys.argv[2] in ["-h", "--help", "help"]:
            print("Usage: taskctl guard [eval|status|test] [options]")
            print("  taskctl guard status [--json]")
            print("  taskctl guard eval <cmd> [--role <role>] [--json]")
            print("  taskctl guard test [--json]")
            sys.exit(0)
        else:
            subcmd = sys.argv[2].lower()
            args = sys.argv[3:]
        sys.exit(cmd_guard(subcmd, args))
    elif cmd in ["tokens", "token"]:
        profile = None
        role = None
        repo = None
        json_output = False
        detailed = False
        limit = 100
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["--profile", "-p"] and i + 1 < len(args):
                profile = args[i + 1]
                i += 2
            elif args[i] in ["--role", "-r"] and i + 1 < len(args):
                role = args[i + 1]
                i += 2
            elif args[i] in ["--repo"] and i + 1 < len(args):
                repo = args[i + 1]
                i += 2
            elif args[i] in ["--limit", "-l"] and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    limit = 100
                i += 2
            elif args[i] in ["--json"]:
                json_output = True
                i += 1
            elif args[i] in ["--detailed", "-d"]:
                detailed = True
                i += 1
            elif not args[i].startswith("-") and profile is None:
                profile = args[i]
                i += 1
            elif not args[i].startswith("-") and role is None:
                role = args[i]
                i += 1
            else:
                i += 1
        sys.exit(cmd_tokens(
            profile=profile,
            role=role,
            repo=repo,
            json_output=json_output,
            detailed=detailed,
            limit=limit,
        ))
    elif cmd in ["worktree", "worktrees", "wt"]:
        action = "list"
        task_id = None
        branch = None
        base_ref = "HEAD"
        worktree_path = None
        force = False
        delete_branch = False
        repo = None
        json_output = False
        extra_args = []
        args = sys.argv[2:]
        i = 0
        if args and not args[0].startswith("-"):
            action = args[0].lower()
            i = 1

        while i < len(args):
            if args[i] in ["--repo", "-r"] and i + 1 < len(args):
                repo = args[i + 1]
                i += 2
            elif args[i] in ["--branch", "-b"] and i + 1 < len(args):
                branch = args[i + 1]
                i += 2
            elif args[i] in ["--base"] and i + 1 < len(args):
                base_ref = args[i + 1]
                i += 2
            elif args[i] in ["--path", "-p"] and i + 1 < len(args):
                worktree_path = args[i + 1]
                i += 2
            elif args[i] in ["--force", "-f"]:
                force = True
                i += 1
            elif args[i] in ["--delete-branch", "-D"]:
                delete_branch = True
                i += 1
            elif args[i] in ["--json"]:
                json_output = True
                i += 1
            elif not args[i].startswith("-") and task_id is None and action in ["create", "add", "new", "remove", "rm", "delete"]:
                task_id = args[i]
                i += 1
            else:
                extra_args.append(args[i])
                i += 1

        sys.exit(cmd_worktree(
            action=action,
            task_id=task_id,
            branch=branch,
            base_ref=base_ref,
            worktree_path=worktree_path,
            force=force,
            delete_branch=delete_branch,
            repo=repo,
            json_output=json_output,
            extra_args=extra_args,
        ))
    elif cmd in ["stage", "stages"]:
        subcmd = "verify"
        args = sys.argv[2:]
        if args and not args[0].startswith("-"):
            subcmd = args[0].lower()
            args = args[1:]
        if subcmd in ["verify", "check"]:
            sys.exit(cmd_stage_verify_from_args(args))
        else:
            print(f"[ERROR] Unknown stage subcommand: '{subcmd}'. Available: verify.")
            sys.exit(1)
    elif cmd in ["recall", "k-search", "knowledge"]:
        query_parts: List[str] = []
        component = None
        json_output = False
        detailed = False
        repo = None
        limit = 10
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["-c", "--component"] and i + 1 < len(args):
                component = args[i + 1]
                i += 2
            elif args[i] in ["--json"]:
                json_output = True
                i += 1
            elif args[i] in ["-d", "--detailed"]:
                detailed = True
                i += 1
            elif args[i] in ["-r", "--repo"] and i + 1 < len(args):
                repo = args[i + 1]
                i += 2
            elif args[i] in ["-l", "--limit"] and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    limit = 10
                i += 2
            elif not args[i].startswith("-"):
                query_parts.append(args[i])
                i += 1
            else:
                i += 1
        query = " ".join(query_parts) if query_parts else "*"
        sys.exit(cmd_recall(
            query=query,
            component=component,
            json_output=json_output,
            detailed=detailed,
            repo=repo,
            limit=limit,
        ))
    elif cmd in ["reflex", "k-reflex"]:
        stderr_content = None
        file_path = None
        json_output = False
        repo = None
        limit = 5
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["-s", "--stderr"] and i + 1 < len(args):
                stderr_content = args[i + 1]
                i += 2
            elif args[i] in ["-f", "--file"] and i + 1 < len(args):
                file_path = args[i + 1]
                i += 2
            elif args[i] in ["--json"]:
                json_output = True
                i += 1
            elif args[i] in ["-r", "--repo"] and i + 1 < len(args):
                repo = args[i + 1]
                i += 2
            elif args[i] in ["-l", "--limit"] and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    limit = 5
                i += 2
            elif not args[i].startswith("-") and stderr_content is None:
                stderr_content = args[i]
                i += 1
            else:
                i += 1
        sys.exit(cmd_reflex(
            stderr_content=stderr_content,
            file_path=file_path,
            json_output=json_output,
            repo=repo,
            limit=limit,
        ))
    else:
        print(f"Unknown command: '{cmd}'. Run 'taskctl --help' for usage.")
        sys.exit(1)

if __name__ == "__main__":
    main()
