#!/usr/bin/env bash
# Human acceptance run for a Linux workstation (checklist #12, section A, E1).
#
# Replays A1-A10 against the machine it runs on and prints one verdict per
# line. It automates what a script can honestly automate; the two steps that
# need a person — signing in to Anthropic, and reading a report's triage — are
# printed as instructions and marked NON ÉVALUÉ, never guessed.
#
# Everything it touches lives in a temporary directory. The installer is
# exercised there under a fake HOME, so the real installation, its config and
# its links are never read or written. The one exception is A7/A10, which
# report on the real ~/.claude-anthropic because that is what the step is about.
#
# Usage: acceptance/linux.sh [--with-selftest]
#   --with-selftest also runs A10 (`claude-delegate selftest`), which calls
#   Anthropic and costs a few cents.

set -uo pipefail

WITH_SELFTEST=0
[ "${1:-}" = "--with-selftest" ] && WITH_SELFTEST=1

# The script is often run over SSH, in a non-login shell whose PATH does not
# carry ~/.local/bin. The whole point of A4/A5/A6 is that the launcher is there,
# so it is put first here, exactly as the user's profile would.
export PATH="${HOME}/.local/bin:${PATH}"

REPO_RAW="https://raw.githubusercontent.com/linagora/claude-delegate/main"
REVIEWER_DIR="${HOME}/.claude-anthropic"
REAL_LAUNCHER="${HOME}/.local/bin/claude-worker"

PASS=0 FAIL=0 UNEVALUATED=0
ok() { printf '  [ OK ]           %s\n' "$*"; PASS=$((PASS + 1)); }
no() { printf '  [ ÉCHEC ]        %s\n' "$*"; FAIL=$((FAIL + 1)); }
skip() { printf '  [ NON ÉVALUÉ ]   %s\n' "$*"; UNEVALUATED=$((UNEVALUATED + 1)); }
head_() { printf '\n=== %s ===\n' "$*"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK" || exit 1
curl -fsSL "${REPO_RAW}/install.sh" -o install.sh || { echo "install.sh introuvable"; exit 1; }

printf 'Recette Linux — checklist #12, section A (E1)\n'
printf 'Poste  : %s\n' "$(uname -n)"
printf 'Date   : %s\n' "$(date -u '+%Y-%m-%d %H:%M UTC')"
printf 'Claude : %s\n' "$(claude --version 2>&1 | head -1)"

# -- A1/A2 : a pty, so install.sh offers its questions ----------------------
# Runs install.sh under a real terminal in a throwaway HOME and types `answers`
# line by line. Prints everything the script said, for the record. The provider
# is LINAGORA because its gateway answers quickly, and the key is deliberately
# wrong: the call fails at the end, which is what makes A2 observable.
run_interactive_install() {
  local fake_home="$1" answers="$2"
  mkdir -p "$fake_home"
  FAKE_HOME="$fake_home" ANSWERS="$answers" python3 - <<'PY'
import os, pty, re, select, sys, time

fake = os.environ["FAKE_HOME"]
env = dict(os.environ)
env.pop("CLAUDE_WORKER_API_KEY", None)
env.pop("CLAUDE_WORKER_PROVIDER", None)
env["HOME"] = fake
env["XDG_CONFIG_HOME"] = fake + "/.config"
env["XDG_DATA_HOME"] = fake + "/.local/share"

pid, master = pty.fork()
if pid == 0:
    os.environ.clear()
    os.environ.update(env)
    os.execvp("bash", ["bash", "install.sh"])
    os._exit(127)

# Each answer is typed only once its prompt has appeared: the plugin
# installation runs before the questions, and its sub-processes flush the
# terminal's input, so anything typed early is lost. A prompt is a line ending
# in `[...]` — `Number [1]`, `Model [x]`, `(one/several) [several]` — and at
# most one answer is sent per prompt seen.
pending = os.environ["ANSWERS"].encode().split(b"\n")
# A prompt is either a line ending in `[...]` (Number [1], Model [x],
# (one/several) [several]) or the secret prompt, which ends in a colon.
prompt = re.compile(rb"(?:\[[^\]]*\]|API key \(not shown\):)\s*$", re.M)
out, deadline = b"", time.monotonic() + 90
ended = False
while time.monotonic() < deadline:
    ready, _, _ = select.select([master], [], [], 0.2)
    if ready:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            ended = True
            break
        if not chunk:
            ended = True
            break
        out += chunk
        if pending and prompt.search(chunk):
            time.sleep(0.2)
            os.write(master, pending.pop(0) + b"\n")
    if os.waitpid(pid, os.WNOHANG)[0]:
        ended = True
        break
if not ended:
    os.kill(pid, 9)
    sys.stderr.write("[pty] install.sh still asking after 60 s: killed\n")
    try:
        os.read(master, 65536)
    except OSError:
        pass
os.close(master)
sys.stdout.write(out.decode("utf-8", "replace"))
PY
}

head_ "A1/A2 — l'installeur pose ses questions et refuse une clé vide"
# Answers in order: provider=1 (LINAGORA), scope=Entrée, model=Entrée,
# key=« one » (deliberately not a key). A2 is observed when the gateway refuses
# it. The URL is not asked: LINAGORA's default fills it.
out="$(run_interactive_install "$WORK/home-a" $'1\n\n\none')"
printf '%s\n' "$out" > "$WORK/install-a1.txt"
printf '%s\n' "$out" | sed 's/^/    /'
if grep -qiE 'which provider serves|number \[' <<<"$out"; then
  ok "A1 — les questions sont posées sur le terminal, /dev/tty est lu"
else
  no "A1 — aucune question posée alors que le script tourne sur un terminal"
fi
if grep -qiE 'provider refused the key|refused the request|HTTP 40' <<<"$out"; then
  ok "A2 — une clé invalide fait échouer le script, après avoir réaffiché fournisseur / URL / modèle"
else
  no "A2 — la clé invalide n'a pas fait échouer le script"
fi

# -- A3 : where the key goes, on a machine without a keychain ---------------
head_ "A3 — où va la clé sur Linux, quand il n'y a pas de trousseau"
# A machine with no usable keychain: a fake secret-tool that always fails, so
# the fallback to the file is what is exercised. The provider call must succeed
# for the installer to reach the file, so a local endpoint answers 200.
a3_home="$WORK/home-a3"; mkdir -p "$a3_home/fakebin"
printf '#!/bin/sh\nexit 1\n' > "$a3_home/fakebin/secret-tool"; chmod +x "$a3_home/fakebin/secret-tool"
python3 - <<'PY' &
import http.server, socketserver
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200); self.send_header("content-type", "application/json")
        self.end_headers(); self.wfile.write(b'{"ok":true}')
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
socketserver.TCPServer(("127.0.0.1", 8732), H).serve_forever()
PY
a3_pid=$!; sleep 1
PATH="$a3_home/fakebin:$PATH" \
HOME="$a3_home" XDG_CONFIG_HOME="$a3_home/.config" XDG_DATA_HOME="$a3_home/.local/share" \
  CLAUDE_WORKER_PROVIDER=linagora CLAUDE_WORKER_BASE_URL=http://127.0.0.1:8732 \
  CLAUDE_WORKER_API_KEY=CLE_DE_TEST \
  bash install.sh >"$WORK/install-a3.txt" 2>&1
