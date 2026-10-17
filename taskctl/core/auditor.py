"""Scope Auditor rule-based policy engine for taskctl.

Evaluates git hygiene, task contracts, syntax validity, and security boundaries.
Returns semantic exit codes:
- 0: APPROVED
- 1: CHANGES REQUIRED
- 2: REJECTED
"""

from __future__ import annotations

import os
import re
import time
import py_compile
import subprocess
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from taskctl.core.parser import parse_task_md
from taskctl.core.commits import parse_conventional_commit


class AuditSeverity(IntEnum):
    APPROVED = 0
    CHANGES_REQUIRED = 1
    REJECTED = 2

    @property
    def label(self) -> str:
        if self == AuditSeverity.APPROVED:
            return "APPROVED"
        if self == AuditSeverity.CHANGES_REQUIRED:
            return "CHANGES REQUIRED"
        return "REJECTED"


@dataclass
class RuleResult:
    rule_name: str
    severity: AuditSeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return int(self.severity)


@dataclass
class AuditVerdict:
    status: str
    exit_code: int
    results: List[RuleResult]

    @property
    def is_approved(self) -> bool:
        return self.exit_code == 0


@dataclass
class RemediationAction:
    """Actionable remediation item derived from an audit rule failure."""

    rule_name: str
    severity: AuditSeverity
    diagnosis: str
    suggested_fix: str
    remediation_command: Optional[str] = None
    affected_files: List[str] = field(default_factory=list)
    auto_fixed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "severity": self.severity.label,
            "diagnosis": self.diagnosis,
            "suggested_fix": self.suggested_fix,
            "remediation_command": self.remediation_command,
            "affected_files": self.affected_files,
            "auto_fixed": self.auto_fixed,
        }


@dataclass
class RemediationPackage:
    """Self-contained remediation payload dispatched to Developer for automated correction."""

    task_id: str
    task_title: str
    status: str
    exit_code: int
    actions: List[RemediationAction] = field(default_factory=list)
    knowledge_remedies: List[Dict[str, Any]] = field(default_factory=list)
    auto_fixed_items: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_title": self.task_title,
            "status": self.status,
            "exit_code": self.exit_code,
            "actions": [a.to_dict() for a in self.actions],
            "knowledge_remedies": self.knowledge_remedies,
            "auto_fixed_items": self.auto_fixed_items,
        }

    def format_markdown(self) -> str:
        """Render remediation package into token-dense machine-parseable markdown for agents."""
        lines = [
            f"# 🛠️ Audit Remediation Package: Task [{self.task_id}]",
            f"**Task Title:** {self.task_title}",
            f"**Audit Status:** [{self.status}] (Exit code: {self.exit_code})",
            "",
        ]
        if self.auto_fixed_items:
            lines.append("### ⚡ Automatically Resolved Mechanical Fixes:")
            for item in self.auto_fixed_items:
                lines.append(f"- ✅ {item}")
            lines.append("")

        if self.actions:
            lines.append("### ⚠️ Required Corrections for Developer Agent:")
            for a in self.actions:
                status_icon = "✅" if a.auto_fixed else "❌"
                lines.append(f"#### {status_icon} Rule: `{a.rule_name}` [{a.severity.label}]")
                lines.append(f"- **Diagnosis:** {a.diagnosis}")
                lines.append(f"- **Suggested Fix:** {a.suggested_fix}")
                if a.remediation_command:
                    lines.append(f"- **Recommended Command:** `{a.remediation_command}`")
                if a.affected_files:
                    lines.append(f"- **Affected Files:** {', '.join(a.affected_files)}")
                lines.append("")

        if self.knowledge_remedies:
            lines.append("### 🧠 Approved Knowledge Base Remedies:")
            for k in self.knowledge_remedies:
                lines.append(f"- **[{k.get('id', 'K-???')}] {k.get('title', '')}** ({k.get('type', 'gotcha')})")
                sol = k.get("solution", "")
                if sol:
                    clean_sol = sol.strip().replace("\n", " ")[:200]
                    lines.append(f"  *Solution:* {clean_sol}...")
            lines.append("")

        lines.append("---")
        lines.append("👉 **Developer Instructions:** Apply the corrective actions above and re-verify with `taskctl audit`.")
        return "\n".join(lines)


