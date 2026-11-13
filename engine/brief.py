"""Brief de marche pour le comite d'agents : python engine/brief.py
Prix Kraken frais + etat du portefeuille + signaux du scanner + sentiment.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import config, equity, iso, load, paris_day, rp, tickers, unrealized


def main():
    cfg = config()
    st = load("state.json", None)
    sig = load("signals.json", {})
    mk = load("market.json", {})
    tk = tickers(cfg["univers"])
    prices = {s: t["last"] for s, t in tk.items()}
    out = {"genere_le": iso(), "source_prix": "Kraken API publique (Ticker), EUR"}
    if st:
        eq = equity(st, prices)
        out["portefeuille"] = {
            "equity": round(eq, 2), "cash": round(st["cash"], 2), "capital_initial": st["capital_initial"],
            "perf_pct": round((eq / st["capital_initial"] - 1) * 100, 2), "pnl_realise": round(st["pnl_realise"], 2),
            "entrees_aujourdhui": st["entrees_par_jour"].get(paris_day(), 0),
            "max_entrees_jour": cfg["risque"]["max_entrees_par_jour"], "coupe_circuit": st["coupe_circuit"],
            "positions": [{"id": p["id"], "sym": p["sym"], "side": p["side"], "entry": p["entry"],
                           "prix": prices.get(p["sym"]), "stop": rp(p["stop"]), "tp": rp(p["tp"]),
                           "pnl_latent": round(unrealized(p, prices.get(p["sym"], p["entry"])), 2),
                           "ouvert_le": p["ouvert_le"], "strategie": p["strategie"]} for p in st["positions"]],
        }
    out["actions_trader_de_garde"] = [e for e in load("activite.json", []) if e.get("agent") == "Trader de garde"][-10:]
    out["urgences"] = load("status.json", {}).get("urgences", [])
    if st:
        out["ordres_attente"] = st.get("ordres_attente", [])
    out["scanner"] = {"t": sig.get("t"), "tendance_btc_1h": sig.get("btc_trend_1h"),
                      "candidats": sig.get("candidats", [])[:10]}
    out["sentiment"] = mk.get("sentiment")
    movers = sorted(tk.items(), key=lambda kv: -abs(kv[1]["chg_pct"]))[:8]
    out["plus_fortes_variations_24h"] = [{"sym": s, "chg_pct": t["chg_pct"], "prix": t["last"], "vol_eur": round(t["vol_eur"])} for s, t in movers]
    out["indicateurs_15m"] = sig.get("indicateurs", {})
    v = load("veille.json", {})
    out["veille"] = {"t": v.get("t"), "alertes_prix": v.get("alertes", [])[:15],
                     "actus_importantes": [x for x in v.get("actus", []) if x.get("score", 0) >= 3][:25]}
    out["derniers_trades"] = load("trades.json", [])[-5:]
    out["dernieres_decisions"] = [{"id": d["id"], "action": d.get("action"), "sym": d.get("sym"),
                                   "synthese": d.get("synthese"), "resultat": d.get("resultat", {}).get("statut")}
                                  for d in load("decisions.json", [])[-5:]]
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