kill $a3_pid 2>/dev/null
cfg="$a3_home/.config/claude-worker/config"
if [ -f "$cfg" ] && [ "$(stat -c '%a' "$cfg")" = "600" ] && grep -q '^CLAUDE_WORKER_API_KEY=' "$cfg"; then
  ok "A3 — sans trousseau, la clé est dans le fichier, mode 600"
  grep -i 'no system keychain' "$WORK/install-a3.txt" | sed 's/^/        /'
else
  no "A3 — le repli sur le fichier, mode 600, n'a pas eu lieu ($(stat -c '%a' "$cfg" 2>/dev/null || echo absent))"
fi

# -- A4/A5/A6 : the launcher on a fresh install, in a throwaway HOME ---------
head_ "A4/A5/A6 — le lanceur, le PATH, la commande"
fake_home="$WORK/home-b"; mkdir -p "$fake_home"
# A local endpoint answers 200, because the installer must get past its own
# verification to reach the linking step; the gateway is not called.
python3 - <<'PY' &
import http.server, socketserver
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200); self.send_header("content-type", "application/json")
        self.end_headers(); self.wfile.write(b'{"ok":true}')
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
socketserver.TCPServer(("127.0.0.1", 8731), H).serve_forever()
PY
fake_pid=$!; sleep 1
# The fake HOME's bin is put on the PATH here: the advice line must then stay
# silent (the opposite case, missing from the PATH, is already visible in the
# A1/A2 output above, which ran without it).
PATH="$fake_home/.local/bin:$PATH" \
HOME="$fake_home" XDG_CONFIG_HOME="$fake_home/.config" XDG_DATA_HOME="$fake_home/.local/share" \
  CLAUDE_WORKER_PROVIDER=linagora CLAUDE_WORKER_BASE_URL=http://127.0.0.1:8731 \
  CLAUDE_WORKER_API_KEY=CLE_DE_TEST \
  bash install.sh >"$WORK/install-b.txt" 2>&1
sed 's/^/    /' "$WORK/install-b.txt"
if [ -L "$fake_home/.local/bin/claude-worker" ]; then
  ok "A4 — le lanceur est créé et c'est un lien -> $(readlink "$fake_home/.local/bin/claude-worker" | sed "s|$fake_home|~|")"
else
  no "A4 — aucun lien claude-worker créé"
fi
# A5 — both sides: silent when ~/.local/bin is on the PATH, and the A1/A2 run
# (no fake bin on the PATH) showed the advice line printed. Only the second is
# asserted here; the first is the sentence above.
if grep -q 'not on your PATH' "$WORK/install-b.txt"; then
  no "A5 — la ligne d'avis s'affiche alors que ~/.local/bin est dans le PATH"
