#!/usr/bin/env bash
# Install the two sessions this project needs, on a fresh machine, in one go:
#
#   - a worker session, opened by the claude-worker launcher on a cheap
#     Anthropic-compatible API;
#   - a reviewer session on Anthropic, which the delegate plugin's slash
#     commands delegate to.
#
# It never signs in to Anthropic: that stays yours to do. It never updates
# Claude Code, and it never edits your shell profile. Everything it prints is
# in English, in short sentences.
#
# Interactive when a terminal is attached, including through the README's
# `curl ... | bash`: the answers are read from /dev/tty there. With no terminal
# at all, it uses the defaults and the CLAUDE_WORKER_* variables, and fails
# clearly if a key is missing.
#
# Re-runnable: each step looks at the state before acting.
set -euo pipefail

MARKETPLACE="linagora/claude-delegate"
PLUGIN="delegate@claude-delegate"
LOCAL_BIN="${HOME}/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/claude-worker"
CONFIG_FILE="${CONFIG_DIR}/config"
LAUNCHER_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/claude-worker"
REVIEWER_DIR="${HOME}/.claude-anthropic"
RAW_URL="https://raw.githubusercontent.com/${MARKETPLACE}/main"

# Providers offered, as "name|base url|default model|label". The free-text
# entry covers anything else, including an internal LiteLLM proxy.
PROVIDERS="linagora|https://ai-api.linagora.com|deepseek-v4.1-flash|LINAGORA gateway
deepseek|https://api.deepseek.com/anthropic|deepseek-v4-pro[1m]|DeepSeek
zai|https://api.z.ai/api/anthropic|glm-5.2|Z.ai
moonshot|https://api.moonshot.ai/anthropic|kimi-k3|Moonshot / Kimi
minimax|https://api.minimax.io/anthropic|MiniMax-M3|MiniMax
openrouter|https://openrouter.ai/api||OpenRouter
custom|||your own endpoint"

# The banner is for a person watching the output: a terminal on stdout is
# enough, even when stdin is a pipe.
BANNER=1
[ -t 1 ] || BANNER=0

# Questions need a readable terminal. Under `curl ... | bash` stdin is the
# script itself, so /dev/tty is asked instead: it is the terminal the command
# was typed in. Without either, nothing is asked and the defaults apply.
INPUT="/dev/stdin"
if [ ! -t 0 ]; then
  if { [ -r /dev/tty ] && [ -w /dev/tty ]; } 2>/dev/null && (: </dev/tty) 2>/dev/null; then
    INPUT="/dev/tty"
  fi
fi
INTERACTIVE=1
if [ "$BANNER" -eq 0 ] || { [ ! -t 0 ] && [ "$INPUT" = "/dev/stdin" ]; }; then
  INTERACTIVE=0
fi

say() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
die() {
  warn "Error: $*"
  exit 1
}

banner() {
  [ "$BANNER" -eq 1 ] || return 0
  cat <<'ART'

 ____  _____ _     _____  ____    _  _____ _____
|  _ \| ____| |   | ____|/ ___|  / \|_   _| ____|
| | | |  _| | |   |  _| | |  _  / _ \ | | |  _|
| |_| | |___| |___| |___| |_| |/ ___ \| | | |___
|____/|_____|_____|_____|\____/_/   \_\_| |_____|

  Two sessions: a worker on a cheap model, a reviewer on Anthropic.
ART
}

# Ask a question, echo the answer. Falls back to the default without a terminal.
ask() {
  local prompt="$1" default="$2" answer=""
  if [ "$INTERACTIVE" -eq 1 ]; then
    printf '%s [%s] ' "$prompt" "$default" >&2
    read -r answer <"$INPUT" || answer=""
  fi
  printf '%s' "${answer:-$default}"
}

ask_secret() {
  local prompt="$1" answer=""
  if [ "$INTERACTIVE" -eq 1 ]; then
    printf '%s ' "$prompt" >&2
    read -rs answer <"$INPUT" || answer=""
    printf '\n' >&2
  fi
  printf '%s' "$answer"
}

