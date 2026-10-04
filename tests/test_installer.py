"""The installer, run as a process with fake claude, curl and security first on
the PATH.

The interactive path is exercised through a real pseudo-terminal, so the
questions the installer asks are answered the way a person answers them. The
piped path — the one the README documents first — is exercised with a real
`cat install.sh | bash`, where /dev/tty is the way back to the terminal.
"""

from __future__ import annotations

import json
import os
import pty
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tests.support import ROOT

INSTALLER = ROOT / "install.sh"
LAUNCHER = ROOT / "bin" / "claude-worker"
PLUGIN_COMMAND = "delegate@claude-delegate"

#: Records what Claude Code was asked to do, and whether it is installed.
_FAKE_CLAUDE = """#!{python}
import json, os, sys
from pathlib import Path
here = Path({directory!r})
argv = sys.argv[1:]
with open(here / "calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(argv) + "\\n")
if argv[:1] == ["--version"]:
    if (here / "installed").exists():
        print("9.9.9 (Claude Code)")
        sys.exit(0)
    sys.exit(1)
if argv[:2] == ["plugin", "list"]:
    listing = here / "plugin-list.txt"
    if listing.exists():
        sys.stdout.write(listing.read_text(encoding="utf-8"))
    sys.exit(0)
if argv[:2] == ["plugin", "install"] and (here / "install-fails").exists():
    sys.stderr.write("install failed\\n")
    sys.exit(1)
# Anything else is a session being opened by the launcher: print what it would
# start with, so the round trip can be checked.
names = [n for n in os.environ if n.startswith(("ANTHROPIC_", "CLAUDE_CODE_"))]
print(json.dumps({{"argv": argv, "env": {{n: os.environ[n] for n in names}}}}))
sys.exit(0)
"""

#: The script Claude Code's own installer would pipe into `bash`: it puts a
#: `claude` where the installer then looks for it.
_INSTALL_SCRIPT = '''#!/bin/sh
mkdir -p "$HOME/.local/bin"
cp CLAUDE_PATH "$HOME/.local/bin/claude"
exit 0
'''

#: Answers `POST /v1/messages` with a canned status, without a network. A call
#: that fetches Claude Code's installer or the launcher instead is recorded
#: apart, so the two are never confused.
_FAKE_CURL = """#!{python}
import json, sys
from pathlib import Path
here = Path({directory!r})
argv = sys.argv[1:]
url = next((a for a in argv if a.startswith("http")), argv[-1] if argv else "")
out = argv[argv.index("-o") + 1] if "-o" in argv else None
if "claude.ai/install.sh" in url:
    with open(here / "install-calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(argv) + "\\n")
    sys.stdout.write((here / "install-script.sh").read_text(encoding="utf-8"))
    sys.exit(0)
if url.endswith("bin/claude-worker"):
    with open(here / "launcher-calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(argv) + "\\n")
    if (here / "launcher-fetch-fails").exists():
        sys.exit(1)
    body = (here / "launcher.sh").read_text(encoding="utf-8")
    if out:
        Path(out).write_text(body, encoding="utf-8")
    else:
        sys.stdout.write(body)
    sys.exit(0)
with open(here / "curl.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(argv) + "\\n")
# The config lines arrive on stdin; keep whatever travels that way, so a test
# can look for the key there.
if not sys.stdin.isatty():
    text = sys.stdin.read()
    if text:
        with open(here / "curl-stdin.txt", "a", encoding="utf-8") as f:
            f.write(text)
reply = json.loads((here / "reply.json").read_text(encoding="utf-8"))
# The body curl would have written with -o, so a 400's message can be shown.
if out:
    Path(out).write_text(reply.get("body", ""), encoding="utf-8")
sys.stdout.write(reply["status"])
sys.exit(0)
"""

