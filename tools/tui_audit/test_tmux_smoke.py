"""Manual smoke check for TmuxDriver. Not part of tests/tui/ — run by hand.

Usage:
    python3 tools/tui_audit/test_tmux_smoke.py

Run before each audit cycle to verify tmux is available and the driver
session lifecycle works cleanly.
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools.tui_audit.tmux_driver import TmuxDriver


class TestTmuxSmoke:
    def test_basic_capture_and_cleanup(self):
        """Spawn, capture output, verify HELLO, confirm session killed on exit."""
        with TmuxDriver("bash -c 'echo HELLO; sleep 60'") as d:
            result = d.wait_for(lambda s: "HELLO" in s, timeout=2.0)
            assert result, "capture() did not contain 'HELLO' within 2s"
            assert "HELLO" in d.capture()
        # session must be gone after __exit__
        ls = subprocess.run(["tmux", "ls"], capture_output=True, text=True)
        assert "hermes-audit-" not in ls.stdout, "stale session after __exit__"
        print("PASS: test_basic_capture_and_cleanup")


if __name__ == "__main__":
    print("Running tmux smoke check...")
    print("Pre-flight: tmux sessions before test:")
    subprocess.run(["tmux", "ls"], check=False)

    t = TestTmuxSmoke()
    t.test_basic_capture_and_cleanup()

    print("Post-flight: tmux sessions after test:")
    subprocess.run(["tmux", "ls"], check=False)
    print("All smoke checks passed.")