# -- steps ---------------------------------------------------------------

install_claude_code() {
  if command -v claude >/dev/null 2>&1; then
    say "Claude Code is installed. Leaving it as it is."
    return 0
  fi
  say "Installing Claude Code..."
  if ! command -v curl >/dev/null 2>&1; then
    die "curl is missing. Install it, then run this script again."
  fi
  curl -fsSL https://claude.ai/install.sh | bash
  if ! command -v claude >/dev/null 2>&1 && [ ! -x "${LOCAL_BIN}/claude" ]; then
    die "Claude Code was not found after installing it. Is ${LOCAL_BIN} on your PATH?"
  fi
  say "Claude Code installed."
}

install_plugin() {
  local claude_bin="$1"
  if "$claude_bin" plugin list 2>/dev/null | grep -q "$PLUGIN"; then
    say "The plugin is already installed. Leaving it as it is."
    return 0
  fi
  say "Adding the plugin marketplace..."
  if ! "$claude_bin" plugin marketplace add "$MARKETPLACE" >/dev/null 2>&1; then
    warn "The marketplace may already be there. Continuing."
  fi
  say "Installing the plugin..."
  # A failure here is not "already installed" — the check above ruled that out —
  # so it stops the installation instead of reporting a success that is not one.
  if ! "$claude_bin" plugin install "$PLUGIN" >/dev/null 2>&1; then
    die "the plugin could not be installed. Run \"${claude_bin##*/} plugin install ${PLUGIN}\" to see why."
  fi
}

# Where claude-worker comes from. Running from a copy of the repository, its own
# bin/ is used. Piped straight into bash there is no file beside the script, so
# the launcher is fetched once into a stable place and reused after that.
launcher_source() {
  local root="$1"
  if [ -n "$root" ] && [ -x "${root}/bin/claude-worker" ]; then
    printf '%s' "${root}/bin/claude-worker"
    return 0
  fi
  local target="${LAUNCHER_DIR}/claude-worker"
  if [ ! -s "$target" ]; then
    command -v curl >/dev/null 2>&1 || return 1
    mkdir -p "$LAUNCHER_DIR"
    curl -fsSL "${RAW_URL}/bin/claude-worker" -o "$target" 2>/dev/null || return 1
    chmod 755 "$target"
  fi
  printf '%s' "$target"
}

# Point a name in ~/.local/bin at the launcher. A file that is not a link is
# somebody else's and is never overwritten.
link_launcher_name() {
  local link
  local name="$1" target="$2"
  link="${LOCAL_BIN}/${name}"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    warn "${link} exists and is not a link. Leaving it alone."
    return 1
  fi
  ln -sfn "$target" "$link"
  return 0
}

link_launcher() {
  local root="$1" source
  mkdir -p "$LOCAL_BIN"
  source="$(launcher_source "$root")" ||
    die "the launcher could not be fetched from ${RAW_URL}. Check your network and run this again."
  # Without this link nothing works, so a failure here is fatal rather than
  # printed as a success. The compatibility name points at the link just made,
  # never at the network copy: it keeps working when the store is gone.
  link_launcher_name claude-worker "$source" ||
    die "${LOCAL_BIN}/claude-worker is not from this installer. Move it away, then run this again."
  link_launcher_name claude-deepseek "${LOCAL_BIN}/claude-worker" || true
  say "Launcher linked in ${LOCAL_BIN}."
}

check_path() {
  case ":${PATH}:" in
  *":${LOCAL_BIN}:"*) return 0 ;;
  esac
  say ""
  say "${LOCAL_BIN} is not on your PATH. Add this line to your shell profile:"
  say ""
  say "  export PATH=\"\${HOME}/.local/bin:\${PATH}\""
  say ""
  say "This script will not edit your profile for you."
}

