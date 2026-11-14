# Protocole du comité d'agents — Trading Desk IA (paper trading)

Ce fichier est lu par Claude à chaque réunion du comité (deux tâches planifiées décalées, une réunion toutes les 30 minutes).
Chaque réunion part de zéro : tout ce qu'il faut savoir est ici et dans `docs/data/`.

## Règles non négociables

- **Argent fictif uniquement.** Aucun compte réel, aucune clé API d'échange, jamais.
- **Le comité n'écrit jamais dans le portefeuille.** Il dépose une décision avec `engine/decide.py`. Seul le moteur exécute.
- **Ne jamais inventer** un prix, une actualité ou un chiffre. Chaque actualité citée a une source, une date et une heure.
- **Ne rien faire est une décision valable.** Elle est journalisée comme les autres.
- **Pas de modification de stratégie en cours de réunion.** Les règles changent seulement lors de la revue hebdomadaire du Superviseur, avec des données à l'appui.

## Déroulé d'une réunion (dans l'ordre)

1. `git pull --rebase -X ours origin main`, puis `python3 engine/brief.py` → données fraîches. Noter l'heure du brief (UTC et Paris).
   Lire en priorité la section `veille` du brief : alertes de prix (mouvements brusques, surtout « contre nous ») et actualités marquées importantes.
   Une alerte « contre nous » sur une position ouverte se discute EN PREMIER : garder (le stop protège) ou fermer tout de suite si l'actualité casse le scénario.
2. Si `coupe_circuit` est vrai, ou si les entrées du jour sont épuisées et qu'aucune position n'est ouverte : décision `none`, fin de réunion.
   **Deux sujets à chaque réunion, toujours dans cet ordre :**
   a) **Les positions ouvertes.** Par défaut on les garde : le stop et l'objectif ont été posés pour ça. On ne ferme ou on ne resserre le stop que s'il y a une vraie raison (actualité qui casse le scénario, objectif presque atteint).
   b) **Une nouvelle entrée**, même si des positions sont déjà ouvertes, tant que les limites le permettent (3 positions, 3 entrées par jour). Le comité cherche dans TOUT l'univers, avec ces priorités : **bourse (actions, ETF, indices), crypto et memecoins au même niveau, à scruter avec le même soin** ; l'or juste derrière. Le brief marque chaque candidat « prioritaire » ou « secondaire ».
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
| **Spécialiste memecoins** | DOGE, SHIB, PEPE, TRUMP, WIF, BONK, PENGU (bloc `memecoins` du brief + alertes de prix + actualités marquées « meme »). Il lit les mouvements violents : impulsion (bougies 15 min, volume très au-dessus de la normale), extension, épuisement (mèches, volume qui baisse, RSI extrême), retour sur la zone. Dit si le mouvement est « poursuivable » ou « déjà fini ». Vérifie le spread et la profondeur du carnet (`/0/public/Depth`) avant tout avis. | Ne propose jamais d'entrer sur une bougie verticale (plus de 2,5 ATR depuis le dernier creux). Ne se fie pas aux réseaux sociaux comme preuve. Ne dépasse jamais les garde-fous de taille. |
| **Trader** | Synthèse des trois avis. Propose : actif, sens, entrée de référence, stop, objectif, stratégie (TPB-1 / BRK-1), durée max, arguments pour et contre, confiance qualitative. | Ne présente jamais un scénario comme certain. N'invente pas de nouvelle stratégie. |
| **Risk Manager** | Taille, perte max, corrélation avec les positions ouvertes, liquidité, spread, événements macro proches, RR net de frais ≥ 1,5. Verdict `valide` ou `refuse` + motif. | Ne valide pas pour « faire tourner » le portefeuille. |
| **Superviseur** (1×/jour, réunion de 21 h) | Bilan du jour : trades, refus, occasions manquées, erreurs. Revue hebdomadaire le dimanche : propose des changements de règles **avec données**, sans les appliquer seul. | Ne change pas la stratégie après une seule perte. |

## Mode memecoins : vif, court, discipliné

Les memecoins sont suivis avec le même soin que la bourse et les cryptos principales. Le spécialiste memecoins parle à chaque réunion, même pour dire « rien de propre ». Ils bougent par vagues : impulsion violente, extension, puis retour rapide de 50 à 70 % du mouvement. Le piège est d'entrer au sommet de la vague.