class GitHygieneRule:
    """Verifies that working tree / staged changes have no conflict markers or whitespace errors."""

    rule_name: str = "git-hygiene"

    def evaluate(self, repo_path: Path) -> RuleResult:
        try:
            res = subprocess.run(
                ["git", "diff", "--check"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                err_lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
                return RuleResult(
                    rule_name=self.rule_name,
                    severity=AuditSeverity.CHANGES_REQUIRED,
                    message="git diff --check detected conflict markers, whitespace errors, or unmerged paths.",
                    details={"errors": err_lines[:5]},
                )
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.APPROVED,
                message="Git diff check passed cleanly with zero whitespace or conflict errors.",
            )
        except Exception as e:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Failed to execute git hygiene check: {e}",
            )


class TaskContractRule:
    """Verifies integrity and invariants of .agent/TASK.md."""

    rule_name: str = "task-contract"
    VALID_STATUSES = {"READY FOR PLANNING", "PLANNING", "RUNNING"}
    ID_PATTERN = re.compile(r"^\d{2}\.\d+(\.\d+)*$")

    def evaluate(self, repo_path: Path) -> RuleResult:
        task_file = repo_path / ".agent" / "TASK.md"
        if not task_file.exists():
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.REJECTED,
                message="Missing required contract file: .agent/TASK.md",
            )

        try:
            content = task_file.read_text(encoding="utf-8")
            active_task, backlog = parse_task_md(content)
        except Exception as e:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.REJECTED,
                message=f"Failed to parse .agent/TASK.md: {e}",
            )

        if not active_task:
            if re.search(r"\*\(No active task", content, re.IGNORECASE):
                return RuleResult(
                    rule_name=self.rule_name,
                    severity=AuditSeverity.APPROVED,
                    message="Task contract [.agent/TASK.md] verified: Idle workbench (no active task).",
                    details={"task_id": "IDLE", "status": "IDLE", "backlog_count": len(backlog)},
                )

        task_id = active_task.get("id", "").strip()
        status = active_task.get("status", "").strip()
        title = active_task.get("title", "").strip()

        if not task_id or (task_id != "XX.Y" and not self.ID_PATTERN.match(task_id)):
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.REJECTED,
                message=f"Invalid task ID schema: '{task_id}'. Expected format '[XX.Y]'.",
            )

        if status not in self.VALID_STATUSES:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Invalid task status: '{status}'. Expected one of {sorted(self.VALID_STATUSES)}.",
            )

        if not title:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message="Active task has an empty title.",
            )

        return RuleResult(
            rule_name=self.rule_name,
            severity=AuditSeverity.APPROVED,
            message=f"Task contract [.agent/TASK.md] verified: Task [{task_id}] '{title}' ({status}).",
            details={"task_id": task_id, "status": status, "backlog_count": len(backlog)},
        )


_DOMAIN_LINT_TRUTHY = {"1", "true", "yes", "on"}


def domain_lint_enabled(flag: bool = False) -> bool:
    """Return whether opt-in domain lint rules should run.

    Enabled by an explicit CLI flag or by TASKCTL_DOMAIN_LINT set to
    1, true, yes, or on. Default is off so the audit verdict stays unchanged.
    """
    if flag:
        return True
    raw = os.environ.get("TASKCTL_DOMAIN_LINT", "").strip().lower()
    return raw in _DOMAIN_LINT_TRUTHY


class AcceptanceCriteriaRule:
    """Opt-in check that the active task lists non-empty acceptance criteria."""

    rule_name: str = "dod-criteria"

    def evaluate(self, repo_path: Path) -> RuleResult:
        task_file = repo_path / ".agent" / "TASK.md"
        if not task_file.exists():
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.REJECTED,
                message="Missing required contract file: .agent/TASK.md",
            )

        try:
            content = task_file.read_text(encoding="utf-8")
            active_task, _backlog = parse_task_md(content)
        except Exception as e:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.REJECTED,
                message=f"Failed to parse .agent/TASK.md: {e}",
            )

        criteria = active_task.get("criteria") or []
        if not criteria:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message="Active task has no acceptance criteria.",
            )

        blank_indexes = [
            index
            for index, item in enumerate(criteria)
            if not str(item.get("text", "")).strip()
        ]
        if blank_indexes:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message="Active task has acceptance criteria with empty text.",
                details={"blank_indexes": blank_indexes},
            )

        return RuleResult(
            rule_name=self.rule_name,
            severity=AuditSeverity.APPROVED,
            message=f"Acceptance criteria verified: {len(criteria)} item(s).",
            details={"criteria_count": len(criteria)},
        )