choose_provider() {
  local provider="${CLAUDE_WORKER_PROVIDER:-}"
  if [ -z "$provider" ]; then
    # A second run keeps the provider already recorded, the way it keeps the
    # address and the model.
    provider="$(read_existing CLAUDE_WORKER_PROVIDER)"
  fi
  if [ -n "$provider" ]; then
    printf '%s' "$provider"
    return 0
  fi
  if [ "$INTERACTIVE" -eq 0 ]; then
    printf '%s' "linagora"
    return 0
  fi
  say "" >&2
  say "Which provider serves your worker model?" >&2
  local index=0 name
  while IFS='|' read -r name _ _ _; do
    index=$((index + 1))
    say "  ${index}) ${name}" >&2
  done <<<"$PROVIDERS"
  local choice
  choice="$(ask "Number" "1")"
  index=0
  while IFS='|' read -r name _ _ _; do
    index=$((index + 1))
    if [ "$index" = "$choice" ]; then
      printf '%s' "$name"
      return 0
    fi
  done <<<"$PROVIDERS"
  printf '%s' "linagora"
}

provider_defaults() {
  local wanted="$1" name url model _
  while IFS='|' read -r name url model _; do
    if [ "$name" = "$wanted" ]; then
      printf '%s|%s' "$url" "$model"
      return 0
    fi
  done <<<"$PROVIDERS"
  printf '%s|' ""
}

# Claude Code appends /v1/messages itself: a base URL ending in /v1 would
# become /v1/v1/messages. A trailing slash is dropped first, so /v1/ is caught
# too.
strip_v1() {
  local url="$1"
  while [ -n "$url" ] && [ "${url%/}" != "$url" ]; do
    url="${url%/}"
  done
  if [ "${url%/v1}" != "$url" ]; then
    warn "Note: the base URL must not end in /v1. Dropping it."
    url="${url%/v1}"
  fi
  printf '%s' "$url"
}

read_existing() {
  # The value a variable already has in the config file, so a second run can
  # offer it as the default instead of overwriting it in silence.
  local name="$1"
  [ -f "$CONFIG_FILE" ] || return 0
  sed -n "s/^${name}=\"\(.*\)\"\$/\1/p" "$CONFIG_FILE" | head -n1
}

# The keychain entry for a provider. LINAGORA keeps the name the README already
# tells people to store their gateway key under; every other provider gets its
# own entry, so two providers never share a key.
key_service_for() {
  case "$1" in
  linagora) printf '%s' "linagora-ai-api-key" ;;
  *) printf '%s' "claude-worker-$1" ;;
  esac
}

# Store the key in the system keychain when one is there to take it. The key
# then belongs to the machine, not to a file that backups and dotfile sync
# carry away. Returns non-zero when no keychain could be written, and the
# caller then falls back to the file.
store_key() {
  local service="$1" key="$2"
  if [ "$(uname)" = Darwin ] && command -v security >/dev/null 2>&1; then
    security add-generic-password -U -a "${USER:-claude-worker}" -s "$service" -w "$key" >/dev/null 2>&1
    return $?
  fi
  if command -v secret-tool >/dev/null 2>&1; then
    printf '%s' "$key" | secret-tool store --label="Claude Code worker key" service "$service" >/dev/null 2>&1
    return $?
  fi
  return 1
}

# Where the key sits for a provider, and what removing it takes.
remove_key() {
  local service="$1"
  [ -n "$service" ] || return 0
  if [ "$(uname)" = Darwin ] && command -v security >/dev/null 2>&1; then
    security delete-generic-password -s "$service" >/dev/null 2>&1 || true
    return 0
  fi
  if command -v secret-tool >/dev/null 2>&1; then
    secret-tool clear service "$service" >/dev/null 2>&1 || true
  fi
}

