# claude-delegate

A Claude Code plugin that delegates code reviews from a worker session running on a cheap
third-party model to an isolated, read-only reviewer session on Anthropic.

## Language

**Worker session**:
The Claude Code session the user works in, opened on a third-party model over an
Anthropic-compatible endpoint, so it costs little to run.
_Avoid_: deepseek session, cheap session, main session

**Reviewer session**:
The isolated, read-only session the worker delegates to, which always runs on Anthropic.
_Avoid_: delegated session, Claude session, Opus session

**Provider**:
A third-party service serving the worker session's model over an Anthropic-compatible
endpoint, identified by its base URL.
_Avoid_: backend, vendor, gateway (a gateway is one kind of provider, not the concept)

**Scoped key**:
A provider credential that reaches a single model. The installer recommends creating one per
worker session; the alternative is a credential that reaches several models, whose model the
user then enters by hand.
_Avoid_: API key, token, credential (too generic)

**Review**:
One delegated run of the reviewer session over a revision, which produces a report.
_Avoid_: delegation (the delegation is the act; the review is the thing produced)

**Report**:
The archived output of a review: a header naming the revision, a verdict and a list of findings,
kept under `${XDG_STATE_HOME:-~/.local/state}` and identified so a recheck can re-read it.
_Avoid_: result, output, review (the report is what a review leaves behind)
