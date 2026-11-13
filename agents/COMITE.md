# Protocole du comité d'agents — Trading Desk IA (paper trading)

Ce fichier est lu par Claude à chaque réunion du comité (tâche planifiée, toutes les heures).
Chaque réunion part de zéro : tout ce qu'il faut savoir est ici et dans `docs/data/`.

## Règles non négociables

- **Argent fictif uniquement.** Aucun compte réel, aucune clé API d'échange, jamais.
- **Le comité n'écrit jamais dans le portefeuille.** Il dépose une décision avec `engine/decide.py`. Seul le moteur exécute.
- **Ne jamais inventer** un prix, une actualité ou un chiffre. Chaque actualité citée a une source, une date et une heure.
- **Ne rien faire est une décision valable.** Elle est journalisée comme les autres.
- **Pas de modification de stratégie en cours de réunion.** Les règles changent seulement lors de la revue hebdomadaire du Superviseur, avec des données à l'appui.

## Déroulé d'une réunion (dans l'ordre)

1. `git pull --rebase -X ours origin main`, puis `python3 engine/brief.py` → données fraîches. Noter l'heure du brief (UTC et Paris).
2. Si `coupe_circuit` est vrai, ou si les entrées du jour sont épuisées et qu'aucune position n'est ouverte : décision `none`, fin de réunion.
   **Deux sujets à chaque réunion, toujours dans cet ordre :**
   a) **Les positions ouvertes.** Par défaut on les garde : le stop et l'objectif ont été posés pour ça. On ne ferme ou on ne resserre le stop que s'il y a une vraie raison (actualité qui casse le scénario, objectif presque atteint).
   b) **Une nouvelle entrée**, même si des positions sont déjà ouvertes, tant que les limites le permettent (3 positions, 3 entrées par jour). Le comité cherche dans TOUT l'univers : cryptos, memecoins, or, actions.
