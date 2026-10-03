# claude-delegate

Plugin Claude Code qui délègue les revues de code d'une session branchée sur DeepSeek à Claude : Opus par défaut, Sonnet à la demande. La revue tourne dans une session Claude Code isolée et en lecture seule, déclenchée de façon déterministe par une slash command. Le plugin prépare aussi le passage de relais vers une session de spec sur Anthropic. La spécification est dans l'issue #1.

## Installation

Prérequis : Claude Code (de préférence le binaire natif, `~/.local/bin/claude`), git, Python 3.9 ou plus récent, une clé de l'AI Gateway de LINAGORA pour tes sessions de travail et un abonnement Claude pour le relecteur. Pour relire des pull requests, il faut aussi GitHub CLI (`gh`) ou, pour les merge requests GitLab, GitLab CLI (`glab`).

Toutes les étapes se font depuis un terminal.

1. **Ajouter la marketplace et installer le plugin.** Le dépôt est privé : il faut un accès git à `linagora/claude-delegate`.

   ```bash
   claude plugin marketplace add linagora/claude-delegate
   claude plugin install delegate@claude-delegate
   ```

2. **Installer le lanceur `claude-deepseek`**, qui ouvre Claude Code sur DeepSeek par l'AI Gateway de LINAGORA (`https://ai-api.linagora.com`, modèle `deepseek-v4.1-flash`). La marketplace a cloné le dépôt : un lien suffit, et le lanceur suit les mises à jour de la marketplace. Range ensuite ta clé du gateway dans le trousseau, la commande la demande :

   ```bash
   ln -s ~/.claude/plugins/marketplaces/claude-delegate/bin/claude-deepseek ~/.local/bin/claude-deepseek
   security add-generic-password -a "$USER" -s linagora-ai-api-key -w
   ```

   Sous Linux, range la clé avec `secret-tool store --label="AI Gateway LINAGORA" service linagora-ai-api-key` (paquet `libsecret-tools`). Sur un serveur sans trousseau, exporte-la plutôt dans `LINAGORA_API_KEY`.

   Ouvre ensuite tes sessions de travail avec `claude-deepseek`. Le lanceur ne règle ses variables que pour la session qu'il ouvre : tes autres sessions restent sur Anthropic.
   - Il fait pointer tous les modèles (principal, Opus, Sonnet, Haiku et sous-agents) vers celui du gateway, car une clé du gateway n'en atteint aucun autre.
   - Il porte le timeout des commandes `!` à 15 minutes : une revue Opus dépasse souvent les 2 minutes par défaut.
   - Claude Code ne connaît pas ce modèle : le coût qu'il affiche est faux, seule compte la facturation du gateway.
   - Les connecteurs de claude.ai (Gmail, Google Drive, etc.) ne sont pas disponibles dans ces sessions.
   - Pour passer par l'API de DeepSeek elle-même, positionne `CLAUDE_DEEPSEEK_BASE_URL`, `CLAUDE_DEEPSEEK_MODEL` et `CLAUDE_DEEPSEEK_KEY_SERVICE`, d'après la [documentation de DeepSeek pour Claude Code](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code).

3. **Te connecter une fois à Anthropic**, dans un dossier de configuration dédié et vierge. N'y crée aucun lien vers `~/.claude` : la session déléguée ne doit hériter ni de tes réglages, ni de tes plugins. Cette session ne sert qu'à la connexion : n'y installe rien.

   ```bash
   mkdir -m 700 ~/.claude-anthropic
   CLAUDE_CONFIG_DIR=~/.claude-anthropic claude   # puis /login, et quitter
   ```

   Sous macOS, Claude Code range ces identifiants dans le trousseau, sous une clé propre à ce dossier. Sous Linux, il les range dans le dossier lui-même.

4. **Vérifier l'isolation** du relecteur, depuis une session `claude-deepseek`, après l'installation puis après chaque mise à jour de Claude Code :

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

### Relire une pull request ou une merge request

```
/delegate:pr-review <numéro> [--forge github|gitlab] [--model sonnet]
```

La commande relit une pull request GitHub ou une merge request GitLab sur son propre code, et non sur ta branche locale.

La forge se déduit de l'hôte d'`origin` :

- `github.com` désigne GitHub ;
- un hôte dont le nom contient « gitlab », comme gitlab.com, ou auquel `glab` est connecté, comme une instance d'entreprise, désigne GitLab ;
- dans les autres cas, par exemple pour GitHub Enterprise, précise la forge avec `--forge github` ou `--forge gitlab`.

L'outil de la forge doit y être connecté : `gh auth login` ou `glab auth login`. `glab` n'est requis que pour GitLab.

