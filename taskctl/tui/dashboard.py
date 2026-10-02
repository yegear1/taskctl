"""Interactive terminal dashboard event loop and controller for taskctl."""

from __future__ import annotations

import os
import sys
import time
import select
import signal
from typing import Optional

from taskctl.tui.state import DashboardState, collect_dashboard_state
from taskctl.tui.renderer import render_dashboard


class Dashboard:
    """Interactive task contract and DoD checklist dashboard."""

    def __init__(
        self,
        repo_root: Optional[str] = None,
        interval: float = 2.0,
        run_tests: bool = False,
        use_color: Optional[bool] = None,
        split_pane: bool = False,
    ):
        self.repo_root = repo_root
        self.interval = max(0.5, interval)
        self.run_tests = run_tests
        self.use_color = use_color
        self.split_pane = split_pane
        self.scroll_offset = 0
        self._running = False

    def render_snapshot(self, split_pane: Optional[bool] = None) -> str:
        """Collect state and return rendered dashboard string for one-shot display."""
        state = collect_dashboard_state(
            repo_root=self.repo_root,
            run_tests=self.run_tests,
            run_audit=True,
        )
        split = self.split_pane if split_pane is None else split_pane
        return render_dashboard(
            state,
            use_color=self.use_color,
            split_pane=split,
            diff_scroll_offset=self.scroll_offset,
        )

    def handle_input(self, seq: str) -> Optional[str]:
        """Process keyboard or mouse input sequence.

        Returns:
            "quit" to terminate loop,
            "refresh" to force redraw,
            "run_tests" to execute tests and redraw,
            None if unhandled.
        """
        if not seq:
            return None

        # Standalone quit keys
        if seq in ("q", "Q", "\x03", "\x04"):  # q, Q, Ctrl+C, Ctrl+D
            return "quit"
        if seq == "\x1b":  # Standalone Escape
            return "quit"

        # SGR Mouse events: \x1b[<button;x;yM or \x1b[<button;x;ym
        if seq.startswith("\x1b[<") and (seq.endswith("M") or seq.endswith("m")):
            payload = seq[3:-1]
            parts = payload.split(";")
            if parts and parts[0].isdigit():
                btn = int(parts[0])
                if btn == 64:  # Wheel Up
                    self.scroll_offset = max(0, self.scroll_offset - 3)
                    return "refresh"
                elif btn == 65:  # Wheel Down
                    self.scroll_offset += 3
                    return "refresh"
            return None

        # Legacy xterm mouse event: \x1b[M followed by 3 bytes
        if seq.startswith("\x1b[M") and len(seq) >= 6:
            btn = ord(seq[3])
            if btn == 96:  # 64 + 32 = Wheel Up
                self.scroll_offset = max(0, self.scroll_offset - 3)
                return "refresh"
            elif btn == 97:  # 65 + 32 = Wheel Down
                self.scroll_offset += 3
                return "refresh"
            return None

        # Arrow keys and Page keys
        if seq in ("\x1b[A", "\x1bOA"):  # Arrow Up
            self.scroll_offset = max(0, self.scroll_offset - 1)
            return "refresh"
        if seq in ("\x1b[B", "\x1bOB"):  # Arrow Down
            self.scroll_offset += 1
            return "refresh"
        if seq == "\x1b[5~":  # Page Up
            self.scroll_offset = max(0, self.scroll_offset - 10)
            return "refresh"
        if seq == "\x1b[6~":  # Page Down
            self.scroll_offset += 10
            return "refresh"
        if seq in ("\x1b[H", "\x1b[1~"):  # Home
            self.scroll_offset = 0
            return "refresh"
        if seq in ("\x1b[F", "\x1b[4~"):  # End
            self.scroll_offset = 999999
            return "refresh"

        # Single key shortcuts
        if seq in ("k", "K"):
            self.scroll_offset = max(0, self.scroll_offset - 1)
            return "refresh"
        if seq in ("j", "J"):
            self.scroll_offset += 1
            return "refresh"
        if seq in ("d", "D", "\t"):  # Toggle split view
            self.split_pane = not self.split_pane
            return "refresh"
        if seq in ("r", "R", "a", "A"):
            return "refresh"
        if seq in ("t", "T"):
            return "run_tests"
        if seq == "g":
            self.scroll_offset = 0
            return "refresh"
        if seq == "G":
            self.scroll_offset = 999999
            return "refresh"

        return None

    def run(self) -> int:
        """Run the interactive terminal loop. Returns exit code."""
        # Non-TTY or forced batch execution: print once and exit cleanly
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            sys.stdout.write(self.render_snapshot() + "\n")
            sys.stdout.flush()
            return 0

        # POSIX terminal setup
        has_termios = False
        old_settings = None
        try:
            import termios
            import tty
            old_settings = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            has_termios = True
        except Exception:
            # Fallback if termios is unsupported or fails
            has_termios = False

        self._running = True

        def cleanup_terminal():
            # Reset colors, show cursor, disable mouse reporting, switch back from alternate screen
            sys.stdout.write("\033[?1006l\033[?1000l\033[?1049l\033[?25h\033[0m")
            sys.stdout.flush()
            if has_termios and old_settings:
                try:
                    import termios
                    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
                except Exception:
                    pass

        def sig_handler(sig, frame):
            self._running = False
            cleanup_terminal()
            sys.exit(0)

        # Register signals for graceful restoration
        try:
            signal.signal(signal.SIGINT, sig_handler)
            signal.signal(signal.SIGTERM, sig_handler)
        except (ValueError, AttributeError):
            pass

        try:
            # Enter alternate screen buffer, hide cursor, enable mouse reporting (SGR mode 1000 & 1006)
            sys.stdout.write("\033[?1049h\033[?1000h\033[?1006h\033[?25l\033[H")
            sys.stdout.flush()

            last_refresh = 0.0
            force_refresh = True
            run_tests_now = self.run_tests

            while self._running:
                now = time.time()
                if force_refresh or (now - last_refresh >= self.interval):
                    state = collect_dashboard_state(
                        repo_root=self.repo_root,
                        run_tests=run_tests_now,
                        run_audit=True,
                    )
                    rendered = render_dashboard(
                        state,
                        use_color=self.use_color,
                        split_pane=self.split_pane,
                        diff_scroll_offset=self.scroll_offset,
                    )
                    # Move cursor home and draw
                    sys.stdout.write("\033[H\033[J" + rendered + "\n")
                    sys.stdout.flush()
                    last_refresh = now
                    force_refresh = False
                    run_tests_now = False

                # Non-blocking poll for user keystroke (100ms slice)
                rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                if rlist:
                    ch = sys.stdin.read(1)
                    if ch == "\x1b":
                        seq = "\x1b"
                        while True:
                            r_sub, _, _ = select.select([sys.stdin], [], [], 0.02)
                            if not r_sub:
                                break
                            c = sys.stdin.read(1)
                            seq += c
                            if len(seq) > 2 and (c.isalpha() or c == "~"):
                                break
                            if seq.startswith("\x1b[M") and len(seq) == 6:
                                break
                    else:
                        seq = ch

                    action = self.handle_input(seq)
                    if action == "quit":
                        break
                    elif action == "refresh":
                        force_refresh = True
                    elif action == "run_tests":
                        run_tests_now = True
                        force_refresh = True

        except KeyboardInterrupt:
            pass
        finally:
            cleanup_terminal()

        return 0
