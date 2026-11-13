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
check("position fermee a l'objectif", len(st["positions"]) == 0 and tr and tr[-1]["raison_sortie"] == "objectif atteint")
exp_net = p["qty"] * 109 * (1 - 0.0025) - p["notionnel"] * 1.004
check("PnL net = gain - frais entree 0,40 % - frais sortie 0,25 %", abs(tr[-1]["pnl_net"] - round(exp_net, 2)) < 0.011,
      f"pnl {tr[-1]['pnl_net']} vs {exp_net:.2f}")
check("cash final coherent", abs(st["cash"] - (500 + exp_net)) < 0.01, f"cash {st['cash']:.2f}")

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

print("\n" + ("TOUS LES TESTS PASSENT" if not fails else f"{fails} ECHEC(S)"))
sys.exit(1 if fails else 0)
