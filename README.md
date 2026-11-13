# Trading Desk IA — paper trading multi-agents

Argent fictif uniquement (500 € de départ). Aucun ordre réel, aucune clé d'échange.

## Comment ça marche

| Pièce | Où elle tourne | Fréquence | Rôle |
|---|---|---|---|
| **Moteur** (`engine/tick.py`) | GitHub Actions (gratuit) | toutes les 5 min | Prix Kraken, stops et objectifs vérifiés minute par minute, exécution des ordres, scanner de signaux |
| **Comité d'agents** (`agents/COMITE.md`) | Tâche planifiée Claude | toutes les heures | Technique, macro, sentiment, trader, risk manager : débat et décision |
| **Terminal** (`docs/index.html`) | GitHub Pages (gratuit) | prix live toutes les 5 s | Ce que tu consultes sur iPhone |

Le comité ne touche jamais au portefeuille : il dépose une décision dans `docs/data/inbox/`, et seul le moteur l'exécute après ses propres contrôles de risque.

## Fichiers de données (`docs/data/`)

`state.json` portefeuille · `trades.json` transactions clôturées · `decisions.json` réunions du comité · `activite.json` journal des agents · `equity.json` courbe du capital · `signals.json` scanner · `market.json` prix et sentiment · `status.json` santé du moteur.

## Commandes

```
python engine/tick.py            # un passage du moteur
python engine/brief.py           # brief du comité
python engine/decide.py check decision.json
python engine/decide.py submit decision.json --now
python tests/test_engine.py      # tests de bout en bout
```

## Mise en ligne (une seule fois)

1. Dépôt GitHub **public** (Pages et Actions illimités gratuits ; il ne contient aucun secret).
2. Settings → Pages → Source : branche `main`, dossier `/docs`.
3. Settings → Actions → General → Workflow permissions : *Read and write*.
4. Sur iPhone : ouvrir l'adresse Pages dans Safari → Partager → *Sur l'écran d'accueil*.