#: `security add-generic-password …` writes the store; `security
#: find-generic-password -s <service> -w` reads it back, the way the launcher
#: asks for the key after the installer stored it.
_FAKE_KEYCHAIN = """#!{python}
import json, sys
from pathlib import Path
store = Path({store!r})
argv = sys.argv[1:]
data = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {{}}
if argv[:1] == ["add-generic-password"]:
    data[argv[argv.index("-s") + 1]] = argv[argv.index("-w") + 1]
    store.write_text(json.dumps(data), encoding="utf-8")
    sys.exit(0)
if argv[:1] == ["delete-generic-password"]:
    if data.pop(argv[argv.index("-s") + 1], None) is None:
        sys.exit(44)
    store.write_text(json.dumps(data), encoding="utf-8")
    sys.exit(0)
if argv[:1] == ["find-generic-password"]:
    key = data.get(argv[argv.index("-s") + 1])
    if key is None:
        sys.exit(44)
    print(key)
    sys.exit(0)
sys.exit(1)
"""


class InstallerTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.claude_dir = self.root / "claude-bin"
        self.claude_dir.mkdir()
        self.fake = self.root / "fake"
        self.fake.mkdir()
        self.keychain_store = self.root / "keychain.json"
        self.uname_file = self.root / "uname.txt"
        claude = self.claude_dir / "claude"
        claude.write_text(_FAKE_CLAUDE.format(python=sys.executable, directory=str(self.fake)), encoding="utf-8")
        claude.chmod(0o755)
        curl = self.bin / "curl"
        curl.write_text(_FAKE_CURL.format(python=sys.executable, directory=str(self.fake)), encoding="utf-8")
        (self.fake / "install-script.sh").write_text(
            _INSTALL_SCRIPT.replace("CLAUDE_PATH", str(claude)), encoding="utf-8"
        )
        # The launcher the fake curl hands out when the script is piped in: a
        # copy of the real one, so the round trip is not faked.
        (self.fake / "launcher.sh").write_text(LAUNCHER.read_text(encoding="utf-8"), encoding="utf-8")
        curl.chmod(0o755)
        security = self.bin / "security"
        security.write_text(_FAKE_KEYCHAIN.format(python=sys.executable, store=str(self.keychain_store)), encoding="utf-8")
        security.chmod(0o755)
        uname = self.bin / "uname"
        uname.write_text(f'#!/bin/sh\ncat {self.uname_file}\n', encoding="utf-8")
        uname.chmod(0o755)
        self.system("Darwin")
        (self.fake / "installed").write_text("", encoding="utf-8")
        self.with_claude = True
        self.answer(200)

    # -- helpers ---------------------------------------------------------

    def answer(self, status: int, body: str = "") -> None:
        """The HTTP status the fake verification call reports."""
        (self.fake / "reply.json").write_text(json.dumps({"status": str(status), "body": body}), encoding="utf-8")

    def installed(self, present: bool) -> None:
        """Whether `claude` is on the PATH, as on a machine that already has it."""
        self.with_claude = present

    def system(self, name: str) -> None:
        self.uname_file.write_text(name + "\n", encoding="utf-8")

    def path(self) -> str:
        parts = [str(self.bin)]
        if self.with_claude:
            parts.append(str(self.claude_dir))
        parts += ["/usr/bin", "/bin"]
        return os.pathsep.join(parts)

    def env(self, **extra: str) -> Dict[str, str]:
        environment = {
            "PATH": self.path(),
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "CLAUDE_WORKER_API_KEY": "CLE_DE_TEST",
        }
        return {**environment, **extra}

    def install(self, *args: str, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(INSTALLER), *args],
            env=env or self.env(),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )

    def pipe(
        self, answers: List[bytes], *args: str, env: Optional[Dict[str, str]] = None, timeout: int = 30
    ) -> Tuple[int, str]:
        """Run the README's own command, `cat install.sh | bash`, under a real
        terminal: the pipe feeds the script, /dev/tty takes the answers."""
        return self._on_a_terminal(["bash", "-c", "cat install.sh | bash"], answers, env, cwd=ROOT, timeout=timeout)

    def install_on_a_terminal(
        self, answers: List[bytes], *args: str, env: Optional[Dict[str, str]] = None, timeout: int = 30
    ) -> Tuple[int, str]:
        """Run the installer under a real pty, typing `answers` as it asks."""
        return self._on_a_terminal(["bash", str(INSTALLER), *args], answers, env, timeout=timeout)

    def watch_a_terminal(self, *args: str, env: Optional[Dict[str, str]] = None, timeout: int = 30) -> Tuple[int, str]:
        """Run with a terminal on the output but nothing on the input: a person
        watching a piped command still sees the banner, and is asked nothing."""
        master, slave = pty.openpty()
        process = subprocess.Popen(
            ["bash", str(INSTALLER), *args],
            env=env or self.env(),
            stdin=subprocess.DEVNULL,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        deadline = time.monotonic() + timeout
        output = b""
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk
                if process.poll() is not None:
                    break
            process.wait(timeout=timeout)
        finally:
            os.close(master)
        return process.returncode, output.decode("utf-8", "replace")

    def _on_a_terminal(
        self,
        argv: List[str],
        answers: List[bytes],
        env: Optional[Dict[str, str]],
        cwd: Optional[Path] = None,
        timeout: int = 30,
    ) -> Tuple[int, str]:
        """Run under a pty that is the child's controlling terminal, so
        /dev/tty reaches the same terminal the answers are typed into."""
        environment = env or self.env()
        pid, master = pty.fork()
        if pid == 0:  # the child
            try:
                if cwd is not None:
                    os.chdir(cwd)
                os.environ.clear()
                os.environ.update(environment)
                os.execvpe(argv[0], argv, os.environ)
            except BaseException:
                os._exit(127)
        return self._drive(pid, master, answers, timeout)

    def _drive(self, pid: int, master: int, answers: List[bytes], timeout: int) -> Tuple[int, str]:
        """Read the terminal while feeding the answers, until the process ends.

        The deadline is global — the installer runs several fake binaries, and a
        quiet second is not the end of it. Output stops only when the process
        does.
        """
        deadline = time.monotonic() + timeout
        pending = list(answers)
        output = b""
        status: Optional[int] = None
        timed_out = False
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk
                    if pending:
                        answer = pending.pop(0)
                        os.write(master, answer.encode() if isinstance(answer, str) else answer)
                done, raw = os.waitpid(pid, os.WNOHANG)
                if done:
                    status = raw
                    break
            if status is None:
                # The terminal may have gone quiet because the process just
                # exited: give it a moment to be reaped before calling it hung.
                grace = time.monotonic() + 3
                while time.monotonic() < grace:
                    done, raw = os.waitpid(pid, os.WNOHANG)
                    if done:
                        status = raw
                        break
                    time.sleep(0.05)
            if status is None:
                timed_out = True
                os.kill(pid, signal.SIGKILL)
                _, status = os.waitpid(pid, 0)
        finally:
            # Anything written as the process exited is still in the terminal.
            while True:
                ready, _, _ = select.select([master], [], [], 0.2)
                if not ready:
                    break
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
            os.close(master)
        if timed_out:
            raise AssertionError(f"the installer did not finish in {timeout}s: {output!r}")
        return os.waitstatus_to_exitcode(status), output.decode("utf-8", "replace")

    def plugin_installed(self, present: bool) -> None:
        """What `claude plugin list` reports, as on a machine already set up."""
        listing = self.fake / "plugin-list.txt"
        if present:
            listing.write_text("  delegate@claude-delegate\n    Version: 0.1.0\n", encoding="utf-8")
        elif listing.exists():
            listing.unlink()

    def install_fails(self) -> None:
        (self.fake / "install-fails").write_text("", encoding="utf-8")

    def config(self) -> Path:
        return self.home / ".config" / "claude-worker" / "config"

    def forget(self) -> None:
        """Drop any configuration written so far, so the next run starts fresh."""
        path = self.config()
        path.unlink() if path.exists() else None

    def written_config(self) -> str:
        return self.config().read_text(encoding="utf-8")

    def claude_calls(self) -> List[List[str]]:
        log = self.fake / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def verify_calls(self) -> List[List[str]]:
        log = self.fake / "curl.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def install_calls(self) -> List[List[str]]:
        """The calls that fetched Claude Code's own installer."""
        log = self.fake / "install-calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def launcher_calls(self) -> List[List[str]]:
        """The calls that fetched bin/claude-worker while piped into bash."""
        log = self.fake / "launcher-calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def curl_stdin(self) -> str:
        text = self.fake / "curl-stdin.txt"
        return text.read_text(encoding="utf-8") if text.exists() else ""

    def keychain(self) -> Dict[str, str]:
        if not self.keychain_store.exists():
            return {}
        return json.loads(self.keychain_store.read_text(encoding="utf-8"))

    # -- banner and language --------------------------------------------

    CAPTION = "Two sessions: a worker on a cheap model, a reviewer on Anthropic."

    def test_the_banner_names_the_tool_and_is_absent_without_a_terminal(self) -> None:
        quiet = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertNotIn(self.CAPTION, quiet.stdout)
        self.assertNotIn("|  _ \\| ____|", quiet.stdout)
        self.forget()

        # The scope question, the model, then the key.
        _, loud = self.install_on_a_terminal(
            ["\n", "\n", "CLE_DE_TEST\n"], env=self.env(CLAUDE_WORKER_PROVIDER="linagora"), timeout=25
        )
        self.assertIn(self.CAPTION, loud)
        # The letters of DELEGATE are drawn, ASCII only, never Unicode.
        art = [line for line in loud.splitlines() if line.startswith("|")]
        self.assertTrue(art, loud)
        self.assertTrue(all(line.isascii() for line in art), art)

        # The banner is gated on the output alone: a terminal there shows it,
        # even when the input comes from a pipe.
        _, watched = self.watch_a_terminal(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"), timeout=25)
        self.assertIn(self.CAPTION, watched)

    def test_the_installer_speaks_english(self) -> None:
        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertIn("claude-worker", result.stdout)
        self.assertNotRegex(result.stdout, r"\b(le|la|les|votre|est)\b")

    # -- installing Claude Code -----------------------------------------

    def test_claude_code_is_installed_only_when_it_is_missing(self) -> None:
        self.installed(False)

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.install_calls()), 1, self.install_calls())

    def test_claude_code_is_never_updated_when_it_is_present(self) -> None:
        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.install_calls(), [])
        self.assertIn("Leaving it as it is", result.stdout)

    def test_the_marketplace_and_the_plugin_are_installed(self) -> None:
        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        flat = [" ".join(call) for call in self.claude_calls()]
        self.assertTrue(any("marketplace add" in call for call in flat), flat)
        self.assertTrue(any("plugin install" in call and PLUGIN_COMMAND in call for call in flat), flat)

    def test_an_existing_plugin_is_left_alone(self) -> None:
        self.plugin_installed(True)

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertEqual(result.returncode, 0, result.stderr)
        flat = [" ".join(call) for call in self.claude_calls()]
        self.assertFalse(any("plugin install" in call for call in flat), flat)
        self.assertIn("already installed", result.stdout)

    def test_a_failed_plugin_installation_fails_the_run(self) -> None:
        self.install_fails()

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not be installed", result.stderr)

    # -- the launcher links ---------------------------------------------

    def test_the_launcher_links_are_created_next_to_claude_code(self) -> None:
        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        worker = self.home / ".local" / "bin" / "claude-worker"
        self.assertTrue(worker.is_symlink())
        self.assertEqual(worker.resolve(), LAUNCHER.resolve())

    def test_a_piped_run_links_the_launcher_it_fetched(self) -> None:
        # The README's own path: no file beside the script, so the launcher is
        # fetched and must actually get linked.
        code, output = self.pipe(
            ["\n".encode(), "CLE_DE_TEST\n".encode()], env=self.env(CLAUDE_WORKER_PROVIDER="linagora")
        )

        self.assertEqual(code, 0, output)
        worker = self.home / ".local" / "bin" / "claude-worker"
        self.assertTrue(worker.is_symlink(), output)
        self.assertEqual(worker.resolve(), (self.home / ".local" / "share" / "claude-worker" / "claude-worker").resolve())
        self.assertTrue(worker.resolve().exists())

    def test_a_link_that_cannot_be_created_fails_the_run(self) -> None:
        squatter = self.home / ".local" / "bin"
        squatter.mkdir(parents=True)
        (squatter / "claude-worker").write_text("#!/bin/sh\n", encoding="utf-8")

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Launcher linked", result.stdout)
        self.assertIn("not a link", result.stderr)
        # The squatter is left exactly as it was.
        self.assertEqual((squatter / "claude-worker").read_text(encoding="utf-8"), "#!/bin/sh\n")

    def test_a_missing_path_entry_is_printed_and_the_profile_is_left_alone(self) -> None:
        (self.home / ".bashrc").write_text("# mine\n", encoding="utf-8")

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora", PATH=f"{self.claude_dir}:/usr/bin:/bin"))

        self.assertIn("export PATH", result.stdout)
        self.assertEqual((self.home / ".bashrc").read_text(encoding="utf-8"), "# mine\n")

    def test_a_path_entry_already_there_prints_nothing_about_it(self) -> None:
        on_path = f"{self.home / '.local' / 'bin'}{os.pathsep}{self.path()}"

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora", PATH=on_path))

        self.assertNotIn("export PATH", result.stdout)

    # -- provider, key, model -------------------------------------------

    def test_the_key_is_stored_in_the_keychain_and_not_in_the_file(self) -> None:
        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.keychain().get("linagora-ai-api-key"), "CLE_DE_TEST")
        written = self.written_config()
        self.assertIn('CLAUDE_WORKER_KEY_SERVICE="linagora-ai-api-key"', written)
        self.assertNotIn("CLE_DE_TEST", written)

    def test_without_a_keychain_the_key_falls_back_to_a_private_file(self) -> None:
        (self.bin / "security").unlink()
        (self.bin / "secret-tool").unlink() if (self.bin / "secret-tool").exists() else None

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertEqual(result.returncode, 0, result.stderr)
        config = self.config()
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertIn("CLE_DE_TEST", self.written_config())
        self.assertIn("keychain", result.stdout)

    def test_the_file_says_it_must_not_be_sourced(self) -> None:
        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertIn("do not", self.written_config())
        self.assertIn("source", self.written_config())

    def test_a_key_with_a_quote_is_refused(self) -> None:
        env = self.env(CLAUDE_WORKER_PROVIDER="linagora", CLAUDE_WORKER_API_KEY='CLE"CASSEE')

        result = self.install(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.config().exists())

    def test_the_key_never_travels_on_the_command_line(self) -> None:
        # ps shows every argument to every user of the machine.
        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        for call in self.verify_calls():
            self.assertNotIn("x-api-key", " ".join(call))
            self.assertFalse(any("CLE_DE_TEST" in argument for argument in call), call)
        self.assertIn("authorization: Bearer CLE_DE_TEST", self.curl_stdin())

    def test_linagora_is_the_default_provider(self) -> None:
        self.install(env=self.env())

        self.assertIn("https://ai-api.linagora.com", self.written_config())
        self.assertIn("deepseek-v4.1-flash", self.written_config())

    def test_every_listed_provider_offers_a_default_model(self) -> None:
        # An empty default would leave a listed provider with no model to
        # validate, which the acceptance criteria forbid.
        source = (ROOT / "install.sh").read_text(encoding="utf-8").replace('PROVIDERS="', "")
        providers = {}
        for line in source.splitlines():
            parts = line.split("|")
            if len(parts) == 4 and parts[0].isalpha():
                providers[parts[0]] = parts[2]

        self.assertTrue(providers)
        for name in ("linagora", "deepseek", "zai", "moonshot", "minimax"):
            self.assertIn(name, providers)
            self.assertTrue(providers[name], f"{name} has no default model")
        # Only the free-text entry may propose no model.
        self.assertEqual(providers.get("custom"), "")

    def test_an_environment_base_url_is_used(self) -> None:
        self.install(env=self.env(CLAUDE_WORKER_BASE_URL="https://env.exemple"))

        self.assertIn('CLAUDE_WORKER_BASE_URL="https://env.exemple"', self.written_config())

    def test_a_trailing_slash_is_stripped_along_with_the_v1(self) -> None:
        self.install(env=self.env(CLAUDE_WORKER_BASE_URL="https://env.exemple/v1/"))

        self.assertIn('CLAUDE_WORKER_BASE_URL="https://env.exemple"', self.written_config())

    def test_a_single_model_key_records_the_provider_default(self) -> None:
        # Claude Code always names a model and a restricted key refuses every
        # other one, so a name is recorded even when none is asked for. It is
        # the chosen provider's, never another provider's.
        code, output = self.install_on_a_terminal(
            ["one\n", "CLE_DE_TEST\n"], env=self.env(CLAUDE_WORKER_PROVIDER="linagora"), timeout=25
        )

        self.assertEqual(code, 0, output)
        self.assertIn('CLAUDE_WORKER_MODEL="deepseek-v4.1-flash"', self.written_config())
        self.assertIn("deepseek-v4.1-flash", self.verify_calls_arg_for("model"))

    def test_a_single_model_key_on_another_provider_records_that_provider_model(self) -> None:
        code, output = self.install_on_a_terminal(
            ["one\n", "CLE_DE_TEST\n"], env=self.env(CLAUDE_WORKER_PROVIDER="deepseek"), timeout=25
        )

        self.assertEqual(code, 0, output)
        written = self.written_config()
        self.assertIn('CLAUDE_WORKER_MODEL="deepseek-v4-pro[1m]"', written)
        self.assertNotIn("deepseek-v4.1-flash", written)

    def verify_calls_arg_for(self, field: str) -> str:
        """The request body the verification call sent, as one string."""
        for call in self.verify_calls():
            for argument in call:
                if argument.startswith("{") and field in argument:
                    return argument
        return self.curl_stdin()

    def test_a_configuration_already_there_is_kept_on_a_second_run(self) -> None:
        config = self.config()
        config.parent.mkdir(parents=True)
        config.write_text(
            'CLAUDE_WORKER_PROVIDER="linagora"\n'
            'CLAUDE_WORKER_BASE_URL="https://ancien.exemple"\n'
            'CLAUDE_WORKER_API_KEY="CLE_ANCIENNE"\n',
            encoding="utf-8",
        )

        env = self.env(CLAUDE_WORKER_PROVIDER="linagora")
        env.pop("CLAUDE_WORKER_API_KEY")
        result = self.install(env=env)

        self.assertEqual(result.returncode, 0, result.stderr)
        written = config.read_text(encoding="utf-8")
        self.assertIn("https://ancien.exemple", written)
        self.assertIn("deepseek-v4.1-flash", written)

    def test_switching_provider_does_not_keep_the_old_address(self) -> None:
        # A second run on another provider must not send DeepSeek's address to
        # a LINAGORA model, nor the other way round.
        config = self.config()
        config.parent.mkdir(parents=True)
        config.write_text(
            'CLAUDE_WORKER_PROVIDER="deepseek"\n'
            'CLAUDE_WORKER_BASE_URL="https://api.deepseek.com/anthropic"\n'
            'CLAUDE_WORKER_MODEL="deepseek-v4-pro[1m]"\n'
            'CLAUDE_WORKER_API_KEY="CLE_ANCIENNE"\n',
            encoding="utf-8",
        )

        # The key is supplied, since a provider switch does not reuse the old
        # provider's: what is under test here is the address and the model.
        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertEqual(result.returncode, 0, result.stderr)
        written = config.read_text(encoding="utf-8")
        self.assertIn('CLAUDE_WORKER_PROVIDER="linagora"', written)
        self.assertIn("https://ai-api.linagora.com", written)
        self.assertNotIn("api.deepseek.com", written)

    def test_a_provider_switch_asks_for_the_new_provider_key(self) -> None:
        # The old provider's key is not sent to the new one: a switch needs a
        # key again, and without a terminal that is a clear failure.
        config = self.config()
        config.parent.mkdir(parents=True)
        config.write_text(
            'CLAUDE_WORKER_PROVIDER="deepseek"\n'
            'CLAUDE_WORKER_BASE_URL="https://api.deepseek.com/anthropic"\n'
            'CLAUDE_WORKER_MODEL="deepseek-v4-pro[1m]"\n'
            'CLAUDE_WORKER_API_KEY="CLE_DEEPSEEK"\n',
            encoding="utf-8",
        )

        env = self.env(CLAUDE_WORKER_PROVIDER="linagora")
        env.pop("CLAUDE_WORKER_API_KEY")
        result = self.install(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no API key", result.stderr)

    def test_a_provider_switch_reuses_nothing_from_the_other_provider(self) -> None:
        # On a terminal the new provider's key is asked for, and the old
        # address and model are not offered as defaults.
        config = self.config()
        config.parent.mkdir(parents=True)
        config.write_text(
            'CLAUDE_WORKER_PROVIDER="deepseek"\n'
            'CLAUDE_WORKER_BASE_URL="https://api.deepseek.com/anthropic"\n'
            'CLAUDE_WORKER_MODEL="deepseek-v4-pro[1m]"\n',
            encoding="utf-8",
        )

        env = self.env(CLAUDE_WORKER_PROVIDER="linagora")
        env.pop("CLAUDE_WORKER_API_KEY")
        code, output = self.install_on_a_terminal(["\n", "\n", "CLE_NOUVELLE\n"], env=env, timeout=25)

        self.assertEqual(code, 0, output)
        written = config.read_text(encoding="utf-8")
        self.assertIn("https://ai-api.linagora.com", written)
        self.assertIn('CLAUDE_WORKER_MODEL="deepseek-v4.1-flash"', written)
        self.assertNotIn("api.deepseek.com", written)

    def test_a_provider_recorded_is_the_default_of_a_second_run(self) -> None:
        config = self.config()
        config.parent.mkdir(parents=True)
        config.write_text(
            'CLAUDE_WORKER_PROVIDER="zai"\n'
            'CLAUDE_WORKER_BASE_URL="https://api.z.ai/api/anthropic"\n'
            'CLAUDE_WORKER_MODEL="glm-5.2"\n'
            'CLAUDE_WORKER_API_KEY="CLE_ZAI"\n',
            encoding="utf-8",
        )

        env = self.env()
        env.pop("CLAUDE_WORKER_API_KEY")
        result = self.install(env=env)

        self.assertEqual(result.returncode, 0, result.stderr)
        written = config.read_text(encoding="utf-8")
        self.assertIn('CLAUDE_WORKER_PROVIDER="zai"', written)
        self.assertIn("https://api.z.ai/api/anthropic", written)
        self.assertIn('CLAUDE_WORKER_MODEL="glm-5.2"', written)

    # -- non-interactive -------------------------------------------------

    def test_without_a_terminal_and_without_a_key_it_fails_clearly(self) -> None:
        env = self.env(CLAUDE_WORKER_PROVIDER="linagora")
        env.pop("CLAUDE_WORKER_API_KEY")

        result = self.install(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLAUDE_WORKER_API_KEY", result.stderr)

    def test_without_a_terminal_the_defaults_are_used(self) -> None:
        result = self.install(env=self.env())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("https://ai-api.linagora.com", self.written_config())

    # -- verification ----------------------------------------------------

    def test_a_refused_key_is_named_as_such(self) -> None:
        self.answer(401, '{"error":{"message":"invalid x-api-key"}}')

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("401", result.stderr + result.stdout)
        self.assertFalse(self.config().exists())

    def test_an_unknown_model_is_told_apart_from_a_refused_key(self) -> None:
        self.answer(404, '{"error":{"message":"model not found"}}')

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertNotEqual(result.returncode, 0)
        output = result.stderr + result.stdout
        self.assertIn("model", output.lower())
        self.assertNotIn("401", output)

    def test_a_refused_model_on_a_400_is_a_failure_not_a_success(self) -> None:
        # LiteLLM answers 400 with "Invalid model name"; treating that as a
        # success would write a configuration that fails on the first request.
        self.answer(400, '{"error":{"message":"Invalid model name"}}')

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid model name", result.stderr)
        self.assertFalse(self.config().exists())

    def test_a_working_configuration_says_so(self) -> None:
        self.answer(200)

        result = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("can reach", result.stdout)

    # -- the reviewer ----------------------------------------------------

    def test_a_reviewer_directory_left_open_is_tightened(self) -> None:
        # Claude Code creates it itself, under whatever umask is in force, so it
        # can arrive group- or world-readable while holding the Anthropic
        # credentials. The README tells the user to make it 700 by hand; an
        # install that finds it looser fixes it instead of leaving the two
        # paths disagreeing.
        reviewer = self.home / ".claude-anthropic"
        reviewer.mkdir()
        reviewer.chmod(0o775)

        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertEqual(stat.S_IMODE(reviewer.stat().st_mode), 0o700)

    def test_the_installer_does_not_create_the_reviewer_directory(self) -> None:
        # Nothing of the reviewer's is installed before the sign-in, so the
        # installer must not leave an empty home for credentials behind.
        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        self.assertFalse((self.home / ".claude-anthropic").exists())

    def test_the_installer_never_signs_in_to_anthropic(self) -> None:
        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))

        flat = [" ".join(call) for call in self.claude_calls()]
        self.assertFalse(any("login" in call or "setup-token" in call for call in flat), flat)

    def test_the_selftest_is_offered_only_when_the_reviewer_is_connected(self) -> None:
        disconnected = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))
        self.assertNotIn("selftest", disconnected.stdout.lower())

        reviewer = self.home / ".claude-anthropic"
        reviewer.mkdir()
        (reviewer / ".credentials.json").write_text("{}", encoding="utf-8")

        connected = self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))
        self.assertIn("selftest", connected.stdout.lower())

    # -- uninstall -------------------------------------------------------

    def test_uninstall_removes_the_configuration_and_the_links(self) -> None:
        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))
        self.assertTrue(self.config().exists())

        result = self.install("--uninstall", env=self.env())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.config().exists())
        self.assertFalse((self.home / ".local" / "bin" / "claude-worker").exists())

    def test_uninstall_removes_the_key_it_stored(self) -> None:
        # Otherwise the key outlives the installation: the entry the installer
        # put in the keychain is its own, and undoing the install removes it.
        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora"))
        self.assertIn("linagora-ai-api-key", self.keychain())

        result = self.install("--uninstall", env=self.env())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("linagora-ai-api-key", self.keychain())

    def test_uninstall_removes_only_the_key_of_the_recorded_service(self) -> None:
        others = self.root / "others.json"
        others.write_text(json.dumps({"quelqu-un-d-autre": "CLE_AUTRE"}), encoding="utf-8")
        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="deepseek"))

        self.install("--uninstall", env=self.env())

        self.assertNotIn("claude-worker-deepseek", self.keychain())
        self.assertEqual(json.loads(others.read_text(encoding="utf-8")), {"quelqu-un-d-autre": "CLE_AUTRE"})

    def test_uninstall_leaves_a_foreign_file_alone(self) -> None:
        # link_launcher refuses to touch it, so uninstall must not delete it.
        squatter = self.home / ".local" / "bin"
        squatter.mkdir(parents=True)
        (squatter / "claude-worker").write_text("#!/bin/sh\necho mine\n", encoding="utf-8")

        result = self.install("--uninstall", env=self.env())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((squatter / "claude-worker").read_text(encoding="utf-8"), "#!/bin/sh\necho mine\n")
        self.assertIn("not a link", result.stderr)

    def test_uninstall_prints_the_plugin_command_instead_of_running_it(self) -> None:
        before = len(self.claude_calls())

        result = self.install("--uninstall", env=self.env())

        self.assertIn("plugin uninstall", result.stdout)
        self.assertEqual(len(self.claude_calls()), before)

    def test_uninstall_leaves_claude_code_alone(self) -> None:
        before = len(self.install_calls())

        result = self.install("--uninstall", env=self.env())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.install_calls()), before)

    # -- the installer and the launcher together -------------------------

    def test_the_launcher_reads_what_the_installer_wrote_below_xdg(self) -> None:
        # The round trip the two scripts must get right: install.sh writes under
        # ${XDG_CONFIG_HOME}, and claude-worker must look in the same place.
        # HOME is a directory the launcher can reach nothing useful in, so only
        # the XDG lookup can explain a working session.
        xdg = self.root / "xdg"
        self.install(env=self.env(CLAUDE_WORKER_PROVIDER="linagora", XDG_CONFIG_HOME=str(xdg)))

        self.assertTrue((xdg / "claude-worker" / "config").exists(), "the installer wrote elsewhere")
        launcher_env = {
            "PATH": self.path(),
            "HOME": str(self.root / "elsewhere"),
            "XDG_CONFIG_HOME": str(xdg),
        }
        done = subprocess.run(["bash", str(LAUNCHER), "--resume", "abc"], env=launcher_env, capture_output=True, text=True)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        started = json.loads(done.stdout)
        self.assertEqual(started["env"]["ANTHROPIC_BASE_URL"], "https://ai-api.linagora.com")
        self.assertEqual(started["env"]["ANTHROPIC_AUTH_TOKEN"], "CLE_DE_TEST")


if __name__ == "__main__":
    unittest.main()
