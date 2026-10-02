# claude-delegate

Plugin Claude Code qui délègue les revues de code d'une session branchée sur DeepSeek à Claude Opus. La revue tourne dans une session Claude Code isolée et en lecture seule, déclenchée de façon déterministe par une slash command. La spécification est dans l'issue #1.

## Installation

Prérequis : Claude Code (de préférence le binaire natif, `~/.local/bin/claude`), git, Python 3.9 ou plus récent, et un abonnement Claude.

1. **Installer le plugin**, dans la configuration qu'utilisent tes sessions DeepSeek. Le dépôt est privé : il faut un accès git à `linagora/claude-delegate`.

   ```
   /plugin marketplace add linagora/claude-delegate
   /plugin install delegate@claude-delegate
   ```

2. **Te connecter une fois à Anthropic**, dans un dossier de configuration dédié et vierge. N'y crée aucun lien vers `~/.claude` : la session déléguée ne doit hériter ni de tes réglages, ni de tes plugins.

   ```bash
   mkdir -m 700 ~/.claude-anthropic
   CLAUDE_CONFIG_DIR=~/.claude-anthropic claude   # puis /login, et quitter
   ```

   Sous macOS, Claude Code range ces identifiants dans le trousseau, sous une clé propre à ce dossier. Sous Linux, il les range dans le dossier lui-même.

3. **Relever le timeout des commandes `!`**, seulement pour les sessions DeepSeek. Une revue Opus dépasse souvent les 2 minutes par défaut. Ajoute la ligne là où tu exportes les variables DeepSeek (`ANTHROPIC_BASE_URL`…), par exemple dans une fonction de lancement :

   ```bash
   export BASH_DEFAULT_TIMEOUT_MS=900000   # 15 min
   ```

   Ne la mets pas dans un `~/.claude/settings.json` partagé avec tes sessions Anthropic : elle s'appliquerait à tous leurs appels Bash.

## Utilisation

```
/delegate:hostile-review [base]
```

La commande relit les changements commités, indexés ou non depuis le merge-base avec la base. Sans argument, la base est la branche par défaut d'`origin`, ou `main` à défaut.

Le rapport (constats Bloquant, Important et Mineur) est archivé dans `${XDG_STATE_HOME:-~/.local/state}/claude-delegate/<dépôt>/`, accompagné d'un JSON. Il est ensuite injecté dans la session. DeepSeek vérifie et classe chaque point sans rien modifier avant ta validation.

Depuis un terminal : `<dossier du plugin>/bin/claude-delegate hostile-review [base]`.

## Isolation de la session déléguée

- **Lecture seule** : `--restricted --tools "Read,Grep,Glob"`. Pas de shell, pas de web, pas d'écriture, et des lectures confinées au dépôt relu.
- **Configuration ignorée** : les settings, hooks, règles d'autorisation et `CLAUDE.md` du projet ne sont pas chargés, ni les serveurs MCP (`--strict-mcp-config`). En cas de demande non autorisée, le refus est automatique (`--permission-mode dontAsk`).
- **Lectures interdites** : `**/.env`, `**/.env.*` et `**/.claude/settings*.json`.
- **Environnement reconstruit à partir de rien** : seules `HOME`, `USER`, `LOGNAME`, `PATH`, `LANG`, `LC_*`, `TERM` et `TMPDIR` passent, plus `CLAUDE_CONFIG_DIR=~/.claude-anthropic`. Aucune variable `ANTHROPIC_*` ou `CLAUDE_CODE_*` ni aucun jeton.
- **Coût borné** : Opus en effort `high`, 30 tours au plus, 5 $ estimés au plus.

Variables utiles :

- `CLAUDE_DELEGATE_BIN` : binaire `claude` à utiliser. Sinon, le CLI prend `~/.local/bin/claude`, puis le premier `claude` du `PATH` qui n'est pas un shim cmux.
- `XDG_STATE_HOME` : racine de l'archive des rapports.

## Développement

```bash
python3 -m unittest discover -s tests -t .
claude plugin validate --strict . && claude plugin validate --strict plugins/delegate
```

Les tests appellent le CLI comme un processus, dans de vrais dépôts git temporaires, avec un faux `claude`. Ils ne font ni appel réseau ni appel de modèle.
