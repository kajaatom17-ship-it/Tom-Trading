"""Tests de bout en bout du moteur, avec des prix simules (aucun appel reseau).
Lance : python tests/test_engine.py
Verifie : ouverture, frais, take-profit, stop-loss short, refus Risk Manager, refus garde-fou.
"""
import json
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp()
os.environ["TD_DATA"] = os.path.join(TMP, "data")
os.environ["TD_ARCHIVE"] = os.path.join(TMP, "archive")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))

import core  # noqa: E402
import tick  # noqa: E402

PRICES = {}
CANDLES = {}


def fake_tickers(universe):
    out = {}
    for a in universe:
        px = PRICES.get(a["sym"], 100.0)
        out[a["sym"]] = {"bid": px * 0.9999, "ask": px * 1.0001, "last": px, "open": px, "high": px, "low": px,
                         "vol_eur": 5e6, "spread_pct": 0.02, "chg_pct": 0}
    return out


def fake_ohlc(pair, interval, since=None):
    return CANDLES.get(pair, [])


tick.tickers = fake_tickers
tick.ohlc = fake_ohlc
tick.scan = lambda cfg: {"t": core.iso(), "btc_trend_1h": "neutre", "candidats": [], "indicateurs": {}}
tick.sentiment = lambda m: {}
tick.time.sleep = lambda s: None


def run():
    sys.argv = ["tick.py"]
    assert tick.main() == 0


def drop(decision):
    os.makedirs(core.INBOX, exist_ok=True)
    with open(os.path.join(core.INBOX, decision["id"] + ".json"), "w") as f:
        json.dump(decision, f)


AGENTS_OK = {"analyste_technique": {"avis": "test"}, "analyste_macro": {"avis": "test"},
             "analyste_sentiment": {"avis": "test"}, "trader": {"avis": "test"},
             "risk_manager": {"verdict": "valide", "motif": "test"}}

cfg = core.config()
fails = 0