class SyntaxCompilationRule:
    """Verifies all Python source files in the repository compile cleanly without syntax errors."""

    rule_name: str = "syntax-compilation"
    IGNORED_DIRS = {".git", ".venv", "venv", "build", "dist", "__pycache__", ".tox", ".eggs"}

    def evaluate(self, repo_path: Path) -> RuleResult:
        failed_files: List[Dict[str, str]] = []

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in self.IGNORED_DIRS]
            for file in files:
                if file.endswith(".py"):
                    full_path = Path(root) / file
                    try:
                        py_compile.compile(str(full_path), doraise=True)
                    except py_compile.PyCompileError as e:
                        failed_files.append({"file": str(full_path.relative_to(repo_path)), "error": str(e)})

        if failed_files:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Python syntax compilation failed on {len(failed_files)} file(s).",
                details={"errors": failed_files[:5]},
            )

        return RuleResult(
            rule_name=self.rule_name,
            severity=AuditSeverity.APPROVED,
            message="All Python source files compiled with 0 syntax errors.",
        )


class SecretsBoundaryRule:
    """Verifies that no private keys, environment secrets, or socket files are staged."""

    rule_name: str = "secrets-boundary"
    FORBIDDEN_EXACT = {".env", "id_rsa", "id_ed25519", "credentials.json", "token.secret"}
    FORBIDDEN_SUFFIXES = {".key", ".pem", ".pfx", ".p12", ".sock"}

    def evaluate(self, repo_path: Path) -> RuleResult:
        try:
            res = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            staged = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        except Exception as e:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Failed to inspect git index for staged secrets: {e}",
            )

        leaked: List[str] = []
        for file_path in staged:
            basename = os.path.basename(file_path)
            if basename in self.FORBIDDEN_EXACT:
                leaked.append(file_path)
            elif basename.startswith(".env.") and not basename.endswith(".example"):
                leaked.append(file_path)
            elif any(basename.endswith(sfx) for sfx in self.FORBIDDEN_SUFFIXES):
                leaked.append(file_path)

        if leaked:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.REJECTED,
                message=f"Security boundary violation: Sensitive secret/key file(s) staged: {leaked}",
                details={"leaked_files": leaked},
            )

        return RuleResult(
            rule_name=self.rule_name,
            severity=AuditSeverity.APPROVED,
            message="No staged credentials, secret files, or private keys detected.",
        )


class CommitConventionRule:
    """Verifies that the latest git commit on the current branch complies with Conventional Commits."""

    rule_name: str = "commit-convention"

    def evaluate(self, repo_path: Path) -> RuleResult:
        try:
            rev_check = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if rev_check.returncode != 0:
                return RuleResult(
                    rule_name=self.rule_name,
                    severity=AuditSeverity.APPROVED,
                    message="Repository has no commits yet; commit convention check skipped.",
                )

            log_res = subprocess.run(
                ["git", "log", "-1", "--pretty=%B"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if log_res.returncode != 0:
                return RuleResult(
                    rule_name=self.rule_name,
                    severity=AuditSeverity.CHANGES_REQUIRED,
                    message=f"Failed to read git commit log: {log_res.stderr.strip()}",
                )

            commit_msg = log_res.stdout
            if commit_msg.strip().lower().startswith("merge"):
                return RuleResult(
                    rule_name=self.rule_name,
                    severity=AuditSeverity.APPROVED,
                    message="Latest commit (HEAD) is a merge commit; conventional commit check skipped.",
                )
            validation = parse_conventional_commit(commit_msg)
            if not validation.is_valid:
                return RuleResult(
                    rule_name=self.rule_name,
                    severity=AuditSeverity.CHANGES_REQUIRED,
                    message=f"Latest commit (HEAD) violates Conventional Commits: {'; '.join(validation.errors)}",
                    details={"errors": validation.errors, "raw_message": commit_msg.strip()},
                )

            header = validation.commit.header if validation.commit else "HEAD"
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.APPROVED,
                message=f"Latest commit conforms to Conventional Commits: '{header}'.",
                details={"header": header, "type": validation.commit.type if validation.commit else ""},
            )
        except Exception as e:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Failed to evaluate commit conventions: {e}",
            )