# The file is the fallback the launcher reads when the key is elsewhere, so it
# always says which keychain service holds the key.
write_config() {
  local provider="$1" base_url="$2" model="$3" key_service="$4" key="$5"
  mkdir -p "$CONFIG_DIR"
  chmod 700 "$CONFIG_DIR"
  local temporary="${CONFIG_FILE}.tmp.$$"
  {
    printf '# Written by install.sh and read by claude-worker, which parses these\n'
    printf '# "NAME=value" lines itself. The values are not escaped, so do not\n'
    printf '# source this file.\n'
    printf 'CLAUDE_WORKER_PROVIDER="%s"\n' "$provider"
    printf 'CLAUDE_WORKER_BASE_URL="%s"\n' "$base_url"
    printf 'CLAUDE_WORKER_MODEL="%s"\n' "$model"
    printf 'CLAUDE_WORKER_KEY_SERVICE="%s"\n' "$key_service"
    [ -n "$key" ] && printf 'CLAUDE_WORKER_API_KEY="%s"\n' "$key"
  } >"$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$CONFIG_FILE"
}

# A short call to the worker API. It authenticates the way the session does —
# `Authorization: Bearer`, from ANTHROPIC_AUTH_TOKEN — so a provider that
# accepts one and refuses the other is caught here rather than in the session.
# Only a 2xx is a success: a 400 means the provider refused the model or the
# body, not that everything is fine.
verify_worker() {
  local base_url="$1" model="$2" key="$3"
  local temporary detail status
  temporary="$(mktemp)"
  # The key travels on stdin, both in the config lines and in the body: an
  # argument would be readable in `ps` by every other user of the machine.
  status="$(
    {
      printf 'header = "content-type: application/json"\n'
      printf 'header = "anthropic-version: 2023-06-01"\n'
      printf 'header = "authorization: Bearer %s"\n' "$key"
      printf 'data = "%s"\n' "$(printf '{"model":"%s","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}' "$model" | sed 's/"/\\"/g')"
    } | curl -sS -o "$temporary" -w '%{http_code}' -X POST "${base_url}/v1/messages" --config - 2>/dev/null
  )" || status="000"
  case "$status" in
  2??)
    rm -f "$temporary"
    say "The worker session can reach ${base_url}."
    return 0
    ;;
  400)
    detail="$(head -c 300 "$temporary" 2>/dev/null || true)"
    rm -f "$temporary"
    die "the provider refused the request for the model \"${model}\" (HTTP 400). ${detail}"
    ;;
  401 | 403)
    rm -f "$temporary"
    die "the provider refused the key (HTTP ${status}). Check your API key."
    ;;
  404)
    rm -f "$temporary"
    die "the provider does not know the model \"${model}\" (HTTP 404). Check the model name."
    ;;
  000)
    rm -f "$temporary"
    die "the provider could not be reached at ${base_url}. Check the URL and your network."
    ;;
  *)
    detail="$(head -c 300 "$temporary" 2>/dev/null || true)"
    rm -f "$temporary"
    die "the provider answered HTTP ${status} at ${base_url}. ${detail}"
    ;;
  esac
}

check_reviewer() {
  # Claude Code creates this directory by itself the first time it runs with
  # CLAUDE_CONFIG_DIR, under whatever umask is in force, so it can end up
  # group- or world-readable. The Anthropic credentials live here, and the
  # README has the user create it 700 by hand, so an install that finds it
  # widens nothing and makes it match.
  if [ -d "${REVIEWER_DIR}" ]; then
    chmod 700 "${REVIEWER_DIR}" 2>/dev/null || true
  fi
  if [ -s "${REVIEWER_DIR}/.credentials.json" ]; then
    say ""
    say "The reviewer session is connected."
    say "To check that nothing leaks into it, run in a worker session:"
    say ""
    say "  /delegate:selftest"
    return 0
  fi
  say ""
  say "The reviewer session is not connected yet. To finish, sign in to Anthropic once:"
  say ""
  say "  mkdir -p ${REVIEWER_DIR} && chmod 700 ${REVIEWER_DIR}"
  say "  CLAUDE_CONFIG_DIR=${REVIEWER_DIR} claude"
  say ""
  say "Then type /login, and quit. The rest of this setup is already done."
}

