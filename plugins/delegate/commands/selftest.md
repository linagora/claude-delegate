---
description: Vérifie sur le vrai Claude Code que le relecteur délégué reste isolé (Haiku, quelques centimes). Sonde de diagnostic de l'isolation du relecteur, à lancer à la main.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/claude-delegate selftest:*)
user-invocable: true
disable-model-invocation: true
---

!`${CLAUDE_PLUGIN_ROOT}/bin/claude-delegate selftest`

Le texte ci-dessus est le résultat du selftest de l'isolation du relecteur délégué. Résume-le en une phrase. Si une vérification n'est pas « OK », dis-le clairement et recommande de ne pas utiliser la délégation tant que la cause n'est pas comprise. Ne modifie aucun fichier.