def parse_systems_involved(systems_str: str) -> List[str]:
    """Parse declared systems list from TASK.md string, e.g. '[path/a, path/b]'."""
    clean = systems_str.strip()
    if clean.startswith("[") and clean.endswith("]"):
        clean = clean[1:-1]
    if not clean:
        return []
    items: List[str] = []
    for item in clean.split(","):
        stripped = item.strip().strip("'\"")
        if stripped:
            items.append(stripped)
    return items


def is_file_in_scope(file_path: str, declared_systems: List[str]) -> bool:
    """Check if file path matches declared systems or is an exempt governance file."""
    norm_path = os.path.normpath(file_path).replace("\\", "/")
    if norm_path.startswith(".agent/") or norm_path in {"AGENTS.md", "README.md", ".gitignore", "pyproject.toml"}:
        return True

    if not declared_systems or "*" in declared_systems:
        return True

    for declared in declared_systems:
        norm_decl = os.path.normpath(declared).replace("\\", "/")
        if norm_decl == "*" or norm_path == norm_decl:
            return True
        if norm_path.startswith(norm_decl.rstrip("/") + "/"):
            return True
    return False


def get_modified_files(repo_path: Path) -> List[str]:
    """Get list of modified/added/untracked files from working tree, index, or latest commit."""
    files: List[str] = []
    res_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )
    if res_status.returncode == 0:
        for line in res_status.stdout.splitlines():
            if not line.strip():
                continue
            path_part = line[3:].strip()
            if " -> " in path_part:
                path_part = path_part.split(" -> ")[1].strip()
            path_part = path_part.strip('"\'')
            if path_part:
                files.append(path_part)

    if not files:
        res_head = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if res_head.returncode == 0:
            files = [l.strip() for l in res_head.stdout.splitlines() if l.strip()]

    return sorted(list(dict.fromkeys(files)))


class LocalHeuristicScopeRule:
    """Verifies that modified files in the working tree / commits stay within declared Systems Involved."""

    rule_name: str = "local-heuristic-scope"

    def evaluate(self, repo_path: Path) -> RuleResult:
        task_file = repo_path / ".agent" / "TASK.md"
        declared_systems: List[str] = []
        if task_file.exists():
            try:
                content = task_file.read_text(encoding="utf-8")
                active_task, _ = parse_task_md(content)
                declared_systems = parse_systems_involved(active_task.get("systems", ""))
            except Exception:
                pass

        try:
            modified_files = get_modified_files(repo_path)
        except Exception as e:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Failed to inspect git repository for modified files: {e}",
            )

        if not modified_files:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.APPROVED,
                message="Working tree clean; no modified files out of scope.",
                details={"declared_systems": declared_systems, "modified_files": []},
            )

        out_of_scope = [f for f in modified_files if not is_file_in_scope(f, declared_systems)]

        if out_of_scope:
            return RuleResult(
                rule_name=self.rule_name,
                severity=AuditSeverity.CHANGES_REQUIRED,
                message=f"Local heuristic scope audit: {len(out_of_scope)} file(s) modified outside declared Systems Involved: {out_of_scope}.",
                details={
                    "out_of_scope": out_of_scope,
                    "declared_systems": declared_systems,
                    "modified_files": modified_files,
                },
            )

        return RuleResult(
            rule_name=self.rule_name,
            severity=AuditSeverity.APPROVED,
            message=f"Local heuristic scope audit passed: all modified files ({len(modified_files)}) conform to declared task scope.",
            details={"modified_files": modified_files, "declared_systems": declared_systems},
        )


def parse_agent_verdict(response_text: str) -> Optional[Tuple[AuditSeverity, str]]:
    """Parse canvas agent verdict and reason from freeform or formatted text."""
    if not response_text:
        return None

    m = re.search(r"VERDICT:\s*\[?(APPROVED|CHANGES\s+REQUIRED|REJECTED)\]?", response_text, re.IGNORECASE)
    if m:
        verdict_raw = m.group(1).upper()
        if "REJECT" in verdict_raw:
            severity = AuditSeverity.REJECTED
        elif "CHANGES" in verdict_raw:
            severity = AuditSeverity.CHANGES_REQUIRED
        else:
            severity = AuditSeverity.APPROVED

        reason_m = re.search(r"REASON:\s*(.*)", response_text, re.IGNORECASE | re.DOTALL)
        reason = reason_m.group(1).strip() if reason_m else response_text.strip()
        return severity, reason

    upper = response_text.upper()
    if "REJECTED" in upper:
        return AuditSeverity.REJECTED, response_text.strip()
    elif "CHANGES REQUIRED" in upper or "CHANGES_REQUIRED" in upper:
        return AuditSeverity.CHANGES_REQUIRED, response_text.strip()
    elif "APPROVED" in upper:
        return AuditSeverity.APPROVED, response_text.strip()

    return None


