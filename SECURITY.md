# Security policy

claude-delegate spawns an Anthropic-backed Claude Code session on behalf of a session that runs on another
model, and it handles review reports that may quote source code and an API key of the LINAGORA AI Gateway.
We take every report seriously and are grateful to anyone who helps keep it safe.

## Supported versions

The plugin is developed on the `main` branch. Security fixes are made on `main` only.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public issues, pull requests or comments.**

Report them privately with GitHub's private vulnerability reporting: open the repository's **Security** tab
and choose **Report a vulnerability**, or go directly to
[the reporting form](https://github.com/linagora/claude-delegate/security/advisories/new).

Please include as much of the following as you can:

- the component concerned: the plugin's slash commands or prompts, the `claude-delegate` CLI
  (`plugins/delegate/claude_delegate/`), the reviewer's isolation (flags, environment allowlist,
  forbidden-file list), the launcher (`bin/claude-deepseek`), or the report archive;
- the commit where you found it;
- a description of the vulnerability and of its impact;
- the steps to reproduce it, or a proof of concept;
- a fix or mitigation, if you have one in mind.

Never include a real API key, a Claude credential or personal data in a report: redact them.

## What to expect

- We acknowledge your report and keep you informed of its assessment and of the fix.
- We may ask you for details, and we coordinate with you the date of any public disclosure.
- Once a fix is shipped, we publish a security advisory and credit you for the finding, unless you prefer to
  remain anonymous.

## What matters most here

The core promise of this project is the isolation of the delegated reviewer: it must not be able to read
outside the reviewed code or a `.env`, write, run a shell, or be driven by the configuration of the
repository under review — its hooks, MCP servers or `CLAUDE.md`. A bypass of any of these guarantees is the
most serious kind of finding for this project, and the `/delegate:selftest` command exists to detect it. If
you find one, report it privately.

Other surfaces worth your attention:

- the treatment of a pull request's own configuration (`.claude/`, `CLAUDE.md`, `.mcp.json`), which must
  never reach the reviewer;
- the resolution of `CLAUDE.md` `@path` imports, which must never escape the repository or reach a forbidden
  file;
- the launcher's handling of the AI Gateway key, and any way it could leak into the environment of a
  delegated session or into a report;
- the report archive, which may quote source code and stays under `${XDG_STATE_HOME:-~/.local/state}`.

## Guidelines for security research

- Reproduce the reviewer's isolation locally: run `/delegate:selftest`, and use temporary git repositories as
  the test suite does. The tests make no network call and no model call.
- If you must exercise a real delegated session, only use repositories and keys you own.
- Stop and report as soon as you have shown that a guarantee can be bypassed.

## Scope

In scope: the code and configuration of this repository — the plugin's commands and prompts, the
`claude-delegate` CLI and the isolation it enforces, the launcher, and the report handling.

Out of scope:

- vulnerabilities of [Claude Code](https://claude.com/claude-code) itself, of the Anthropic API or of the
  model providers, which should be reported to their maintainers (tell us too if our use of them exposes
  them);
- vulnerabilities of the [LINAGORA AI Gateway](https://github.com/linagora/ai-gateway), which should be
  reported there;
- anything that already requires control of the machine, the user's shell or the git configuration, and is
  therefore outside the threat model.