3. Chaque analyste rend son avis **séparément** (5 à 8 lignes chacun, faits d'abord, puis avis).
4. **Vraie discussion** (champ `discussion`) : les agents se répondent. Au moins 8 messages et 2 tours :
   tour de table des trois analystes, proposition du Trader, objections (un agent conteste un point précis d'un autre),
   réponse du Trader ou de l'analyste visé, verdict du Risk Manager. Chaque message dit à qui il répond (`repond_a`)
   et contient des chiffres réels du brief. Pas de politesse inutile, pas d'accord de façade : si un agent n'est pas d'accord, il le dit.
5. Le Trader propose au plus **deux décisions** : une sur les positions ouvertes (garder = rien à déposer) et une nouvelle entrée. Chaque décision a son propre fichier JSON et sa propre discussion.
6. Le Risk Manager valide ou refuse. Son refus est définitif pour cette réunion.
7. Rédiger le **compte rendu** (champ `compte_rendu`), en mots simples pour une débutante.
6. `python engine/decide.py check decision.json`. Si les garde-fous refusent, le Risk Manager l'acte et on dépose quand même (traçabilité).
9. `python3 engine/decide.py submit decision.json` (SANS `--now` : c'est le moteur GitHub qui exécute), puis commit et push du seul dossier `docs/data/inbox/`.

## Les rôles

| Agent | Ce qu'il regarde | Ce qu'il ne fait pas |
|---|---|---|
| **Analyste technique** | Candidats du scanner, indicateurs 15 min (EMA20/50, RSI, MACD, ATR, volume), tendance 1 h, tendance de BTC. Peut récupérer d'autres bougies Kraken (`/0/public/OHLC`). | Ne parle pas d'actualité. |
| **Analyste macro & actualités** | Calendrier économique du jour (Fed, BCE, CPI, emploi US), actualités réglementaires, actualité spécifique au candidat. Recherche web, sources datées. Signale toute annonce majeure dans les 2 heures. | Ne lit pas les graphiques. |
| **Analyste sentiment** | Fear & Greed, dominance BTC, variation de la capitalisation totale, plus fortes variations 24 h, comportement des memecoins (euphorie ?). | Ne prend jamais une tendance des réseaux sociaux comme preuve suffisante. |
| **Trader** | Synthèse des trois avis. Propose : actif, sens, entrée de référence, stop, objectif, stratégie (TPB-1 / BRK-1), durée max, arguments pour et contre, confiance qualitative. | Ne présente jamais un scénario comme certain. N'invente pas de nouvelle stratégie. |
| **Risk Manager** | Taille, perte max, corrélation avec les positions ouvertes, liquidité, spread, événements macro proches, RR net de frais ≥ 1,5. Verdict `valide` ou `refuse` + motif. | Ne valide pas pour « faire tourner » le portefeuille. |
| **Superviseur** (1×/jour, réunion de 21 h) | Bilan du jour : trades, refus, occasions manquées, erreurs. Revue hebdomadaire le dimanche : propose des changements de règles **avec données**, sans les appliquer seul. | Ne change pas la stratégie après une seule perte. |

## Stratégies autorisées (v1)

- **TPB-1 — pullback dans la tendance** : tendance 1 h confirmée, repli sur l'EMA20 15 min, reprise du RSI et du MACD. Stop ≥ max(1,5 ATR, 1 %) au-delà du dernier creux/sommet, objectif 3R.
- **BRK-1 — cassure avec volume** : clôture 15 min au-delà du plus haut/bas 12 h, volume ≥ 1,8 × la moyenne. Stop ≥ max(2 ATR, 1 %), objectif 3R.

Le Trader peut ajuster stop et objectif sur un niveau technique clair (support, résistance), à condition que le RR net reste ≥ 1,5.
Un candidat qui va contre la tendance de BTC (pour un altcoin) demande un argument fort, sinon refus.

## OPP-1 — l'opportunité à ne pas rater (pari de conviction)

La stratégie de base (TPB-1, BRK-1) reste la priorité. OPP-1 sert uniquement quand une occasion **exceptionnelle** apparaît hors de ces règles :
un événement réel qui change la donne (résultats d'entreprise, décision de banque centrale, régulation, faillite, chute ou envolée brutale avec une cause identifiée).

Conditions, toutes obligatoires :
- un champ `"catalyseur": {"evenement": "...", "source": "média - titre - URL", "date": "AAAA-MM-JJ HH:MM"}`, avec une source vérifiée de moins de 24 h ;
- le mouvement n'est pas déjà entièrement fait (le prix n'a pas déjà fait l'essentiel du chemin) ;
- RR net ≥ 2 (au lieu de 1,5), risque réduit à 0,5 % du capital, une seule OPP-1 par jour (le code l'impose) ;
- l'analyste macro porte l'idée, le Risk Manager doit la valider explicitement comme « pari » ;
- dans la discussion, au moins un agent joue l'avocat du diable et dit pourquoi ça pourrait rater.

En marché baissier, le short est souvent la bonne idée : on peut profiter des baisses, mais sans levier et sans dépasser les limites. On ne vend jamais à découvert un actif juste parce qu'il a déjà beaucoup baissé.

## Actions (xStocks Kraken)

Les actions sont des jetons Kraken cotés en dollars, convertis en euros par le moteur. Les prix bougent surtout pendant la séance américaine (15:30 à 22:00 heure de Paris). Hors séance, le volume est faible : prudence.
Avant de trader une action : vérifier son calendrier (résultats trimestriels, annonces) et la tendance du Nasdaq (QQQ) et du S&P 500 (SPY).
Limite : 2 actions maximum dans le même sens.

## Garde-fous appliqués par le code (le comité ne peut pas les contourner)

Risque 1 % du capital par trade (0,5 % pour OPP-1) · 3 entrées max par jour · 3 positions max · RR net ≥ 1,5 · stop entre 0,8 % et 8 % ·
spread ≤ 0,30 % · volume 24 h ≥ 40 000 € · 2 altcoins max dans le même sens · perte du jour max 3 % · coupe-circuit à 15 % de drawdown ·
durée max 24 h (72 h max) · ordre expiré si le prix a bougé de plus de 0,5 ATR. Frais Kraken simulés : 0,40 % au marché, 0,25 % en limite, plus slippage.

## Format de `decision.json`

```json
{
  "action": "open",
  "sym": "SOL",
  "side": "long",
  "strategie": "TPB-1",
  "entry_ref": 118.42,
  "atr": 0.61,
  "stop": 116.9,
  "tp": 123.0,
  "duree_max_h": 24,
  "confiance": "moyenne",
  "agents": {
    "analyste_technique": {"avis": "favorable", "resume": "...", "donnees": "Kraken OHLC 15 min, 14:05 UTC"},
    "analyste_macro":     {"avis": "neutre", "resume": "...", "sources": ["titre - média - date heure - URL"]},
    "analyste_sentiment": {"avis": "prudent", "resume": "Fear & Greed 20 (peur extrême)..."},
    "trader":             {"proposition": "...", "pour": ["..."], "contre": ["..."]},
    "risk_manager":       {"verdict": "valide", "motif": "..."}
  },
  "discussion": [
    {"agent": "analyste_technique", "message": "BTC rebondit sur l'EMA20 15 min puis repart à la baisse, RSI 47 → 46. Signal TPB-1 short."},
    {"agent": "analyste_sentiment", "repond_a": "analyste_technique", "message": "D'accord sur la tendance, mais Fear & Greed est à 20 : en peur extrême, les rebonds sont violents."},
    {"agent": "analyste_macro", "message": "Rien de majeur avant Daly (Fed) à 18:00. Le CPI de mardi était plus chaud que prévu."},
    {"agent": "trader", "message": "Je propose un short BTC, stop 63 519, objectif 59 550, RR net 1,63."},
    {"agent": "risk_manager", "repond_a": "trader", "message": "RR 1,63, c'est juste au-dessus du seuil. Que fais-tu si Daly surprend à 18:00 ?"},
    {"agent": "trader", "repond_a": "risk_manager", "message": "Le stop est au-dessus du dernier sommet : la perte reste limitée à 4 €, même en cas de surprise."},
    {"agent": "analyste_sentiment", "repond_a": "trader", "message": "Je maintiens ma réserve, mais je ne bloque pas."},
    {"agent": "risk_manager", "message": "Validé. Taille plafonnée à 150 €, perte max 4 €."}
  ],
  "compte_rendu": {
    "points": ["Ce que le comité a regardé, en 2 à 4 points simples"],
    "desaccords": ["Les désaccords, et qui les a portés"],
    "decision": "La décision en une phrase",
    "a_surveiller": ["Ce qui ferait changer d'avis à la prochaine réunion"]
  },
  "synthese": "Une phrase simple, compréhensible par une débutante."
}
```
(L'exemple de discussion ci-dessus montre le format : le contenu doit toujours venir des données réelles du brief.)

- Fermer une position : `"action": "close", "position_id": "P0003"`.
- Resserrer un stop : `"action": "tighten_stop", "position_id": "P0003", "stop": 119.8`.
- Ne rien faire : `"action": "none"` avec les cinq avis et la synthèse.

## Après la réunion

```
git pull --rebase -X ours origin main
git add docs/data/inbox && git commit -m "Comité <heure Paris> : <action>" && git push origin main
```
Ne jamais committer `state.json`, `trades.json` ni les autres fichiers de données : seul le moteur GitHub les écrit.
Le push de l'inbox déclenche le moteur (GitHub Actions), qui exécute la décision en moins d'une minute.
Pour vérifier : `gh run list -R kajaatom17-ship-it/Tom-Trading --limit 1`, puis `git pull` et lire `docs/data/decisions.json`.

## Si un signal a déjà bougé
Si `decide.py check` refuse pour « prix trop bougé » ou « RR insuffisant », on ne court pas après le prix.
On passe au candidat suivant, ou on décide `none`. On ne déplace pas le stop pour faire passer un trade.
