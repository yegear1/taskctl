"""Terminal formatting and ANSI rendering engine for taskctl TUI."""

from __future__ import annotations

import os
import sys
import shutil
from typing import Any, Dict, List, Optional

from taskctl.tui.state import DashboardState, DoDCheckItem


class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BG_DARK = "\033[48;5;236m"
    BG_BLUE = "\033[44m"
    BG_CYAN = "\033[46m"
    BG_GREEN = "\033[42m"
    BG_RED = "\033[41m"
    BG_YELLOW = "\033[43m"


def _should_use_color(forced: Optional[bool] = None) -> bool:
    if forced is not None:
        return forced
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty()


def _visible_len(s: str) -> int:
    """Return visible character length of string with ANSI escape codes stripped."""
    import re
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return len(ansi_escape.sub("", s))


def _truncate_pad(s: str, width: int) -> str:
    """Truncate or pad string to exact visible width."""
    vlen = _visible_len(s)
    if vlen > width:
        # Strip excess visible characters while keeping it simple
        import re
        ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        plain = ansi_escape.sub("", s)
        return plain[: width - 3] + "..." if width >= 3 else plain[:width]
    return s + " " * (width - vlen)


def _status_badge(status: str, use_color: bool = True) -> str:
    s = status.upper().strip()
    if not use_color:
        return f"[{s}]"

    if s in ["RUNNING"]:
        return f"{Ansi.BG_CYAN}{Ansi.BLACK}{Ansi.BOLD} {s} {Ansi.RESET}"
    if s in ["APPROVED", "DONE", "PASS"]:
        return f"{Ansi.BG_GREEN}{Ansi.BLACK}{Ansi.BOLD} {s} {Ansi.RESET}"
    if s in ["PLANNING", "READY", "READY FOR PLANNING"]:
        return f"{Ansi.BG_YELLOW}{Ansi.BLACK}{Ansi.BOLD} {s} {Ansi.RESET}"
    if s in ["REJECTED", "FAIL", "FAILED"]:
        return f"{Ansi.BG_RED}{Ansi.WHITE}{Ansi.BOLD} {s} {Ansi.RESET}"
    if s in ["CHANGES REQUIRED", "WARN"]:
        return f"{Ansi.BG_YELLOW}{Ansi.BLACK}{Ansi.BOLD} {s} {Ansi.RESET}"
    return f"{Ansi.BOLD}[{s}]{Ansi.RESET}"


def _dod_badge(status: str, use_color: bool = True) -> str:
    s = status.upper().strip()
    if not use_color:
        if s == "PASS":
            return "[PASS]"
        if s == "FAIL":
            return "[FAIL]"
        if s == "WARN":
            return "[WARN]"
        if s == "RUNNING":
            return "[RUN ]"
        return "[PEND]"
    if s == "PASS":
        return f"{Ansi.GREEN}{Ansi.BOLD}✅ [PASS]{Ansi.RESET}"
    if s == "FAIL":
        return f"{Ansi.RED}{Ansi.BOLD}❌ [FAIL]{Ansi.RESET}"
    if s == "WARN":
        return f"{Ansi.YELLOW}{Ansi.BOLD}⚠️  [WARN]{Ansi.RESET}"
    if s == "RUNNING":
        return f"{Ansi.CYAN}{Ansi.BOLD}⚡ [RUN ]{Ansi.RESET}"
    return f"{Ansi.DIM}⏳ [PEND]{Ansi.RESET}"