elif grep -q 'not on your PATH' "$WORK/install-a1.txt"; then
  ok "A5 — avis affiché quand ~/.local/bin manque, silencieux quand il est là"
else
  no "A5 — la ligne d'avis ne s'est affichée dans aucun des deux cas"
fi
# A6 is about the real workstation: the launcher lives in the real ~/.local/bin,
# and the fact that it answers is what proves the link and the PATH are right.
if timeout 60 claude-worker --version >/dev/null 2>&1; then
  ok "A6 — claude-worker --version répond sur ce poste"
else
  no "A6 — claude-worker ne répond pas (lien ou PATH)"
fi
kill $fake_pid 2>/dev/null

# -- A8/A9 : what the real launcher exports ---------------------------------
head_ "A8/A9 — la session worker pointe le gateway"
# A fake `claude` first on the PATH prints what the launcher exported, so no
# session is opened and the gateway is not called.
fakebin="$WORK/fakebin"; mkdir -p "$fakebin"
cat > "$fakebin/claude" <<'PY'
#!/usr/bin/env python3
import json, os
names = ["ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "BASH_DEFAULT_TIMEOUT_MS"]
dump = {n: os.environ.get(n) for n in names}
dump["auth_token_set"] = bool(os.environ.get("ANTHROPIC_AUTH_TOKEN"))
print(json.dumps(dump))
PY
chmod +x "$fakebin/claude"
dump="$(PATH="$fakebin:/usr/bin:/bin" timeout 60 "$REAL_LAUNCHER" 2>/dev/null)"
read_json() { python3 -c 'import json,sys
try:
    print(json.loads(sys.argv[1]).get(sys.argv[2]) or "")
except Exception:
    print("")' "$1" "$2"; }
base="$(read_json "$dump" ANTHROPIC_BASE_URL)"
model="$(read_json "$dump" ANTHROPIC_MODEL)"
token="$(read_json "$dump" auth_token_set)"
to_ms="$(read_json "$dump" BASH_DEFAULT_TIMEOUT_MS)"
if [ "$base" = "https://ai-api.linagora.com" ] && [ "$token" = "True" ] && [ "$model" = "deepseek-v4.1-flash" ]; then
  ok "A8 — URL=${base}, modèle=${model}, ANTHROPIC_AUTH_TOKEN positionné"
elif [ -z "$base" ]; then
  skip "A8 — le lanceur n'a rien exporté : clé introuvable sur ce poste (voir A3/A7)"
else
  no "A8 — URL=${base}, modèle=${model:-vide}, jeton positionné=${token:-?}"
fi
if [ "$to_ms" = "900000" ]; then
  ok "A9 — BASH_DEFAULT_TIMEOUT_MS=${to_ms} (15 min)"
elif [ -n "$to_ms" ]; then
  no "A9 — BASH_DEFAULT_TIMEOUT_MS=${to_ms}, 900000 attendu"
else
  skip "A9 — non observable sans une clé (A8)"
fi

# -- A7/A10 : the reviewer session, the one part that is not automatable ----
head_ "A7/A10 — connexion du relecteur et selftest"
if [ -s "${REVIEWER_DIR}/.credentials.json" ]; then
  ok "A7 — le relecteur est connecté dans ${REVIEWER_DIR}"
  if [ "$WITH_SELFTEST" -eq 1 ]; then
    plugin_bin="${HOME}/.claude/plugins/marketplaces/claude-delegate/plugins/delegate/bin/claude-delegate"
    if [ ! -x "$plugin_bin" ]; then
      no "A10 — cli du plugin introuvable : ${plugin_bin}"
    else
      selftest="$(timeout 600 python3 "$plugin_bin" selftest 2>&1)"
      printf '%s\n' "$selftest" | sed 's/^/    /'
      if [ "$(grep -c '| OK |' <<<"$selftest")" -eq 8 ] && ! grep -q 'ÉCHEC\|NON ÉVALUÉ' <<<"$selftest"; then
        ok "A10 — les huit vérifications d'isolation sont OK"
      else
        no "A10 — le selftest n'a pas rendu huit OK"
      fi
    fi
  else
    skip "A10 — relancer avec --with-selftest pour l'exécuter (appel Anthropic, quelques centimes)"
  fi
else
  skip "A7 — le relecteur n'est pas connecté sur ce poste. À faire une fois, à la main :"
  printf '        CLAUDE_CONFIG_DIR=%s claude   puis /login, puis quitter\n' "$REVIEWER_DIR"
  skip "A10 — dépend de A7"
fi

# -- verdict ----------------------------------------------------------------
head_ "Résultat"
printf '  OK : %d    ÉCHEC : %d    NON ÉVALUÉ : %d\n' "$PASS" "$FAIL" "$UNEVALUATED"
printf '  Mode du dossier du relecteur : %s (700 attendu)\n' \
  "$(stat -c '%a' "$REVIEWER_DIR" 2>/dev/null || echo absent)"
[ "$FAIL" -eq 0 ] || exit 1
