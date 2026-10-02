# claude-delegate

Plugin Claude Code qui délègue les revues de code d'une session branchée sur DeepSeek à Claude : Opus par défaut, Sonnet à la demande. La revue tourne dans une session Claude Code isolée et en lecture seule, déclenchée de façon déterministe par une slash command. La spécification est dans l'issue #1.

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
/delegate:hostile-review [base] [--model sonnet]
```

La commande relit tous les changements depuis le merge-base avec la base : commités, indexés ou non, ainsi que les nouveaux fichiers non suivis, mais pas ceux qu'ignore git. Sans argument, la base est la branche par défaut d'`origin`, ou `main` à défaut.

L'état relu est figé dans un commit technique non référencé, sans toucher à ton index. Son identifiant figure dans le rapport, à la ligne « Révision relue ». Le relecteur lit aussi les fichiers concernés dans ton arbre de travail : ne les modifie pas pendant la revue.

La revue ne démarre pas, avec le code de sortie 3, dans ces cas :

- le répertoire n'est pas un dépôt git, ou le dépôt n'a encore aucun commit ;
- la base est introuvable, ou n'a aucun ancêtre commun avec `HEAD` ;
- il n'y a rien à relire ;
- le diff dépasse 1 000 000 caractères.

Le relecteur connaît les conventions du projet : le CLI lui fournit le `CLAUDE.md` racine tel qu'il est au merge-base, avec ses imports `@chemin` lus dans la même révision. Une modification de `CLAUDE.md` dans les changements relus n'est donc jamais prise pour une consigne : elle est relue comme le reste du code.

Le relecteur est Opus par défaut. `--model sonnet` le remplace par Sonnet, et aucun autre modèle n'est accepté.

L'en-tête du rapport indique comment la revue a tourné :

- le modèle réellement utilisé et l'effort ;
- les tours, le coût estimé et la durée ;
- le hash du prompt envoyé ;
- les versions du plugin et de Claude Code ;
- les permissions refusées au relecteur.

### Codes de sortie

| Code | Signification |
|---|---|
| 0 | Revue réussie, rapport archivé |
| 2 | Arguments invalides |
| 3 | Préparation impossible : le relecteur n'a pas été appelé |
| 4 | Quota Claude épuisé, avec la date de reprise si elle est connue |
| 5 | Revue incomplète : plafond de budget ou nombre maximal de tours atteint |
| 6 | Sortie structurée du relecteur absente ou non conforme |
| 7 | Autre échec de la session déléguée, ou rapport impossible à archiver |

En cas d'échec, rien n'est archivé et le message part sur la sortie d'erreur. Claude Code annule alors la commande et affiche ce message.

Le rapport (constats Bloquant, Important et Mineur) est archivé dans `${XDG_STATE_HOME:-~/.local/state}/claude-delegate/<dépôt>/`, accompagné d'un JSON. Il est ensuite injecté dans la session. DeepSeek vérifie et classe chaque point sans rien modifier avant ta validation.

Depuis un terminal : `<dossier du plugin>/bin/claude-delegate hostile-review [base]`.

## Isolation de la session déléguée

- **Lecture seule** : `--restricted --tools "Read,Grep,Glob"`. Pas de shell, pas de web, pas d'écriture, et des lectures confinées au dépôt relu.
- **Configuration ignorée** : les settings, hooks, règles d'autorisation et `CLAUDE.md` du projet ne sont pas chargés par Claude Code, ni les serveurs MCP (`--strict-mcp-config`). Seule la version de confiance de `CLAUDE.md`, fournie par le CLI, atteint le relecteur. En cas de demande non autorisée, le refus est automatique (`--permission-mode dontAsk`).
- **Fichiers interdits** : `**/.env`, `**/.env.*` et `**/.claude/settings*.json`. Le relecteur ne peut pas les lire, et ils sont exclus du diff qu'il reçoit.
- **Environnement reconstruit à partir de rien** : seules `HOME`, `USER`, `LOGNAME`, `PATH`, `LANG`, `LC_*`, `TERM` et `TMPDIR` passent, plus `CLAUDE_CONFIG_DIR=~/.claude-anthropic`. Aucune variable `ANTHROPIC_*` ou `CLAUDE_CODE_*` ni aucun jeton.
- **Coût borné** : effort `high`, 30 tours au plus, et un plafond de 5 $ estimés. Ce plafond est souple : Claude Code le vérifie après chaque appel, il peut donc être dépassé d'un appel.

Variables utiles :

- `CLAUDE_DELEGATE_BIN` : binaire `claude` à utiliser. Sinon, le CLI prend `~/.local/bin/claude`, puis le premier `claude` du `PATH` qui n'est pas un shim cmux.
- `XDG_STATE_HOME` : racine de l'archive des rapports.

## Développement

```bash
python3 -m unittest discover -s tests -t .
claude plugin validate --strict . && claude plugin validate --strict plugins/delegate
```

Les tests appellent le CLI comme un processus, dans de vrais dépôts git temporaires, avec un faux `claude`. Ils ne font ni appel réseau ni appel de modèle.