def render_dashboard(
    state: DashboardState,
    width: Optional[int] = None,
    use_color: Optional[bool] = None,
) -> str:
    """Render the dashboard state into a formatted terminal string."""
    color = _should_use_color(use_color)

    if width is None:
        term_cols = shutil.get_terminal_size((80, 24)).columns
        width = max(70, min(100, term_cols))
    else:
        width = max(60, width)

    inner_width = width - 4  # accounted for "│ " and " │"

    lines: List[str] = []

    def border_top() -> str:
        return f"┌{'─' * (width - 2)}┐"

    def border_mid() -> str:
        return f"├{'─' * (width - 2)}┤"

    def border_bottom() -> str:
        return f"└{'─' * (width - 2)}┘"

    def box_line(content: str = "") -> str:
        return f"│ {_truncate_pad(content, inner_width)} │"

    # --- TOP BORDER & TITLE ---
    lines.append(border_top())
    title_text = "⚡ TASKCTL COCKPIT • TASK LIFECYCLE & CONTRACT ENGINE"
    if color:
        title_text = f"{Ansi.BOLD}{Ansi.CYAN}{title_text}{Ansi.RESET}"
    lines.append(box_line(title_text))

    repo_name = os.path.basename(state.repo_root) or "repository"
    meta_line = f"Repo: {repo_name} │ Branch: {state.branch} [{state.head_commit}] │ Python: 3.14"
    if color:
        meta_line = f"{Ansi.DIM}{meta_line}{Ansi.RESET}"
    lines.append(box_line(meta_line))

    # --- ACTIVE TASK CONTRACT PANEL ---
    lines.append(border_mid())
    header_task = "📌 ACTIVE TASK CONTRACT"
    if color:
        header_task = f"{Ansi.BOLD}{Ansi.YELLOW}{header_task}{Ansi.RESET}"
    lines.append(box_line(header_task))

    task = state.active_task
    if task:
        task_id = task.get("id", "XX.Y")
        task_title = task.get("title", "Ad-hoc task")
        status_raw = task.get("status", "UNKNOWN")

        badge = _status_badge(status_raw, use_color=color)
        t_id_str = f"[{task_id}] {task_title}"
        if color:
            t_id_str = f"{Ansi.BOLD}{t_id_str}{Ansi.RESET}"
        lines.append(box_line(f"Task   : {t_id_str}"))
        lines.append(box_line(f"Status : {badge}"))

        if task.get("target"):
            lines.append(box_line(f"Target : {task['target']}"))
        if task.get("systems"):
            lines.append(box_line(f"Systems: {task['systems']}"))

        # Acceptance Criteria
        criteria = state.acceptance_criteria
        if criteria:
            completed = sum(1 for c in criteria if c.get("checked"))
            total = len(criteria)
            crit_head = f"Acceptance Criteria ({completed}/{total} completed):"
            if color:
                crit_head = f"{Ansi.BOLD}{crit_head}{Ansi.RESET}"
            lines.append(box_line(crit_head))

            for c in criteria:
                is_done = c.get("checked", False)
                text = c.get("text", "")
                if is_done:
                    marker = f"{Ansi.GREEN}  [x]{Ansi.RESET}" if color else "  [x]"
                    c_text = f"{Ansi.DIM}{text}{Ansi.RESET}" if color else text
                else:
                    marker = f"{Ansi.YELLOW}  [ ]{Ansi.RESET}" if color else "  [ ]"
                    c_text = text
                lines.append(box_line(f"{marker} {c_text}"))
        else:
            lines.append(box_line(f"Criteria: {Ansi.DIM if color else ''}(No explicit acceptance criteria found){Ansi.RESET if color else ''}"))
    else:
        lines.append(box_line("No active task loaded."))

    # --- DEFINITION OF DONE & AUDIT PANEL ---
    lines.append(border_mid())
    header_dod = "📋 DEFINITION OF DONE (DoD) & SCOPE AUDIT"
    if color:
        header_dod = f"{Ansi.BOLD}{Ansi.GREEN}{header_dod}{Ansi.RESET}"
    lines.append(box_line(header_dod))

    for item in state.dod_items:
        badge = _dod_badge(item.status, use_color=color)
        name_str = f"{item.name:<21}"
        if color:
            name_str = f"{Ansi.BOLD}{name_str}{Ansi.RESET}"
        msg_str = item.message
        if item.details:
            msg_str += f" ({item.details})"
        lines.append(box_line(f" {badge} {name_str} : {msg_str}"))

    # --- GIT WORKSPACE STATUS PREVIEW ---
    lines.append(border_mid())
    header_ws = f"📂 WORKSPACE HYGIENE ({'Clean' if state.git_clean else f'{state.staged_count} staged, {state.unstaged_count} modified, {state.untracked_count} untracked'})"
    if color:
        ws_color = Ansi.GREEN if state.git_clean else Ansi.YELLOW
        header_ws = f"{Ansi.BOLD}{ws_color}{header_ws}{Ansi.RESET}"
    lines.append(box_line(header_ws))

    if state.git_clean:
        clean_msg = "  Working tree clean. Zero uncommitted changes or merge conflicts."
        lines.append(box_line(f"{Ansi.DIM if color else ''}{clean_msg}{Ansi.RESET if color else ''}"))
    else:
        for p in state.git_status_preview:
            code = p[:2]
            fname = p[3:]
            if color:
                code_color = Ansi.GREEN if "A" in code or "M" in code[:1] else (Ansi.YELLOW if "M" in code[1:] else Ansi.RED)
                line_str = f"  {code_color}{code}{Ansi.RESET} {fname}"
            else:
                line_str = f"  {code} {fname}"
            lines.append(box_line(line_str))
        remaining = (state.staged_count + state.unstaged_count + state.untracked_count) - len(state.git_status_preview)
        if remaining > 0:
            lines.append(box_line(f"  {Ansi.DIM if color else ''}... and {remaining} more modified files{Ansi.RESET if color else ''}"))

    # --- CONTROLS / FOOTER ---
    lines.append(border_mid())
    ctrls = "[r] Refresh   [t] Run Tests   [a] Scope Audit   [q] Quit"
    if color:
        ctrls = f"{Ansi.BOLD}{Ansi.CYAN}{ctrls}{Ansi.RESET}"
    lines.append(box_line(ctrls))
    lines.append(border_bottom())

    return "\n".join(lines)
