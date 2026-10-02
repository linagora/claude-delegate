# claude-delegate

Plugin Claude Code qui délègue les revues de code d'une session branchée sur DeepSeek à Claude : Opus par défaut, Sonnet à la demande. La revue tourne dans une session Claude Code isolée et en lecture seule, déclenchée de façon déterministe par une slash command. Le plugin prépare aussi le passage de relais vers une session de spec sur Anthropic. La spécification est dans l'issue #1.

## Installation

Prérequis : Claude Code (de préférence le binaire natif, `~/.local/bin/claude`), git, Python 3.9 ou plus récent, et un abonnement Claude. Pour relire des pull requests GitHub, il faut aussi GitHub CLI (`gh`).

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

4. **Vérifier l'isolation** du relecteur, après l'installation puis après chaque mise à jour de Claude Code :

   ```
   /delegate:selftest
   ```

   Le selftest construit un projet piégé et demande au relecteur d'en sortir : lire hors du dépôt et `.env`, écrire, lancer un shell. Il vérifie aussi que le hook, le serveur MCP et le `CLAUDE.md` du projet n'agissent pas. Il tourne sur Haiku et coûte quelques centimes. Plusieurs garanties reposent sur un comportement non documenté de `--restricted` : si une vérification n'est pas « OK », n'utilise pas la délégation avant d'en avoir compris la cause.

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

Le relecteur connaît les conventions du projet. Le CLI lui fournit le `CLAUDE.md` racine tel qu'il est au merge-base, ou sa cible s'il s'agit d'un lien symbolique, avec ses imports `@chemin` lus dans la même révision. Une modification de `CLAUDE.md` dans les changements relus n'apparaît que dans le diff : elle est relue comme le reste du code, jamais suivie comme une consigne.

Règles des imports :

- un import n'est suivi que vers un fichier du dépôt : jamais vers `~`, un chemin absolu, un répertoire ou un fichier interdit ;
- un import qu'on ne peut pas suivre est remplacé par la mention « import ignoré » ;
- les imports placés dans un bloc de code ne sont pas évalués ;
- les conventions sont bornées à 20 fichiers importés et à 100 000 caractères.

Si git ne peut pas lire les conventions, la revue s'arrête avec le code de sortie 3.

Le relecteur est Opus par défaut. `--model sonnet` le remplace par Sonnet, et aucun autre modèle n'est accepté.

L'en-tête du rapport indique comment la revue a tourné :

- le modèle réellement utilisé et l'effort ;
- les tours, le coût estimé et la durée ;
- le hash du prompt envoyé ;
- les versions du plugin et de Claude Code ;
- les permissions refusées au relecteur.

### Relire une pull request

```
/delegate:pr-review <numéro> [--model sonnet]
```

La commande relit une pull request GitHub sur son propre code, et non sur ta branche locale. `origin` doit être sur `github.com`, et `gh` doit y être connecté (`gh auth login`).

- `gh` fournit le titre, la description, la branche cible, la tête et l'URL de la pull request.
- git récupère la branche cible et la tête de la pull request (`pull/<numéro>/head`) sans déplacer aucune référence de ton dépôt. Ta branche, ton index et ton arbre de travail ne changent pas non plus.
- Le relecteur lit la pull request dans un worktree détaché et jetable, créé hors du dépôt sans exécuter aucun hook git. Le CLI en retire d'abord tous les `CLAUDE.md`, `CLAUDE.local.md`, `.claude/` et `.mcp.json`, quelle que soit leur casse : la configuration apportée par la pull request n'atteint jamais le relecteur. Le worktree est supprimé à la fin, même en cas d'échec ou d'interruption.
- Le relecteur reçoit le titre, la description et le diff depuis le merge-base avec la branche cible. Ses conventions sont celles de la branche cible, jamais celles de la pull request : une modification de `CLAUDE.md` est relue comme du code.
- Le rapport donne un verdict, APPROVE ou REQUEST_CHANGES, justifié en une phrase. Son en-tête indique le numéro et l'URL de la pull request, sa branche cible et la tête relue.

DeepSeek vérifie ensuite chaque point à la tête relue, avec `git show <tête>:<chemin>`, sans checkout. Rien n'est publié sur GitHub : c'est toi qui décides de ce que tu publies.

Si la pull request évolue, même par un force-push, relance simplement la commande.

La revue ne démarre pas, avec le code de sortie 3, dans ces cas :

- `origin` n'est pas sur `github.com` ;
- `gh` est absent, ou ne peut pas lire la pull request ;
- la pull request a changé pendant la préparation : relance alors la commande ;
- la pull request n'a aucun ancêtre commun avec sa branche cible, ne change rien, ou son diff dépasse 1 000 000 caractères.

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
| 8 | Selftest en échec : l'isolation du relecteur n'est plus garantie |

En cas d'échec, rien n'est archivé et le message part sur la sortie d'erreur. Claude Code annule alors la commande et affiche ce message.

Le rapport (constats Bloquant, Important et Mineur) est archivé dans `${XDG_STATE_HOME:-~/.local/state}/claude-delegate/<dépôt>/`, accompagné d'un JSON. Il est ensuite injecté dans la session. DeepSeek vérifie et classe chaque point sans rien modifier avant ta validation.

Depuis un terminal : `<dossier du plugin>/bin/claude-delegate hostile-review [base]`, ou `pr-review <numéro>`.

### Préparer une spec

```
/delegate:handoff <sujet>
```

Les specs ne sont pas déléguées : elles s'écrivent dans une session Claude Code sur Anthropic, avec `grill-me` puis `to-spec`. Cette commande fait écrire par DeepSeek un brief daté dans `docs/specs/brief-AAAAMMJJ-<sujet>.md`. Il contient le contexte, l'objectif, les décisions déjà prises, les contraintes, les questions ouvertes, ainsi que les fichiers et références utiles. La session Anthropic n'a ensuite qu'à partir de ce brief.

## Isolation de la session déléguée

- **Lecture seule** : `--restricted --tools "Read,Grep,Glob"`. Pas de shell, pas de web, pas d'écriture, et des lectures confinées au code relu : le dépôt, ou le worktree de la pull request.
- **Configuration ignorée** : les settings, hooks, règles d'autorisation et `CLAUDE.md` du projet ne sont pas chargés par Claude Code, ni les serveurs MCP (`--strict-mcp-config`). Seule la version de confiance de `CLAUDE.md`, fournie par le CLI, lui est donnée comme consigne. En cas de demande non autorisée, le refus est automatique (`--permission-mode dontAsk`).
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
