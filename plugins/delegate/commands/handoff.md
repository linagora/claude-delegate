---
description: Rédige un brief pour préparer une session de spec sur Anthropic (grill-me, puis to-spec)
argument-hint: "<sujet>"
disable-model-invocation: true
---

Rédige un brief de passage de relais sur ce sujet : $ARGUMENTS

Si aucun sujet n'est donné, demande-le avant d'écrire quoi que ce soit.

Le brief prépare une session de spécification qui aura lieu dans une autre session Claude Code, sur Anthropic, sans accès à cette conversation. Il doit donc se suffire à lui-même.

1. Écris-le dans `docs/specs/brief-AAAAMMJJ-<sujet>.md` :
   - AAAAMMJJ est la date du jour ;
   - `<sujet>` est le sujet en minuscules, sans accents, avec des tirets entre les mots ;
   - crée le dossier s'il n'existe pas, et ne remplace jamais un brief existant : ajoute `-2`, `-3`… au nom.
2. Structure-le avec exactement ces sections :
   - `## Contexte` : la situation et le problème, pour un lecteur qui découvre le sujet ;
   - `## Objectif` : ce que la spec doit permettre d'obtenir ;
   - `## Décisions déjà prises`, avec leur raison quand elle est connue ;
   - `## Contraintes` : techniques, de calendrier, de compatibilité ;
   - `## Questions ouvertes` : ce que la session de spec devra trancher ;
   - `## Fichiers et références` : les chemins du dépôt, les issues et les liens utiles.
3. Appuie-toi sur cette conversation et sur le code. N'invente rien : écris « Rien à signaler » dans une section vide. N'y recopie aucun secret.
4. Termine par une phrase qui donne le chemin du brief et suggère d'ouvrir une session Claude Code sur Anthropic, puis d'y enchaîner `/mattpocock-skills:grill-me` et `/mattpocock-skills:to-spec` à partir de ce brief.

Ne modifie aucun autre fichier.