def check(name, cond, detail=""):
    global fails
    print(("OK   " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += 0 if cond else 1


# 1. initialisation
run()
st = core.load("state.json", None)
check("portefeuille initial a 500 EUR", st["cash"] == 500.0)

# 2. ouverture long SOL : entree 100, stop 97, objectif 109
PRICES["SOL"] = 100.0
drop({"id": "T1", "action": "open", "sym": "SOL", "side": "long", "entry_ref": 100, "atr": 1.0,
      "stop": 97, "tp": 109, "strategie": "TEST", "agents": AGENTS_OK, "synthese": "test"})
run()
st = core.load("state.json", None)
p = st["positions"][0] if st["positions"] else None
check("position SOL ouverte", p is not None)
fill = 100 * 1.0001 * 1.0005
risk_target = 500 * 0.01
per_unit = (fill - 97) + 0.004 * (fill + 97)
qty_expected = min(risk_target / per_unit, 500 * 0.30 / fill)
check("quantite = risque 1 % / distance au stop", abs(p["qty"] - qty_expected) < 1e-9, f"qty {p['qty']:.4f}")
check("cash = 500 - notionnel - frais 0,40 %", abs(st["cash"] - (500 - p["notionnel"] * 1.004)) < 1e-6, f"cash {st['cash']:.2f}")

# 3. une bougie 1 min touche l'objectif -> cloture maker
t0 = int(time.time()) - 120
CANDLES["SOLEUR"] = [{"t": t0, "o": 100, "h": 109.5, "l": 99.5, "c": 109.2, "v": 1},
                     {"t": t0 + 60, "o": 109.2, "h": 109.3, "l": 109, "c": 109.1, "v": 1}]
# la bougie doit etre posterieure a l'ouverture
st["positions"][0]["verifie_jusqu_a"] = core.iso(core.now_utc().fromtimestamp(t0 - 1, tz=core.now_utc().tzinfo))
core.save("state.json", st)
PRICES["SOL"] = 109.1
run()
st = core.load("state.json", None)
tr = core.load("trades.json", [])
check("objectif : moitié encaissée, le reste court", len(st["positions"]) == 1 and st["positions"][0].get("runner")
      and tr and tr[-1]["raison_sortie"].startswith("objectif atteint"))
exp_net = 0.5 * (p["qty"] * 109 * (1 - 0.0025) - p["notionnel"] * 1.004)
check("PnL net de la moitié = gain - frais entrée - frais sortie", abs(tr[-1]["pnl_net"] - round(exp_net, 2)) < 0.011,
      f"pnl {tr[-1]['pnl_net']} vs {exp_net:.2f}")
run_p = st["positions"][0]
check("stop du reste verrouille du profit", run_p["stop"] > p["entry"], f"stop {run_p['stop']}")
# le prix continue a monter puis redescend : le stop suiveur ferme avec un gain
t0b = int(time.time()) - 120
CANDLES["SOLEUR"] = [{"t": t0b, "o": 109, "h": 115, "l": 108.9, "c": 114.5, "v": 1},
                     {"t": t0b + 60, "o": 114.5, "h": 114.6, "l": 110, "c": 110.5, "v": 1},
                     {"t": t0b + 120, "o": 110.5, "h": 110.6, "l": 110.4, "c": 110.5, "v": 1}]
st["positions"][0]["verifie_jusqu_a"] = core.iso(core.now_utc().fromtimestamp(t0b - 1, tz=core.now_utc().tzinfo))
core.save("state.json", st); PRICES["SOL"] = 110.5
run()
st = core.load("state.json", None); tr = core.load("trades.json", [])
check("stop suiveur ferme le reste avec un gain", not st["positions"] and tr[-1]["pnl_net"] > 0 and "suiveur" in tr[-1]["raison_sortie"],
      f"{tr[-1]['raison_sortie']} {tr[-1]['pnl_net']}")

# 4. short ETH touche par le stop
PRICES["ETH"] = 3000.0
drop({"id": "T2", "action": "open", "sym": "ETH", "side": "short", "entry_ref": 3000, "atr": 20,
      "stop": 3060, "tp": 2820, "strategie": "TEST", "agents": AGENTS_OK, "synthese": "test"})
run()
st = core.load("state.json", None)
ps = st["positions"][0]
cash_before_close = st["cash"]
t1 = int(time.time()) - 120
CANDLES["ETHEUR"] = [{"t": t1, "o": 3010, "h": 3075, "l": 3005, "c": 3070, "v": 1},
                     {"t": t1 + 60, "o": 3070, "h": 3071, "l": 3065, "c": 3066, "v": 1}]
st["positions"][0]["verifie_jusqu_a"] = core.iso(core.now_utc().fromtimestamp(t1 - 1, tz=core.now_utc().tzinfo))
core.save("state.json", st)
run()
st = core.load("state.json", None)
tr = core.load("trades.json", [])
check("short ferme au stop-loss", tr[-1]["sym"] == "ETH" and tr[-1]["raison_sortie"] == "stop-loss")
check("perte du short proche du risque prevu (1 R)", -1.15 < tr[-1]["r_multiple"] < -0.9, f"R {tr[-1]['r_multiple']}")

# 5. refus du Risk Manager IA -> rien n'est execute
bad = dict(AGENTS_OK, risk_manager={"verdict": "refuse", "motif": "trop de volatilite"})
drop({"id": "T3", "action": "open", "sym": "SOL", "side": "long", "entry_ref": 109.1, "atr": 1,
      "stop": 105, "tp": 122, "strategie": "TEST", "agents": bad, "synthese": "test"})
run()
d = core.load("decisions.json", [])[-1]
check("ordre refuse par le Risk Manager IA non execute", d["resultat"]["statut"] == "refuse par le Risk Manager IA"
      and not core.load("state.json", None)["positions"])

# 6. garde-fou code : RR trop faible
drop({"id": "T4", "action": "open", "sym": "SOL", "side": "long", "entry_ref": 109.1, "atr": 1,
      "stop": 107, "tp": 110.5, "strategie": "TEST", "agents": AGENTS_OK, "synthese": "test"})
run()
d = core.load("decisions.json", [])[-1]
check("garde-fou bloque un RR insuffisant", d["resultat"]["statut"] == "bloque par les garde-fous du code",
      "; ".join(d["resultat"].get("motifs", [])))

# 7. limite de 3 entrees par jour
st = core.load("state.json", None)
st["entrees_par_jour"][core.paris_day()] = 3
core.save("state.json", st)
drop({"id": "T5", "action": "open", "sym": "SOL", "side": "long", "entry_ref": 109.1, "atr": 1,
      "stop": 105, "tp": 122, "strategie": "TEST", "agents": AGENTS_OK, "synthese": "test"})
run()
d = core.load("decisions.json", [])[-1]
check("limite de 3 entrees par jour respectee", any("entrées aujourd'hui" in m for m in d["resultat"].get("motifs", [])))

# 8. decision "ne rien faire" journalisee
drop({"id": "T6", "action": "none", "agents": AGENTS_OK, "synthese": "Marche sans signal propre."})
run()
check("decision 'aucune action' journalisee", core.load("decisions.json", [])[-1]["resultat"]["statut"] == "aucune action")

# 9. OPP-1 : sans catalyseur -> refus ; avec -> execute avec risque reduit 0,5 %
st = core.load("state.json", None); st["entrees_par_jour"] = {}; core.save("state.json", st)
PRICES["NVDA"] = 150.0
drop({"id": "T7", "action": "open", "sym": "NVDA", "side": "short", "entry_ref": 150, "atr": 1,
      "stop": 153, "tp": 140, "strategie": "OPP-1", "agents": AGENTS_OK, "synthese": "test"})
run()
d = core.load("decisions.json", [])[-1]
check("OPP-1 sans catalyseur refusé", any("catalyseur" in m for m in d["resultat"].get("motifs", [])))
drop({"id": "T8", "action": "open", "sym": "NVDA", "side": "short", "entry_ref": 150, "atr": 1,
      "stop": 153, "tp": 135, "strategie": "OPP-1", "agents": AGENTS_OK, "synthese": "test",
      "catalyseur": {"evenement": "test", "source": "test", "date": "2026-11-13"}})
run()
d = core.load("decisions.json", [])[-1]
eq = core.load("status.json", {})["equity"]
check("OPP-1 avec catalyseur exécuté", d["resultat"]["statut"] == "execute", str(d["resultat"]))
check("OPP-1 risque limité à 0,5 % du capital", d["resultat"].get("risque_eur", 99) <= 0.005 * 507 + 0.01, str(d["resultat"].get("risque_eur")))

# 10. ordre en attente : placé, pas déclenché, puis déclenché quand le prix passe le niveau
st = core.load("state.json", None); st["positions"] = []; st["entrees_par_jour"] = {}; st["cash"] = 500.0; core.save("state.json", st)
PRICES["SOL"] = 100.0
drop({"id": "T9", "action": "pending", "sym": "SOL", "side": "short", "type_ordre": "stop", "declencheur": 98,
      "stop": 101, "tp": 89, "expire_h": 4, "strategie": "BRK-1", "agents": AGENTS_OK, "synthese": "test"})
run()
st = core.load("state.json", None)
check("ordre en attente enregistré", len(st.get("ordres_attente", [])) == 1 and not st["positions"])
PRICES["SOL"] = 97.9
run()
st = core.load("state.json", None)
check("ordre déclenché quand le prix passe sous 98", len(st["positions"]) == 1 and st["positions"][0]["side"] == "short"
      and not st.get("ordres_attente"), str(st.get("ordres_attente")))
check("urgences calculées", "urgences" in core.load("status.json", {}))

# 11. trader de garde : stop au prix d'entrée à +1R
st = core.load("state.json", None); p = st["positions"][0]  # short SOL entré vers 97,9, stop 101
risk = p["stop_initial"] - p["entry"]
PRICES["SOL"] = p["entry"] - 1.2 * risk
run()
st = core.load("state.json", None); p2 = st["positions"][0]
check("trader de garde : stop au prix d'entrée à +1R", p2["stop"] < p["entry"] and p2["stop"] > p["entry"] * 0.99, f"stop {p2['stop']} entrée {p['entry']}")

# 12. ordres jumeaux autour d'une annonce : le premier déclenché annule l'autre, glissement d'annonce appliqué
st = core.load("state.json", None); st["positions"] = []; st["entrees_par_jour"] = {}; st["cash"] = 500.0
st["ordres_attente"] = []; core.save("state.json", st)
cfg = core.config(); pair = core.pair_of(cfg, "ETH")
PRICES["ETH"] = 100.0
now = int(time.time()); t0 = now - 600
for k, (grp, side, trig, stop, tp) in enumerate([("A1", "long", 101.0, 98.9, 107.3), ("A1", "short", 99.0, 101.1, 91.5)]):
    drop({"id": f"TJ{k}", "action": "pending", "sym": "ETH", "side": side, "type_ordre": "stop", "declencheur": trig,
          "stop": stop, "tp": tp, "expire_h": 2, "strategie": "BRK-1", "groupe": grp, "evenement": "CPI test",
          "agents": AGENTS_OK, "synthese": "test"})
CANDLES[pair] = []
run()
st = core.load("state.json", None)
check("deux ordres jumeaux posés", len(st.get("ordres_attente", [])) == 2 and st["ordres_attente"][0]["groupe"] == "A1")
st = core.load("state.json", None)
for o in st["ordres_attente"]:
    o["verifie_le"] = core.iso(core.now_utc() - __import__("datetime").timedelta(minutes=10))  # posés il y a 10 min
core.save("state.json", st)
base = (now - 300) // 60 * 60
CANDLES[pair] = [
    {"t": base, "o": 100.0, "h": 100.4, "l": 99.8, "c": 100.2, "v": 1},
    {"t": base + 60, "o": 100.2, "h": 101.8, "l": 100.1, "c": 101.6, "v": 9},   # casse à la hausse
    {"t": base + 120, "o": 101.6, "h": 101.7, "l": 98.0, "c": 98.5, "v": 9},    # puis retournement violent
    {"t": base + 180, "o": 98.5, "h": 98.9, "l": 98.2, "c": 98.6, "v": 3},
    {"t": base + 240, "o": 98.6, "h": 98.7, "l": 98.5, "c": 98.6, "v": 1},      # bougie en cours
]
PRICES["ETH"] = 98.6
run()
st = core.load("state.json", None)
act = core.load("activite.json", [])
check("jumeau annulé quand le premier se déclenche", not st.get("ordres_attente"), str(st.get("ordres_attente")))
tj = [p for p in st["positions"] if str(p["decision_id"]).startswith("TJ")] + [x for x in core.load("trades.json", []) if str(x.get("decision_id", "")).startswith("TJ")]
check("un seul ordre jumeau est devenu position", len(tj) == 1, str(tj))
check("annulation journalisée", any("jumeau" in json.dumps(e, ensure_ascii=False) for e in act))
check("entrée à la hausse avec glissement d'annonce (> 101,0)", tj and tj[0]["side"] == "long" and tj[0]["entry"] > 101.0, str(tj and (tj[0]["side"], tj[0]["entry"])))
run()  # passage suivant : les minutes après le déclenchement sont rejouées
closed = [x for x in core.load("trades.json", []) if str(x.get("decision_id", "")).startswith("TJ")]
check("retournement brutal : stop touché sur les minutes rejouées", bool(closed) and closed[0]["raison_sortie"].startswith("stop"), str(closed))

# 13. agenda : ajout d'annonces, sans passer par les décisions
core.save("calendrier.json", [])
drop({"id": "AG1", "action": "agenda", "evenements": [{"titre": "CPI test", "quand_utc": core.iso(core.now_utc() + __import__("datetime").timedelta(minutes=50)),
                                                    "impact": "haut", "actifs": ["BTC"], "source": "test"}]})
run()
check("agenda enregistré", len(core.load("calendrier.json", [])) == 1)
check("urgence annonce < 2 h", any("Annonce" in u for u in core.load("status.json", {}).get("urgences", [])))
check("agenda pas dans les décisions", not any(d.get("id") == "AG1" for d in core.load("decisions.json", [])))

# 14. budget memecoins : risque réduit, 1 entrée par jour, ajout d'un actif émergent vérifié
st = core.load("state.json", None); st["positions"] = []; st["entrees_par_jour"] = {}; st["entrees_meme_par_jour"] = {}; st["cash"] = 500.0
st["ordres_attente"] = []; st["coupe_circuit"] = False; core.save("state.json", st)
core.save("trades.json", [])
PRICES["PEPE"] = 100.0
drop({"id": "M1", "action": "open", "sym": "PEPE", "side": "long", "stop": 97.0, "tp": 109.0, "entry_ref": 100.0, "strategie": "TPB-1",
      "agents": AGENTS_OK, "synthese": "test"})
run()
st = core.load("state.json", None); pm = [p for p in st["positions"] if p["sym"] == "PEPE"]
check("memecoin ouvert", len(pm) == 1, str(core.load("decisions.json", [])[-1].get("resultat")))
check("risque memecoin réduit (≤ 0,4 % du capital)", pm and pm[0]["risque_eur"] <= 0.004 * 505 + 0.05, str(pm and pm[0]["risque_eur"]))
check("mise memecoin plafonnée (≤ 6 % du capital)", pm and pm[0]["notionnel"] <= 0.06 * 505 + 0.5, str(pm and pm[0]["notionnel"]))
check("durée max memecoin ≤ 6 h", pm and pm[0]["duree_max_h"] <= 6, str(pm and pm[0]["duree_max_h"]))
drop({"id": "M2", "action": "open", "sym": "DOGE", "side": "long", "stop": 97.0, "tp": 109.0, "entry_ref": 100.0, "strategie": "TPB-1",
      "agents": AGENTS_OK, "synthese": "test"})
run()
d = core.load("decisions.json", [])[-1]
check("2e memecoin refusé (1 max)", d["id"] == "M2" and d["resultat"]["statut"] != "execute", str(d["resultat"]))
st = core.load("state.json", None); st["positions"] = []; core.save("state.json", st)
drop({"id": "M3", "action": "open", "sym": "WIF", "side": "long", "stop": 97.0, "tp": 109.0, "entry_ref": 100.0, "strategie": "TPB-1",
      "agents": AGENTS_OK, "synthese": "test"})
run()
d = core.load("decisions.json", [])[-1]
check("memecoin ne consomme pas les 3 entrées normales", core.load("state.json", None)["entrees_par_jour"].get(core.paris_day(), 0) == 0)
check("1 seule entrée memecoin par jour", d["id"] == "M3" and d["resultat"]["statut"] != "execute" and any("entrée memecoin" in m for m in d["resultat"].get("motifs", [])), str(d["resultat"]))

tick.kraken = lambda m, p=None: {"NEWEUR": {"altname": "NEWEUR", "quote": "ZEUR", "status": "online"}}
drop({"id": "AJ1", "action": "ajouter_actif", "sym": "NEW", "pair": "NEWEUR", "nom": "New Coin", "cat": "Emergent",
      "raison": "listing annoncé", "source": "https://exemple.test/annonce"})
drop({"id": "AJ2", "action": "ajouter_actif", "sym": "BTC", "pair": "XBTEUR", "raison": "x", "source": "y"})
run()
aj = core.load("univers_ajouts.json", [])
check("actif émergent ajouté après vérification Kraken", [a["sym"] for a in aj] == ["NEW"] and aj[0]["tier"] == "C", str(aj))
check("actif déjà présent refusé", "BTC" not in [a["sym"] for a in aj])
check("l'actif ajouté est dans la config fusionnée", any(a["sym"] == "NEW" for a in core.config()["univers"]))
check("config de l'interface mise à jour", any(a["sym"] == "NEW" for a in json.load(open(os.path.join(os.path.dirname(core.DATA), "config.json")))["univers"]))

# 15. objectif rapproché sur demande : seulement vers le prix, du côté du gain
st = core.load("state.json", None); st["positions"] = []; st["entrees_meme_par_jour"] = {}; st["entrees_par_jour"] = {}; core.save("state.json", st)
core.save("trades.json", [])
st = core.load("state.json", None); st["equity_debut_jour"] = {core.paris_day(): st["cash"]}; st["cash"] = 500.0; core.save("state.json", st)
PRICES["SOL"] = 100.0
drop({"id": "S1", "action": "open", "sym": "SOL", "side": "short", "stop": 104.0, "tp": 88.0, "entry_ref": 100.0, "strategie": "TPB-1", "agents": AGENTS_OK, "synthese": "test"})
run()
check("position SOL short ouverte pour le test", any(p["sym"] == "SOL" for p in core.load("state.json", None)["positions"]), str(core.load("decisions.json", [])[-1].get("resultat")))
PRICES["SOL"] = 97.0
drop({"id": "S2", "action": "set_target", "sym": "SOL", "tp": 80.0, "origine": "tom"})   # plus loin : refusé
drop({"id": "S3", "action": "set_target", "sym": "SOL", "tp": 96.9, "origine": "tom"})   # collé au prix : refusé
drop({"id": "S4", "action": "set_target", "sym": "SOL", "tp": 93.0, "origine": "tom"})   # plus proche, bon côté : accepté
run()
dec = {x["id"]: x["resultat"]["statut"] for x in core.load("decisions.json", []) if x["id"] in ("S2", "S3", "S4")}
check("objectif plus loin refusé", dec.get("S2") == "refuse", str(dec))
check("objectif collé au prix refusé", dec.get("S3") == "refuse", str(dec))
check("objectif rapproché accepté", dec.get("S4") == "execute", str(dec))
check("objectif mis à jour dans la position", [p["tp"] for p in core.load("state.json", None)["positions"] if p["sym"] == "SOL"] == [93.0])

print("\n" + ("TOUS LES TESTS PASSENT" if not fails else f"{fails} ECHEC(S)"))
sys.exit(1 if fails else 0)
