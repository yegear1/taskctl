#!/usr/bin/env python3
"""
taskctl - Task Lifecycle, Contract Engine & Multi-Agent CLI.

Commands:
  taskctl ws [name]        Create and wire complete Maestri workspace for current repo.
  taskctl init             Initialize .agent/TASK.md and AGENTS.md in current repository.
  taskctl status           Show active task, criteria, git status, and quota route.
  taskctl quota            Display real-time Multigravity quota across all profiles.
  taskctl plan "<prompt>"  Ask the Planner agent to decompose tasks into .agent/TASK.md.
  taskctl next [--weight]  Promote next backlog task to active (RUNNING) and notify Dev.
  taskctl audit            Trigger the Scope Auditor to verify diff.
                           Returns semantic exit codes:
                             0: [APPROVED] - Ready for taskctl done.
                             1: [CHANGES REQUIRED] - Prints Required Action for auto-remediation.
                             2: [REJECTED] - Critical failure; escalates to Planner/human.
  taskctl done [msg] [-p]  Validate DoD, create double atomic commit (code + governance),
                           and dispatch webhook notifications.
  taskctl lint-commit [msg] [--file <path>]  Validate commit message against Conventional Commits.
  taskctl sync             Sync current .agent/TASK.md to canvas note.
  taskctl backlog          List upcoming backlog items.
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
)
from taskctl.webhooks.dispatcher import WebhookDispatcher
from taskctl.telemetry import get_telemetry_emitter, TelemetryEvent

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

def cmd_next(weight: str = "medium"):
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

    backlog_line_pat = rf"-\s*\[ \]\s*\*\*\[{re.escape(next_id)}\]\*\*\s*{re.escape(next_title)}\n?"
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
        details={
            "actor": f"{best_profile} ({best_model})",
            "weight": weight,
            "profile": best_profile,
            "model": best_model,
        },
    )

def cmd_audit() -> int:
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

    print("\n" + "="*58)
    print(" 🛡️ SCOPE AUDITOR VERIFICATION")
    print("="*58)

    start_audit = time.perf_counter()
    auditor = ScopeAuditor()
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

    webhook = WebhookDispatcher()
    webhook.send_event(
        event_type="audit",
        task_id=active_task.get("id", "XX.Y"),
        title=active_task.get("title", "Ad-hoc task"),
        status=verdict.status,
        details={
            "exit_code": verdict.exit_code,
            "rule_count": len(verdict.results),
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
        details={
            "exit_code": verdict.exit_code,
            "rule_count": len(verdict.results),
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

def cmd_lint_commit(msg: Optional[str] = None, file_path: Optional[str] = None) -> int:
    raw_content = ""
    if file_path:
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
        print("[ERROR] No commit message provided. Usage: taskctl lint-commit '<message>' or taskctl lint-commit --file <file>")
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

def cmd_done(custom_msg: Optional[str] = None, promote: bool = False, weight: str = "medium", notify_planner: bool = True):
    task_file = get_task_file()
    with open(task_file, "r", encoding="utf-8") as f:
        content = f.read()

    active_task, backlog = parse_task_md(content)
    task_id = active_task.get("id", "XX.Y")
    title = active_task.get("title", "Ad-hoc task")

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
            return
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
        details={"commit": commit_hash, "governance_commit": gov_hash},
    )

    if promote:
        cmd_next(weight=weight)

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
    elif cmd == "next":
        weight = "medium"
        for arg in sys.argv[2:]:
            if arg in ["light", "medium", "heavy"]:
                weight = arg
        cmd_next(weight=weight)
    elif cmd == "audit":
        sys.exit(cmd_audit())
    elif cmd == "done":
        promote = False
        custom_msg = None
        for arg in sys.argv[2:]:
            if arg in ["-p", "--promote"]:
                promote = True
            elif not arg.startswith("-"):
                custom_msg = arg
        cmd_done(custom_msg=custom_msg, promote=promote)
    elif cmd == "sync":
        task_file = get_task_file()
        with open(task_file, "r", encoding="utf-8") as f:
            content = f.read()
        sync_task_cockpit_note(content)
        print("[OK] Real-time canvas sync completed.")
    elif cmd == "notify":
        msg = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Test notification"
        webhook = WebhookDispatcher()
        if not webhook.is_configured():
            print("[WARN] Webhook URL not configured. Set TASKCTL_WEBHOOK_URL.")
            sys.exit(1)
        ok = webhook.send_event(
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
            details={"summary": msg},
        )
        print("[OK] Notification sent." if ok else "[ERROR] Notification failed.")
    elif cmd in ["lint-commit", "commit-lint"]:
        file_path = None
        msg_parts = []
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ["-f", "--file"] and i + 1 < len(args):
                file_path = args[i + 1]
                i += 2
            else:
                msg_parts.append(args[i])
                i += 1
        msg = " ".join(msg_parts) if msg_parts else None
        sys.exit(cmd_lint_commit(msg=msg, file_path=file_path))
    else:
        print(f"Unknown command: '{cmd}'. Run 'taskctl --help' for usage.")
        sys.exit(1)

if __name__ == "__main__":
    main()