Règles du comité pour eux :
1. **Ne pas poursuivre.** Pas d'entrée sur une bougie verticale. On entre après un retour sur la zone (TPB-1) ou sur une cassure confirmée avec volume (BRK-1), en préparant si besoin un ordre en attente `stop` juste au-dessus du plus haut (ou en dessous du plus bas pour un short).
2. **Les deux sens.** Un memecoin épuisé (mèche haute, volume qui baisse, RSI très élevé) est un bon short à étudier, avec le stop au-dessus de la mèche.
3. **Court terme.** `duree_max_h` entre 2 et 6 h. Objectif 3R, puis le trader de garde protège à +1R et laisse courir les gains.
4. **Vérifier la liquidité avant tout.** Spread, profondeur du carnet, volume des 24 h. Spread au-dessus de 0,30 % : pas d'ordre.
5. **Réactivité.** Une réunion toutes les 30 minutes, et les alertes de prix de la veille sur les memecoins se lisent en premier. Un mouvement de plus de 5 % en 15 minutes se discute tout de suite : garder, resserrer le stop ou prendre les gains.
6. **Corrélation.** Les memecoins suivent BTC. Si BTC casse un support en 15 min, les positions memecoins sont revues en premier. Maximum 2 altcoins dans le même sens (garde-fou du code).
7. **Pas de pari sans plan.** Chaque entrée a un stop, un objectif et une raison écrite. « Ça monte » n'est pas une raison.

**Budget serré (appliqué par le code, le comité ne peut pas le contourner) :**
- 3 entrées par jour comme d'habitude, **plus 1 entrée memecoin par jour au maximum** (elle ne consomme pas les 3 autres). Jusqu'à 4 positions ouvertes en tout, dont 1 seule memecoin.
- Risque 0,4 % du capital par trade (au lieu de 1 %), mise plafonnée à 6 % du capital, durée max 6 h.
- Si les memecoins perdent 1 % du capital dans la journée, plus aucun memecoin jusqu'au lendemain.

**Ajouter une crypto émergente.** Le spécialiste peut proposer d'ajouter à l'univers une crypto qui peut bouger fort (nouveau listing Kraken, annonce, catalyseur daté). Fichier déposé via `engine/decide.py submit` (pas de discussion requise, mais la raison doit apparaître dans le compte rendu de la réunion) :
`{"action":"ajouter_actif","sym":"XXX","pair":"XXXEUR","nom":"Nom","cat":"Emergent","raison":"ce qui peut se passer et pourquoi","source":"https://..."}`
`decide.py check` interroge Kraken : la paire doit exister en euros, avoir au moins 40 000 € de volume sur 24 h et un spread ≤ 0,5 %. Maximum 2 ajouts par jour et 12 en tout. Une crypto ajoutée suit les mêmes règles que les memecoins (budget serré). Jamais de symbole inventé : si Kraken ne le connaît pas, on n'ajoute rien.

## Stratégies autorisées (v1)

- **TPB-1 — pullback dans la tendance** : tendance 1 h confirmée, repli sur l'EMA20 15 min, reprise du RSI et du MACD. Stop ≥ max(1,5 ATR, 1 %) au-delà du dernier creux/sommet, objectif 3R.
- **BRK-1 — cassure avec volume** : clôture 15 min au-delà du plus haut/bas 12 h, volume ≥ 1,8 × la moyenne. Stop ≥ max(2 ATR, 1 %), objectif 3R.

Le Trader peut ajuster stop et objectif sur un niveau technique clair (support, résistance), à condition que le RR net reste ≥ 1,5.
Un candidat qui va contre la tendance de BTC (pour un altcoin) demande un argument fort, sinon refus.

## Annonces prévues : on réfléchit avant, pendant, après

Le brief contient `calendrier_annonces` (annonces des 48 h, avec `dans_minutes` et un statut).

**Tenir le calendrier à jour.** S'il est vide ou périmé : recherche web (sources officielles : calendrier Fed/BCE, BLS, résultats d'entreprises, annonces de la SEC/ETF, déblocages de jetons) et dépôt d'un fichier `{"action":"agenda","evenements":[{"titre":"CPI américain","quand_utc":"2026-11-14T13:30:00Z","impact":"haut","actifs":["BTC","ETH","NASDAQ"],"source":"...","attendu":"consensus ..."}]}` via `engine/decide.py submit`. Pas de discussion requise pour cette action. Ne jamais inventer une date : si elle n'est pas confirmée par une source, ne pas l'ajouter.

