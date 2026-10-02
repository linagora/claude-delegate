from __future__ import annotations

import os
import unittest
from pathlib import Path

from tests.support import Sandbox

CMUX_SHIM = "#!/bin/sh\n# cmux claude wrapper: injects hooks and session tracking\nexit 97\n"


class BinaryResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.init_repo()
        self.sb.git("switch", "-q", "-c", "feature")
        self.sb.write("app.py", "def div(a, b):\n    return a / b if b else 0\n")
        self.sb.commit_all("feature change")

    def _executable(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
        return path

    def _cmux_shim_dir(self) -> Path:
        shim = self._executable(self.sb.root / "cmux-cli-shims" / "abc" / "claude", CMUX_SHIM)
        return shim.parent

    def test_the_native_install_is_preferred_over_a_shim_on_the_path(self) -> None:
        native = self.sb.home / ".local" / "bin" / "claude"
        native.parent.mkdir(parents=True)
        native.symlink_to(self.sb.fake.path)
        path = f"{self._cmux_shim_dir()}{os.pathsep}{os.environ['PATH']}"

        result = self.sb.run(
            "hostile-review", "main", extra_env={"PATH": path}, unset=["CLAUDE_DELEGATE_BIN"]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.sb.fake.calls()), 1)

    def test_on_the_path_a_cmux_shim_is_skipped_for_the_real_binary(self) -> None:
        real = self.sb.root / "real-bin" / "claude"
        real.parent.mkdir()
        real.symlink_to(self.sb.fake.path)
        path = os.pathsep.join([str(self._cmux_shim_dir()), str(real.parent), os.environ["PATH"]])

        result = self.sb.run(
            "hostile-review", "main", extra_env={"PATH": path}, unset=["CLAUDE_DELEGATE_BIN"]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.sb.fake.calls()), 1)

    def test_a_missing_binary_is_reported_clearly(self) -> None:
        result = self.sb.run(
            "hostile-review", "main", extra_env={"CLAUDE_DELEGATE_BIN": str(self.sb.root / "absent")}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("introuvable", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
