# Strategy Lab — diagnostic du 16 novembre 2026

Tests sur l'historique réel Kraken (API publique), avec les vrais frais Kraken Pro palier 1 :
cryptos 0,40 % limite / 0,80 % marché, actions xStocks 0 % / 0,08 %, glissement par niveau de liquidité, coût du short 0,02 % par 4 h.
Argent fictif. Un test sur le passé ne garantit rien pour la suite.

## 1. Constat sur les trades réels (15 trades, 13 au 16 nov)

| | Montant |
|---|---|
| Gain brut avant frais | +3,8 € |
| Frais | 9,5 € |
| Résultat net | -5,7 € |

## 2. Les anciennes stratégies rejouées (TPB-1 et BRK-1, bougies 15 min, 7 jours, environ 1 000 trades)

| Classe | Résultat moyen sans frais | Résultat moyen avec frais |
|---|---|---|
| Cryptos | +0,01R (-0,08 %) | -1,1R (-1,6 %) |
| Memecoins | -0,02R | -1,1R (-1,6 %) |
| Actions | -0,14R | -0,3R (-0,35 %) |

Lecture : les signaux n'ont pas d'avantage, même gratuits. Les frais transforment un jeu nul en jeu perdant.
Changer l'objectif (2R, 5R), le score minimum (75), le volume des cassures (x3) ou passer en ordre limite ne rend aucune variante positive.

Portefeuille de 500 € rejoué avec tous ces signaux : -186 € en 25 jours (bougies 1 h), -307 € en 100 jours (bougies 4 h).

## 3. Autres familles testées, toutes négatives après frais

| Famille | Échantillon | Résultat moyen net par trade |
|---|---|---|
| Impulsions 5 min (MOM-1 : 2,5 % en 3 bougies, volume x3) | 58 | -0,9 % (cryptos), -1,4 % (memecoins) |
| Impulsions de 4 % | 19 | -1,7 % |
| Contre-impulsion (parier sur le retour) | 61 | -2,2 à -2,6 % |
| Cassure de canal journalière 20 ou 55 jours, achat et vente | 355 à 835 | -0,2R à -0,4R |
| Cassure de canal journalière, achat seul | 205 à 493 | environ 0 (actions), -0,05R (cryptos) |
| Cassure de canal 4 h | 344 à 1 540 | -0,6R à +0,3R, instable (achat seul sur cryptos : positif en première moitié, négatif en seconde) |
| Retour à la moyenne journalier (RSI 2 jours) | 54 à 144 par classe | -0,1 % (actions), +0,2 % (cryptos, non stable), -2,3 % (memecoins) |
| Cassure d'ouverture actions (30 premières minutes) | 168 | -0,24 % |

## 4. Ce qui change tout : le sens de la tendance de fond

Sur le dernier mois (BTC -19 %, Nvidia -25 %), en bougies 1 h :

| | Réussite | Résultat moyen net |
|---|---|---|
| Achats cryptos | 9 % | -1,4R |
| Ventes à découvert cryptos | 42 % | -0,05R |
| Achats actions | 19 % | -0,6R |
| Ventes à découvert actions | 28 % | -0,2R |

Trader contre la tendance de fond perd presque à chaque fois.

## 5. La configuration retenue : SWG-1

Même signal de repli dans la tendance, mais :
- bougies 1 h au lieu de 15 min ;
- seulement dans le sens de la variation sur 20 jours de l'actif ET de son marché (BTC ou QQQ) ;
- stop deux fois plus large ;
- objectif 3R, moitié encaissée puis stop suiveur ;
- tenue jusqu'à 8 jours ;
- pas de stop remonté au prix d'entrée.

Signal seul (une position à la fois par actif, entrée limite) :

| Bougies | Classe | Trades | Réussite | Résultat moyen net | Facteur de profit | Par tiers de la période |
|---|---|---|---|---|---|---|
| 1 h (30 jours) | Cryptos | 94 | 55 % | +0,69R (+2,9 %) | 2,6 | +0,68 / +0,86 / +0,54 |
| 1 h | Actions | 67 | 39 % | +0,18R (+0,75 %) | 1,3 | +0,38 / +0,02 / +0,13 |
| 1 h | Memecoins | 60 | 48 % | +0,23R (+0,8 %) | 1,4 | -0,45 / +0,79 / +0,35 |
| 4 h (120 jours) | Cryptos | 108 | 38 % | +0,13R (+2,3 %) | 1,2 | -0,30 / -0,15 / +0,82 |
| 4 h | Actions | 90 | 33 % | -0,12R | 0,8 | -0,49 / -0,25 / +0,37 |
| 4 h | Memecoins | 72 | 42 % | +0,17R (+3,6 %) | 1,25 | -0,52 / +0,02 / +1,01 |

Portefeuille de 500 € rejoué avec les limites (2 positions crypto, 3 actions, risque 1 %, entrée au marché) :

| Variante | Période | Trades | Réussite | Résultat | Pire baisse |
|---|---|---|---|---|---|
| Ancien système, tous signaux | 25 jours | 229 | 22 % | -185,87 € | 37 % |
| SWG-1 sans stop au prix d'entrée | 23 jours | 30 | 50 % | +54,26 € | 3,8 % |
| SWG-1 avec stop au prix d'entrée à +1R | 23 jours | 47 | 30 % | -1,52 € | 7,3 % |
| SWG-1 sans stop au prix d'entrée, bougies 4 h | 99 jours | 32 | 41 % | +22,65 € | 9,7 % |
| SWG-1 avec stop au prix d'entrée, bougies 4 h | 96 jours | 41 | 37 % | +33,98 € | 4,4 % |

## 6. Limites à ne pas oublier

- Petit échantillon : 30 à 40 trades au niveau portefeuille. Un seul mois en bougies 1 h, et ce mois était très baissier : presque tout le gain vient des ventes à découvert.
- Les positions crypto bougent ensemble : 94 trades ne sont pas 94 paris indépendants.
- Sur 120 jours en bougies 4 h, le résultat est positif mais faible et irrégulier (premier tiers négatif).
- Plusieurs variantes ont été essayées : la meilleure paraît toujours meilleure qu'elle ne l'est vraiment.
- En argent réel, la vente à découvert passe par la marge Kraken. Pour un compte en France, l'accès n'est pas garanti : à vérifier avant tout passage en réel.
- Règle de décision : on juge SWG-1 après 30 trades réels. Si le résultat net est négatif à ce moment, on arrête et on revient au Lab.

## 7. Refaire les tests

    cd lab
    python3 fetch.py && python3 fetch2.py   # historique Kraken (quelques minutes)
    python3 sig.py && python3 sig4h.py      # rejoue le scanner
    python3 sim.py && python3 var.py        # anciennes stratégies et variantes
    python3 trend.py && python3 alt.py      # autres familles
    python3 final.py                        # SWG-1 et portefeuille