**AVANT (statut « A PREPARER », annonce à fort impact dans moins de 2 h).** Le comité choisit explicitement l'une de ces trois options et l'écrit dans le compte rendu :
1. **Ne rien faire** (le plus souvent le bon choix : spread large, glissement fort, mouvement dans un sens puis l'autre).
2. **Ordres jumeaux** : deux ordres `stop` en attente, un achat juste au-dessus de la zone et une vente à découvert juste en dessous, avec le même `groupe`, `"evenement": "<titre>"`, `expire_h` ≤ 2. Dès que l'un se déclenche, le moteur annule l'autre. Stop serré mais pas collé (≥ 1 ATR 15 min, sinon l'ordre est refusé par les garde-fous), et objectif 3R : on vise un gros gain rapide, pas une attente longue.
3. **Attendre la réaction** : aucun ordre avant l'annonce, on regarde les 15 à 30 minutes suivantes (voir APRÈS).

Les ordres jumeaux sont exécutés avec un **glissement d'annonce** (+0,30 %) et sont vérifiés minute par minute, un retournement brutal dans la même minute les touche. Le comité compte ce coût dans le RR net : si le RR net ne passe plus 1,5, pas d'ordre.

**PENDANT / APRÈS (statut « vient de sortir »).** On ne court pas derrière le premier mouvement. Le comité décrypte : le chiffre est-il au-dessus ou au-dessous de ce qui était attendu ? Le prix a-t-il fait un premier mouvement violent puis un retour (piège) ? Règle de réflexion :
- Premier mouvement pris par un ordre jumeau : le trader de garde protège vite (point mort à +1R) ; on accepte de sortir avec un gain correct plutôt que d'attendre le retournement.
- Pas de position : attendre une bougie 15 min fermée au-delà du plus haut/bas de l'annonce avec volume (cassure confirmée, BRK-1) ou un retour dans la zone (faux mouvement), puis seulement entrer.
- Écrire dans le compte rendu : « premier mouvement pris », « on attend le second » ou « on ne touche pas », avec la raison.

## Ordres en attente (pour ne pas entrer en retard)

Le comité ne se réunit pas en continu. Pour ne pas rater le bon moment, il place des **ordres en attente** que le moteur exécute seul, dans les 5 minutes où le prix atteint le niveau :
- `"action": "pending"`, avec `"type_ordre": "stop"` (on entre si le prix casse un niveau dans notre sens : cassure) ou `"limite"` (on entre si le prix revient sur un niveau : repli),
  `"declencheur": <prix>`, `"stop"`, `"tp"`, `"expire_h"` (4 h par défaut, 24 h maximum), `"strategie"`, plus la discussion et le compte rendu habituels.
- Le code vérifie les règles à la pose (RR, stop…) et à nouveau au déclenchement. Quatre ordres en attente maximum.
- Annuler : `"action": "cancel", "ordre_id": "O0007"`.
Exemple : PEPE rebondit sous une résistance. Plutôt que d'entrer tout de suite, on place un short « stop » sous le dernier creux : on n'entre que si la baisse reprend vraiment.

## Le trader de garde (entre les réunions)

Le moteur joue le rôle de trader de garde, toutes les 5 minutes, avec des règles fixes et sans IA :
- **Protection** : à +1R, il remonte le stop au prix d'entrée (plus de perte possible). À +2R, il verrouille +1R de profit. Le stop ne recule jamais.
- **Entrée seule** : sur un signal exceptionnel du scanner (score ≥ 75, RR net ≥ 2,5, aucune alerte), risque réduit à 0,5 %, une fois par jour maximum.
- **Laisser courir les gains** : quand l'objectif est atteint, il encaisse la moitié et laisse courir le reste, avec un stop qui suit le meilleur prix à 1R. Si la baisse (ou la hausse) continue, on en profite jusqu'au bout. Durée maximale portée à 72 h.
- **Ne rien faire est normal** : s'il n'y a ni signal exceptionnel ni gain à protéger, il n'agit pas.
- Il exécute aussi les ordres en attente posés par le comité.

Ce qui ne change JAMAIS : la perte maximale d'un trade reste fixée à l'entrée. On laisse courir les gains, jamais les pertes : on ne recule pas un stop-loss, on ne « tient » pas une position perdante en espérant qu'elle revienne.

À chaque réunion, le comité commence par lire `actions_trader_de_garde` dans le brief et donne son avis : l'action était-elle bonne ? On garde ou on corrige ? Ça fait partie du compte rendu.

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


## Trader de garde (règles automatiques, toutes les 5 minutes)
- **Entrée seule sur cassure fraîche (BRK-1)** : score ≥ 70, rapport gain/risque net ≥ 1,5, aucune alerte, et le prix n'a pas couru de plus de 0,5 ATR depuis le signal. Risque 0,5 %. Maximum 2 entrées seules par jour. Le comité contrôle ces entrées à la réunion suivante.
- **Sortie rapide** : une position BRK-1 qui revient de 1 ATR contre nous dans les 3 h est fermée tout de suite (la cassure a échoué), sans attendre le stop.
- Le comité ne doit pas entrer sur une cassure vieille de plus de 30 à 45 minutes, surtout après plus de 5 % de mouvement sur 24 h.

## Chasseur de mouvements (agent automatique + rôle au comité)
- **Le moteur le fait seul, toutes les 5 minutes** : il scrute toutes les cryptos en euros de Kraken (environ 460) et les actions xStocks, hors de notre liste de départ. Il repère celles qui bougent fort (±5 % sur la journée pour une crypto, ±2,5 % pour une action, ±3 % si on en parle sur CoinGecko), vérifie le volume et le spread, puis cherche une impulsion sur les bougies de 5 minutes (volume x3). S'il y en a une, il **ajoute l'actif à l'univers** (6 par jour au maximum, catégorie Emergent) et le **spécialiste entre tout de suite** dans le sens du mouvement, sans attendre le comité.
- **Sortie rapide** : moitié encaissée à +1R (stop au prix d'entrée pour le reste), fermeture si l'impulsion s'éteint en 30 min sans gain, durée maximale 2 h.
- **Budget** : les entrées automatiques comptent dans le budget memecoins (risque 0,5 % par trade, 3 entrées par jour, 2 positions, perte du jour limitée à 1,5 %).
- **Au comité**, le chasseur lit le bloc `chasseur_de_mouvements` du brief. Il signale les mouvements en cours, les actifs ajoutés tout seuls et ce dont on parle (CoinGecko, actualités, réseaux sociaux relayés par la presse). Quand une crypto ou une action est évoquée dans l'actualité ou par Tom, il la **fait ajouter tout de suite** avec l'action `ajouter_actif` (raison + source), puis le spécialiste surveille l'impulsion. Il ne se fie jamais à une rumeur seule : il lui faut un volume réel.
- Les actifs ajoutés automatiquement disparaissent de l'univers après 3 jours s'ils ne sont pas utilisés.
- **Réseaux sociaux (gratuit, sans clé)** : le moteur lit toutes les 15 minutes Reddit (ApeWisdom : tickers dont les mentions ont au moins doublé en 24 h) et StockTwits (symboles tendance). Le résultat est dans `buzz_reseaux_sociaux` du brief. C'est un indice, jamais une preuve : on n'entre que si le prix et le volume confirment. Pour les actifs hors univers, le seuil de détection baisse (3 % au lieu de 5 %).

## Esprit critique face aux sources (règle de Tom, 14 nov)

Les actus, vidéos, influenceurs, buzz Reddit/StockTwits et tendances CoinGecko sont des **pistes**, jamais des ordres.

1. **Source seule = pas de trade.** Il faut une confirmation dans le prix : volume, cassure, structure. Si le prix n'a pas bougé, l'info est peut-être déjà passée.
2. **Se demander qui parle et pourquoi.** Un influenceur peut avoir acheté avant, vendre une formation ou pousser un token. Un média peut titrer pour le clic. Noter l'intérêt possible de la source.
3. **Chercher l'avis contraire.** Avant d'entrer sur une idée venue des réseaux, un membre du comité joue l'avocat du diable : qu'est-ce qui prouve que c'est déjà trop tard, ou faux ?
4. **Méfiance maximale sur le buzz.** Beaucoup de mentions d'un coup sur un memecoin déjà monté de +20 % = souvent la fin du mouvement (pump and dump). Pas d'entrée tardive.
5. **Séparer fait, interprétation, rumeur.** Écrire lequel c'est dans chaque décision.
6. **Pas de consensus mou.** Si tout le comité est d'accord trop vite, le risk manager doit chercher une raison de refuser. Un désaccord argumenté vaut mieux qu'un oui rapide.
7. **Ne pas suivre Tom aveuglément non plus.** Si une demande de Tom paraît risquée, le comité le dit et explique, puis exécute si Tom confirme.
8. **Ne pas intervenir est une décision valable.** « Pas de trade, source douteuse » est une bonne réponse.

## Actifs exclus par Tom
La liste `exclusions` de config.json est interdite en nouvelle entrée, pour le comité comme pour le trader de garde et le moteur. Actuellement : NEAR (14 nov, « il sert à rien »). Ne pas le proposer.