describe_provider() {
  local wanted="$1" name _ _ label
  while IFS='|' read -r name _ _ label; do
    if [ "$name" = "$wanted" ]; then
      say "$label"
      return 0
    fi
  done <<<"$PROVIDERS"
  say "$wanted"
}

# Remove a link only when it is one this installer made. A file the user wrote
# under that name is left alone, exactly as link_launcher leaves it alone.
remove_link() {
  local link
  local name="$1"
  link="${LOCAL_BIN}/${name}"
  if [ ! -L "$link" ]; then
    [ -e "$link" ] && warn "${link} is not a link this installer made. Leaving it alone."
    return 0
  fi
  local target
  target="$(readlink "$link")"
  # The repository's own bin/, or the copy fetched when the script was piped
  # into bash: any other target belongs to somebody else.
  case "$target" in
  *"/bin/claude-worker" | *"/bin/claude-deepseek" | "${LAUNCHER_DIR}/claude-worker" | "${LOCAL_BIN}/claude-worker") rm -f "$link" ;;
  *) warn "${link} points at ${target}, not at this installer's launcher. Leaving it alone." ;;
  esac
}

uninstall() {
  # The keychain entry is read from the file before the file goes: it is the
  # only record of which service holds the key, and removing the installer's
  # own entry is part of undoing the installation.
  local key_service
  key_service="$(read_existing CLAUDE_WORKER_KEY_SERVICE)"
  say "Removing the configuration..."
  rm -f "$CONFIG_FILE"
  rmdir "$CONFIG_DIR" 2>/dev/null || true
  if [ -n "$key_service" ]; then
    say "Removing the key from the keychain..."
    remove_key "$key_service"
  fi
  say "Removing the launcher links..."
  remove_link claude-worker
  remove_link claude-deepseek
  say ""
  say "Done. Claude Code itself was left alone."
  say "To remove the plugin too, run:"
  say ""
  say "  claude plugin uninstall ${PLUGIN}"
}

