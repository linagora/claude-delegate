from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest

from tests.support import BIN, Sandbox, success


class TerminationTest(unittest.TestCase):
    def test_a_terminated_run_kills_the_reviewer_and_cleans_up(self) -> None:
        sb = Sandbox()
        self.addCleanup(sb.cleanup)
        sb.repo.mkdir()
        sb.fake.reply(success(), sleep=30)
        process = subprocess.Popen(
            [sys.executable, str(BIN), "selftest"],
            cwd=sb.repo,
            env=sb.env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(process.kill)
        deadline = time.monotonic() + 15
        while not sb.fake.calls() and time.monotonic() < deadline:
            time.sleep(0.05)
        trap = sb.fake.last_call()["cwd"]

        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=15)

        self.assertEqual(process.returncode, 128 + signal.SIGTERM)
        self.assertFalse(os.path.exists(trap))


if __name__ == "__main__":
    unittest.main()