class HybridScopeRule:
    """Hybrid scope rule combining canvas agent semantic verification with local heuristic fallback."""

    rule_name: str = "hybrid-scope"

    def __init__(
        self,
        agent_name: Optional[str] = None,
        timeout: float = 15.0,
        fallback_rule: Optional[LocalHeuristicScopeRule] = None,
    ):
        self.agent_name = agent_name
        self.timeout = timeout
        self.fallback_rule = fallback_rule or LocalHeuristicScopeRule()

    def evaluate(self, repo_path: Path) -> RuleResult:
        task_file = repo_path / ".agent" / "TASK.md"
        active_task: Dict[str, Any] = {"id": "XX.Y", "title": "Active Task", "criteria": [], "systems": ""}
        if task_file.exists():
            try:
                content = task_file.read_text(encoding="utf-8")
                active_task, _ = parse_task_md(content)
            except Exception:
                pass

        diff_summary = ""
        try:
            res_stat = subprocess.run(
                ["git", "diff", "HEAD", "--stat"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            stat_text = res_stat.stdout.strip() if res_stat.returncode == 0 else ""

            res_diff = subprocess.run(
                ["git", "diff", "HEAD", "-U2"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            diff_text = res_diff.stdout[:8000].strip() if res_diff.returncode == 0 else ""
            diff_summary = f"{stat_text}\n\n{diff_text}".strip()
            if not diff_summary:
                diff_summary = "Working tree clean; no uncommitted diff."
        except Exception:
            diff_summary = "Unable to inspect git diff."

        task_id = active_task.get("id", "XX.Y")
        title = active_task.get("title", "")
        desc = active_task.get("description", "")
        systems = active_task.get("systems", "")
        criteria_list = active_task.get("criteria", [])
        criteria_str = "\n".join(f"- [{'x' if c.get('checked') else ' '}] {c.get('text', '')}" for c in criteria_list)

        prompt = (
            f"You are the Scope Auditor for taskctl.\n"
            f"Evaluate the following Git diff against the active task contract.\n\n"
            f"Task [{task_id}]: {title}\n"
            f"Description: {desc}\n"
            f"Systems Involved: {systems}\n"
            f"Acceptance Criteria:\n{criteria_str}\n\n"
            f"Git Changes:\n{diff_summary}\n\n"
            f"Verify if changes adhere to task scope and criteria without regressions.\n"
            f"Respond with:\n"
            f"VERDICT: [APPROVED | CHANGES REQUIRED | REJECTED]\n"
            f"REASON: <concise explanation>"
        )

        candidates = [self.agent_name] if self.agent_name else ["Auditor", "ScopeAuditor"]
        agent_used: Optional[str] = None
        agent_response: Optional[str] = None
        start_time = time.perf_counter()

        for cand in candidates:
            try:
                from taskctl.providers.maestri import ask_agent
                resp = ask_agent(cand, prompt, timeout=int(self.timeout))
                if resp:
                    agent_used = cand
                    agent_response = resp
                    break
            except Exception:
                continue

        # If canvas agent responded and parsed successfully
        if agent_used and agent_response:
            verdict = parse_agent_verdict(agent_response)
            if verdict:
                severity, reason = verdict
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                try:
                    from taskctl.telemetry import get_telemetry_emitter
                    get_telemetry_emitter().record_provider_call(
                        provider="maestri",
                        operation=f"hybrid_audit:{agent_used}",
                        duration_ms=duration_ms,
                        success=True,
                        metadata={"verdict": severity.label, "delegated": True, "fallback": False},
                    )
                    get_telemetry_emitter().emit_lifecycle_event(
                        event_type="hybrid_audit",
                        task_id=task_id,
                        message=f"Hybrid audit evaluated by canvas agent '{agent_used}': [{severity.label}] in {duration_ms:.2f}ms",
                        status=severity.label,
                        duration_ms=duration_ms,
                        level="info" if severity == AuditSeverity.APPROVED else "warn",
                        details={"agent": agent_used, "delegated": True, "fallback": False, "reason": reason},
                    )
                except Exception:
                    pass

                return RuleResult(
                    rule_name=f"canvas-agent-semantic[{agent_used}]",
                    severity=severity,
                    message=f"Canvas agent '{agent_used}' verdict: {reason}",
                    details={
                        "agent": agent_used,
                        "delegated": True,
                        "fallback": False,
                        "raw_response": agent_response,
                    },
                )

        # Fallback to local heuristic rule
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        try:
            from taskctl.telemetry import get_telemetry_emitter
            get_telemetry_emitter().record_provider_call(
                provider="maestri",
                operation="hybrid_audit:delegation",
                duration_ms=duration_ms,
                success=False,
                metadata={"degraded": True, "fallback": True, "reason": "canvas agent offline or unresponsive"},
            )
            get_telemetry_emitter().emit_lifecycle_event(
                event_type="hybrid_audit",
                task_id=task_id,
                message=f"Canvas agent offline/unresponsive; falling back to local heuristic scope audit ({duration_ms:.2f}ms)",
                status="FALLBACK",
                duration_ms=duration_ms,
                level="info",
                details={"delegated": False, "fallback": True},
            )
        except Exception:
            pass

        fallback_res = self.fallback_rule.evaluate(repo_path)
        return RuleResult(
            rule_name="hybrid-scope[fallback]",
            severity=fallback_res.severity,
            message=f"Canvas agent offline/unresponsive; fell back to local heuristic scope audit: {fallback_res.message}",
            details={
                "fallback": True,
                "fallback_rule": fallback_res.rule_name,
                **fallback_res.details,
            },
        )


class ScopeAuditor:
    """Orchestrates rule evaluation and resolves final audit verdict."""

    def __init__(
        self,
        rules: Optional[List[Any]] = None,
        hybrid: bool = False,
        delegate: bool = False,
        agent_name: Optional[str] = None,
        timeout: float = 15.0,
        domain_lint: bool = False,
    ):
        if rules is None:
            self.rules = [
                GitHygieneRule(),
                TaskContractRule(),
                SyntaxCompilationRule(),
                SecretsBoundaryRule(),
                CommitConventionRule(),
            ]
            if domain_lint:
                self.rules.append(AcceptanceCriteriaRule())
        else:
            self.rules = rules
        self.hybrid = hybrid or delegate
        self.agent_name = agent_name
        self.timeout = timeout

    def run(self, repo_path: Path) -> AuditVerdict:
        results: List[RuleResult] = []
        max_severity = AuditSeverity.APPROVED

        # 1. Local rules are evaluated first
        for rule in self.rules:
            result = rule.evaluate(repo_path)
            results.append(result)
            if result.severity > max_severity:
                max_severity = result.severity

        # 2. Hybrid canvas delegation if enabled and not hard-rejected locally
        if self.hybrid and not any(isinstance(r, HybridScopeRule) for r in self.rules):
            if max_severity < AuditSeverity.REJECTED:
                hybrid_rule = HybridScopeRule(agent_name=self.agent_name, timeout=self.timeout)
                hybrid_result = hybrid_rule.evaluate(repo_path)
                results.append(hybrid_result)
                if hybrid_result.severity > max_severity:
                    max_severity = hybrid_result.severity

        return AuditVerdict(
            status=max_severity.label,
            exit_code=int(max_severity),
            results=results,
        )


def remediate_mechanical(repo_path: Path, results: List[RuleResult]) -> List[str]:
    """Attempt safe deterministic mechanical fixes for known failures."""
    auto_fixed: List[str] = []
    for r in results:
        if r.severity == AuditSeverity.APPROVED:
            continue
        if r.rule_name == "git-hygiene":
            try:
                # 1. Attempt whitespace fix on unstaged git diff
                diff_res = subprocess.run(
                    ["git", "diff"],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if diff_res.stdout.strip():
                    fix_res = subprocess.run(
                        ["git", "apply", "--whitespace=fix"],
                        input=diff_res.stdout,
                        cwd=str(repo_path),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if fix_res.returncode == 0:
                        chk = subprocess.run(
                            ["git", "diff", "--check"],
                            cwd=str(repo_path),
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if chk.returncode == 0:
                            auto_fixed.append("Resolved trailing whitespace errors via 'git apply --whitespace=fix'")
            except Exception:
                pass
    return auto_fixed


def generate_remediation_package(
    verdict: AuditVerdict,
    repo_path: Path,
    auto_fixed: Optional[List[str]] = None,
) -> RemediationPackage:
    """Synthesize a structured remediation package from audit results and reflex knowledge cards."""
    task_file = repo_path / ".agent" / "TASK.md"
    task_id = "XX.Y"
    task_title = "Active Task"
    if task_file.exists():
        try:
            active_task, _ = parse_task_md(task_file.read_text(encoding="utf-8"))
            if active_task:
                task_id = active_task.get("id", "XX.Y")
                task_title = active_task.get("title", "Active Task")
        except Exception:
            pass

    actions: List[RemediationAction] = []
    error_texts: List[str] = []

    for r in verdict.results:
        if r.severity == AuditSeverity.APPROVED:
            continue
        error_texts.append(f"{r.rule_name}: {r.message}")
        cmd: Optional[str] = None
        sug = r.message
        affected: List[str] = []

        if r.rule_name == "git-hygiene":
            cmd = "git diff --check"
            sug = "Clean trailing whitespaces and conflict markers from working tree."
            errs = r.details.get("errors", [])
            for e in errs:
                if ":" in e:
                    affected.append(e.split(":")[0].strip())
        elif r.rule_name == "task-contract":
            sug = "Ensure .agent/TASK.md has a valid Task ID [XX.Y], title, and Status in [READY FOR PLANNING, PLANNING, RUNNING]."
            affected = [".agent/TASK.md"]
        elif r.rule_name == "syntax-compilation":
            cmd = "python3 -m py_compile <scripts>"
            sug = "Resolve Python syntax errors reported by py_compile in affected files."
            affected = r.details.get("failed_files", [])
        elif r.rule_name == "secrets-boundary":
            sug = "Remove detected secret files, API tokens, or private keys from git working tree."
            affected = r.details.get("detected_secrets", [])
        elif r.rule_name == "commit-convention":
            cmd = "taskctl lint-commit <msg>"
            sug = "Format the latest commit message according to Conventional Commits: 'type(scope): description'."
        elif r.rule_name == "scope-boundary":
            cmd = "git checkout -- <file>"
            sug = "Revert unapproved modifications outside declared Systems Involved or update TASK.md Systems Involved."
            affected = r.details.get("out_of_scope", [])
        elif r.rule_name == "acceptance-criteria":
            sug = "Complete all remaining unchecked acceptance criteria in .agent/TASK.md."
            affected = [".agent/TASK.md"]

        actions.append(
            RemediationAction(
                rule_name=r.rule_name,
                severity=r.severity,
                diagnosis=r.message,
                suggested_fix=sug,
                remediation_command=cmd,
                affected_files=affected,
            )
        )

    # Query Knowledge Cards via reflex or recall
    knowledge_remedies: List[Dict[str, Any]] = []
    try:
        from taskctl.core.knowledge import KnowledgeEngine
        k_engine = KnowledgeEngine(repo_path=str(repo_path))
        query_text = " ".join(error_texts)
        reflex_matches = k_engine.reflex(query_text, limit=3)
        for card, score, matched in reflex_matches:
            knowledge_remedies.append({
                "id": card.id,
                "title": card.title,
                "type": card.type,
                "problem": card.problem,
                "solution": card.solution,
                "score": score,
                "matched_keywords": matched,
            })
        if not knowledge_remedies and error_texts:
            for text in error_texts[:2]:
                recall_matches = k_engine.recall(text, limit=2)
                for card, score in recall_matches:
                    if not any(k["id"] == card.id for k in knowledge_remedies):
                        knowledge_remedies.append({
                            "id": card.id,
                            "title": card.title,
                            "type": card.type,
                            "problem": card.problem,
                            "solution": card.solution,
                            "score": score,
                        })
    except Exception:
        pass

    return RemediationPackage(
        task_id=task_id,
        task_title=task_title,
        status=verdict.status,
        exit_code=verdict.exit_code,
        actions=actions,
        knowledge_remedies=knowledge_remedies,
        auto_fixed_items=auto_fixed or [],
    )
