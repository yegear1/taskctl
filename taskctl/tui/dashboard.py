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
    ):
        self.repo_root = repo_root
        self.interval = max(0.5, interval)
        self.run_tests = run_tests
        self.use_color = use_color
        self._running = False

    def render_snapshot(self) -> str:
        """Collect state and return rendered dashboard string for one-shot display."""
        state = collect_dashboard_state(
            repo_root=self.repo_root,
            run_tests=self.run_tests,
            run_audit=True,
        )
        return render_dashboard(state, use_color=self.use_color)

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
            # Reset colors, show cursor, switch back from alternate screen
            sys.stdout.write("\033[?1049l\033[?25h\033[0m")
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
            # Enter alternate screen buffer and hide cursor
            sys.stdout.write("\033[?1049h\033[?25l\033[H")
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
                    rendered = render_dashboard(state, use_color=self.use_color)
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
                    if ch in ("q", "Q", "\x03", "\x1b", "\x04"):  # q, Q, Ctrl+C, Esc, Ctrl+D
                        break
                    elif ch in ("r", "R"):
                        force_refresh = True
                    elif ch in ("t", "T"):
                        run_tests_now = True
                        force_refresh = True
                    elif ch in ("a", "A"):
                        force_refresh = True

        except KeyboardInterrupt:
            pass
        finally:
            cleanup_terminal()

        return 0
