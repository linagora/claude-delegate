---
description: Rédige un brief pour préparer une session de spec sur Anthropic (grill-me, puis to-spec). À déclencher quand l'utilisateur veut préparer une session de spécification à partir de la conversation en cours.
argument-hint: "<sujet>"
---

Rédige un brief de passage de relais sur ce sujet : $ARGUMENTS

Si aucun sujet n'est donné, demande-le avant d'écrire quoi que ce soit.

Le brief prépare une session de spécification qui aura lieu dans une autre session Claude Code, sur Anthropic, sans accès à cette conversation. Il doit donc se suffire à lui-même.

1. Écris-le à la racine du dépôt, dans `docs/specs/brief-AAAAMMJJ-<sujet>.md` :
   - AAAAMMJJ est la date du jour ;
   - `<sujet>` reprend le sujet avec seulement des minuscules non accentuées, des chiffres et des tirets (`[a-z0-9-]`, 60 caractères au plus) : tout autre caractère, y compris `/` et `.`, devient un tiret ;
   - vérifie d'abord si ce fichier existe. S'il existe, ajoute `-2`, `-3`… juste avant `.md` : ne remplace jamais un brief existant ;
   - crée le dossier `docs/specs/` s'il n'existe pas.
2. Structure-le avec exactement ces sections :
   - `## Contexte` : la situation et le problème, pour un lecteur qui découvre le sujet ;
   - `## Objectif` : ce que la spec doit permettre d'obtenir ;
   - `## Décisions déjà prises`, avec leur raison quand elle est connue ;
   - `## Contraintes` : techniques, de calendrier, de compatibilité ;
   - `## Questions ouvertes` : ce que la session de spec devra trancher ;
   - `## Fichiers et références` : les chemins du dépôt, les issues et les liens utiles.
3. Appuie-toi sur cette conversation et sur le code. N'invente rien : écris « Rien à signaler » dans une section vide. N'y recopie aucune valeur de secret (clé, jeton, mot de passe) : indique seulement où elle se trouve.
4. Termine par une phrase qui donne le chemin du brief et suggère d'ouvrir une session Claude Code sur Anthropic, puis d'y enchaîner `grill-me` et `to-spec` (`/mattpocock-skills:grill-me`, puis `/mattpocock-skills:to-spec`) à partir de ce brief.

Ne modifie aucun autre fichier.
