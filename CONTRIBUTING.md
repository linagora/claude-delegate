# Contributing to claude-delegate

Thank you for your interest in claude-delegate. Bug reports, ideas, documentation and code are all welcome.
This guide explains how to set up the project and the conventions we follow.

Issues and pull requests can be written in English or French.

## Ways to contribute

- **Report a bug or suggest a feature** by opening an
  [issue](https://github.com/linagora/claude-delegate/issues/new/choose). Please search the existing issues
  first.
- **Report a vulnerability privately**, never in a public issue: see [SECURITY.md](SECURITY.md).
- **Improve the documentation**, in English or French.
- **Submit a pull request.** For anything larger than a small fix, open an issue first so that we can agree
  on the approach before you invest time in it.

This project follows a [Code of Conduct](CODE_OF_CONDUCT.md). By taking part, you agree to uphold it.

## Development environment

The project is a Claude Code plugin: the slash commands live in
[`plugins/delegate/commands/`](plugins/delegate/commands), the prompts in
[`plugins/delegate/prompts/`](plugins/delegate/prompts), and the CLI in
[`plugins/delegate/claude_delegate/`](plugins/delegate/claude_delegate). The launcher is
[`bin/claude-worker`](bin/claude-worker).

Requirements: Python 3.9 or later, git, and the [Claude Code](https://claude.com/claude-code) CLI (to run the
plugin and validate its manifests). The CLI uses only the Python standard library: there is nothing to
install.

```bash
git clone git@github.com:linagora/claude-delegate.git
cd claude-delegate
python3 -m unittest discover -s tests -t .   # end-to-end tests of the CLI and the launcher
```

The tests call the CLI as a process, in real temporary git repositories, with a fake `claude` and a fake
`gh` or `glab`; the launcher is tested with fake `claude`, `security`, `secret-tool` and `uname`. They make
no network call and no model call, so they run offline and cost nothing.

To try the plugin on a real review, install it (see the README's *Getting started*) and, from a session on
DeepSeek, run `/delegate:selftest` to confirm that the reviewer's isolation still holds on your machine.

## Checks

Run them before opening a pull request.

| Command | Scope |
|---|---|
| `python3 -m unittest discover -s tests -t .` | End-to-end tests of the CLI and the launcher |
| `claude plugin validate --strict .` | Marketplace manifest |
| `claude plugin validate --strict plugins/delegate` | Plugin manifest |

- **Test what you change.** A new behaviour of the CLI belongs in a test that drives the real process, in a
  temporary git repository, as the existing tests do, not in a unit test of an internal function.
- **Run `/delegate:selftest`** after any change to the reviewer's permissions, environment or flags: it is
  the only check that exercises the real Claude Code isolation.

## Conventions

### Language

- The code base uses **French** for its domain vocabulary and its user-facing strings: the slash-command
  texts seen by the worker session, and the CLI's `argparse` descriptions.
- **Docstrings, the tests and the commit messages are in English**, in the style of the existing ones.
- The **README, CONTRIBUTING, SECURITY and CODE_OF_CONDUCT files are in English**; keep them in English.

### Code

- Python 3.9 compatible, standard library only: the CLI must run on a bare interpreter. No new runtime
  dependency without discussing it in an issue first.
- The CLI talks to `git`, `gh` and `glab` as subprocesses and must stay non-interactive.
- The reviewer's isolation is the point of the project: any change to a flag, a permission, the environment
  allowlist or the forbidden-file list is a security-relevant change. Explain it in the pull request and add
  or adjust the matching test.
- Errors are typed: each failure maps to a documented exit code (see the README's *Exit codes*). Do not
  introduce a new code without documenting it and covering it with a test.

### Commits

We follow [Conventional Commits](https://www.conventionalcommits.org), written in English, with a subject in
the imperative mood starting with a capital letter:

```text
feat(delegate): Recheck a pull request at its new head
fix(delegate): Keep what a rebase brings out of a recheck's gap
docs: Rewrite the README in English
```

- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`. The plugin's code and tests use the
  `delegate` scope; documentation-only changes carry no scope.
- One subject per commit: a subject that needs “and” calls for two commits.
- The body, wrapped at 72 characters, explains why when the diff does not say it.

### Pull requests

- Branch from `main`: `feat/…`, `fix/…` or `chore/…`.
- One concern per pull request, with a short lowercase title (under 70 characters).
- The description is a short summary, in bullets, of what the pull request changes; link the issue it
  resolves (`Closes #123`).