- `gh` ou `glab` fournit le titre, la description, la branche cible, la tête et l'URL de la pull request.
- git récupère la branche cible et la tête de la pull request (`pull/<numéro>/head`, ou `merge-requests/<numéro>/head` sur GitLab) sans déplacer aucune référence de ton dépôt. Ta branche, ton index et ton arbre de travail ne changent pas non plus.
- Le relecteur lit la pull request dans un worktree détaché et jetable, créé hors du dépôt sans exécuter aucun hook git. Le CLI en retire d'abord tous les `CLAUDE.md`, `CLAUDE.local.md`, `.claude/` et `.mcp.json`, quelle que soit leur casse : la configuration apportée par la pull request n'atteint jamais le relecteur. Le worktree est supprimé à la fin, même en cas d'échec ou d'interruption.
- Le relecteur reçoit le titre, la description et le diff depuis le merge-base avec la branche cible. Ses conventions sont celles de la branche cible, jamais celles de la pull request : une modification de `CLAUDE.md` est relue comme du code.
- Les fichiers `.env*` et `.claude/settings*.json` restent hors de la revue, car ils peuvent contenir des secrets. Ceux que la pull request modifie sont nommés dans l'en-tête du rapport, à la ligne « Fichiers non relus » : relis-les toi-même.
- Le rapport donne un verdict, APPROVE ou REQUEST_CHANGES, justifié en une phrase. Son en-tête indique le numéro et l'URL de la pull request, sa branche cible et la tête relue.

DeepSeek vérifie ensuite chaque point à la tête relue, avec `git show <tête>:<chemin>`, sans checkout. Rien n'est publié sur la forge : c'est toi qui décides de ce que tu publies.

Si la pull request évolue, même par un force-push, relance simplement la commande.

La revue ne démarre pas, avec le code de sortie 3, dans ces cas :

- la forge d'`origin` n'est pas reconnue : précise-la avec `--forge` ;
- `gh` ou `glab` est absent, ou ne peut pas lire la pull request ;
- la pull request a changé pendant la préparation : relance alors la commande ;
- la pull request n'a aucun ancêtre commun avec sa branche cible, ne change que des fichiers exclus de la revue ou rien du tout, ou son diff dépasse 1 000 000 caractères.

### Re-revoir après corrections

```
/delegate:recheck [rapport]
```

Après tes corrections, la commande fait statuer le relecteur sur chaque constat Bloquant ou Important du rapport d'origine : traité, non traité ou mal traité, avec une justification. Il relit aussi tout ce qui a changé depuis la révision relue par ce rapport, pour repérer les régressions introduites par les correctifs.

- Sans argument, la re-revue porte sur le dernier rapport du dépôt. Sinon, désigne un rapport par son identifiant, ou par le chemin de son Markdown ou de son JSON.
- Une re-revue peut elle-même être re-revue : la suivante statue sur ce qu'elle a laissé ouvert, c'est-à-dire les constats non traités ou mal traités, avec leur dernier statut, et ses nouveaux constats bloquants ou importants. Tu peux ainsi enchaîner corrections et re-revues.
- Le relecteur reçoit les constats à statuer, l'écart depuis la révision relue par le rapport d'origine et le diff complet courant. L'état courant est figé comme pour une revue hostile, fichiers non suivis compris. L'écart se limite aux fichiers que touche ton travail, avant ou après les corrections : ce qu'un rebase ou une fusion apporte de la base n'y figure pas. Le relecteur tourne avec le modèle de la revue d'origine.
- Le rapport rappelle chaque constat statué et son statut, puis donne les nouveaux constats, numérotés à la suite de tous les précédents. Son en-tête le relie au rapport d'origine.
- DeepSeek résume les statuts et liste ce qui reste bloquant.

Pour une pull request ou une merge request, la re-revue redemande la pull request à sa forge, récupère sa nouvelle tête et la fait relire dans un nouveau worktree jetable, nettoyé comme pour la revue, avec les conventions de la branche cible. L'écart va de la tête relue par le rapport d'origine jusqu'à la nouvelle. Cela fonctionne même après un force-push, tant que l'ancienne tête est encore présente dans ton dépôt. Comme pour la revue, DeepSeek vérifie chaque point avec `git show <tête>:<chemin>`, sans checkout, et rien n'est publié sur la forge.

La re-revue ne démarre pas, avec le code de sortie 3, dans ces cas :

- le rapport est introuvable, illisible, ou concerne un autre dépôt ;
- rien n'a changé depuis le rapport d'origine ;
- git a purgé la révision relue par le rapport d'origine, par exemple l'ancienne tête d'une pull request après un force-push : lance alors une revue complète ;
- l'écart et le diff complet dépassent ensemble 1 000 000 caractères ;
- pour une pull request, les mêmes cas que pour sa revue : forge, outil ou tête introuvables.

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

Depuis un terminal : `<dossier du plugin>/bin/claude-delegate hostile-review [base]`, `pr-review <numéro>` ou `recheck [rapport]`.

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

Les tests appellent le CLI comme un processus, dans de vrais dépôts git temporaires, avec un faux `claude` et un faux `gh` ou `glab`. Une pull request y vit dans un dépôt nu local qui sert d'`origin`, auquel une règle `url.insteadOf` donne une URL GitHub ou GitLab. Le lanceur `claude-deepseek` est testé de la même façon, avec de faux `claude`, `security`, `secret-tool` et `uname`. Les tests ne font ni appel réseau ni appel de modèle.