main() {
  case "${1:-}" in
  --uninstall)
    banner
    uninstall
    return 0
    ;;
  --help | -h)
    say "Usage: install.sh [--uninstall] [--help]"
    say ""
    say "Installs the worker launcher and the delegate plugin."
    say "Set CLAUDE_WORKER_PROVIDER, CLAUDE_WORKER_MODEL, CLAUDE_WORKER_BASE_URL"
    say "and CLAUDE_WORKER_API_KEY to skip the questions."
    return 0
    ;;
  esac

  banner

  # Where this script lives, when it is a file at all. Piped into bash there is
  # no path, and the launcher is fetched instead of read beside it.
  local script="${BASH_SOURCE[0]:-}" root=""
  if [ -n "$script" ]; then
    root="$(cd "$(dirname "$script")" 2>/dev/null && pwd)" || root=""
  fi

  install_claude_code
  local claude_bin
  claude_bin="$(command -v claude || printf '%s' "${LOCAL_BIN}/claude")"
  install_plugin "$claude_bin"
  link_launcher "$root"
  check_path

  # A provider named in the environment or on the command line still needs an
  # address and a key: only the choice itself is skipped.
  local provider
  provider="$(choose_provider)"
  local defaults provider_url provider_model
  defaults="$(provider_defaults "$provider")"
  provider_url="${defaults%%|*}"
  provider_model="${defaults#*|}"

  # The address and the model of a previous run are reused only when that run
  # used the same provider: switching provider must not carry the old address
  # over to the new one. An empty value recorded on purpose counts as set.
  local stored_provider stored_url stored_model reuse_stored=0
  stored_provider="$(read_existing CLAUDE_WORKER_PROVIDER)"
  if [ -z "$stored_provider" ] || [ "$stored_provider" = "$provider" ]; then
    reuse_stored=1
  fi
  stored_url=""
  stored_model=""
  if [ "$reuse_stored" -eq 1 ]; then
    stored_url="$(read_existing CLAUDE_WORKER_BASE_URL)"
    if grep -q '^CLAUDE_WORKER_MODEL=' "$CONFIG_FILE" 2>/dev/null; then
      stored_model="$(read_existing CLAUDE_WORKER_MODEL)"
    fi
  fi
  local url="${CLAUDE_WORKER_BASE_URL:-${stored_url:-$provider_url}}"

  if [ -z "$url" ]; then
    url="$(ask "Base URL of your Anthropic-compatible API" "")"
  elif [ "$INTERACTIVE" -eq 1 ] && [ -n "$stored_url" ]; then
    url="$(ask "Base URL" "$stored_url")"
  fi
  url="$(strip_v1 "$url")"
  [ -n "$url" ] || die "no base URL given. Set CLAUDE_WORKER_BASE_URL, or answer the question."

  # The model follows the same precedence, and the key's scope decides how it is
  # settled. Claude Code always sends a model name and a restricted key refuses
  # every other one, so a name is always recorded: for a single-model key the
  # provider's default is recorded without asking, since the name itself is not
  # the user's choice.
  local model="${CLAUDE_WORKER_MODEL:-}"
  if [ -z "$model" ] && [ -n "$stored_model" ]; then
    model="$stored_model"
  fi
  [ -n "$model" ] || model="$provider_model"

  local scope
  scope="$(ask "Does your API key reach one model or several? (one/several)" "several")"
  if [ "$scope" = "one" ]; then
    if [ -n "${CLAUDE_WORKER_MODEL:-}" ]; then
      say "The model from the environment is kept: ${model}."
    elif [ -n "$model" ]; then
      say "No model is asked: every request will name ${model}. Change it in ${CONFIG_FILE}."
    else
      # Nothing to fall back on: the free-text provider proposes no model.
      model="$(ask "Model" "")"
      [ -n "$model" ] || die "no model given. A model name is needed on every request."
    fi
  else
    if [ "$provider" = "linagora" ] && [ "$INTERACTIVE" -eq 1 ]; then
      say "Tip: for a fixed model, create a key dedicated to this use."
    fi
    model="$(ask "Model" "$model")"
    [ -n "$model" ] || die "no model given."
  fi

  local key_service
  key_service="${CLAUDE_WORKER_KEY_SERVICE:-$(key_service_for "$provider")}"
  local key="${CLAUDE_WORKER_API_KEY:-}"
  if [ -z "$key" ] && [ "$reuse_stored" -eq 1 ]; then
    key="$(read_existing CLAUDE_WORKER_API_KEY)"
  fi
  if [ -z "$key" ]; then
    key="$(ask_secret "API key (not shown):")"
  fi
  [ -n "$key" ] || die "no API key given. Set CLAUDE_WORKER_API_KEY, or run this with a terminal."
  # The file holds `NAME="value"` lines and the key travels inside a curl config
  # line: a quote or a line break would break both.
  case "$key" in
  *'"'*)
    die "the API key contains a double quote. Check it and run this again."
    ;;
  *$'\n'*)
    die "the API key contains a line break. Check it and run this again."
    ;;
  esac

  say ""
  say "Provider : $(describe_provider "$provider")"
  say "Base URL : ${url}"
  say "Model    : ${model}"
  say ""

  verify_worker "$url" "$model" "$key"

  # The keychain comes first: a file survives a backup, a dotfile sync or a
  # `tar ~`, and the key goes with it. Without a keychain the file takes it,
  # at mode 600 and nothing else.
  if store_key "$key_service" "$key"; then
    write_config "$provider" "$url" "$model" "$key_service" ""
    say "The key is in the system keychain, under \"${key_service}\"."
  else
    write_config "$provider" "$url" "$model" "$key_service" "$key"
    say "No system keychain is available: the key is in ${CONFIG_FILE} (mode 600)."
  fi
  say "Configuration written to ${CONFIG_FILE}."

  check_reviewer

  say ""
  say "Done. Open a worker session with:"
  say ""
  say "  claude-worker"
}

main "$@"
