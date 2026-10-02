from __future__ import annotations

import os
import signal
import unittest

from tests.support import Sandbox, interrupt_review, success


class TerminationTest(unittest.TestCase):
    def test_a_terminated_run_kills_the_reviewer_and_cleans_up(self) -> None:
        sb = Sandbox()
        self.addCleanup(sb.cleanup)
        sb.repo.mkdir()
        sb.fake.reply(success(), sleep=30)

        call, returncode = interrupt_review(sb, ["selftest"], signal.SIGTERM)

        self.assertEqual(returncode, 128 + signal.SIGTERM)
        self.assertFalse(os.path.exists(call["cwd"]))


if __name__ == "__main__":
    unittest.main()
