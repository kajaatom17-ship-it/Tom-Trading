"""Brief de marche pour le comite d'agents : python engine/brief.py
Prix Kraken frais + etat du portefeuille + signaux du scanner + sentiment.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import timedelta
from core import config, equity, iso, load, now_utc, paris_day, parse_iso, rp, tickers, unrealized


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
            "max_entrees_jour": cfg["risque"]["max_entrees_par_jour"],
            "entrees_memecoin_aujourdhui": st.get("entrees_meme_par_jour", {}).get(paris_day(), 0),
            "max_entrees_memecoin_jour": cfg.get("memecoins", {}).get("max_entrees_par_jour", 1), "coupe_circuit": st["coupe_circuit"],
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
    cal = load("calendrier.json", [])
    now = now_utc(); proches = []
    for e in cal:
        dt = (parse_iso(e["quand_utc"]) - now).total_seconds() / 60
        if -180 <= dt <= 48 * 60:
            proches.append({**e, "dans_minutes": round(dt),
                            "statut": "A PREPARER (ordres jumeaux avant l'heure)" if 0 < dt <= 120 and e.get("impact") == "haut"
                            else "vient de sortir : décrypter, ne pas courir" if dt <= 0 else "à venir"})
    out["calendrier_annonces"] = {"evenements": proches, "dernier_ajout_ou_vide": not cal,
                                  "note": "Si vide ou périmé : chercher sur le web les annonces à fort impact des 48 h et les déposer (action agenda)."}
    focus = set(cfg.get("focus", {}).get("categories_prioritaires", []))
    cat = {a["sym"]: a["cat"] for a in cfg["univers"]}
    for c in out["scanner"]["candidats"]:
        c["priorite"] = "prioritaire" if cat.get(c["sym"]) in focus else "secondaire"
    out["scanner"]["candidats"].sort(key=lambda c: c["priorite"] != "prioritaire")
    memes = [a["sym"] for a in cfg["univers"] if a["cat"] == "Meme"]
    out["memecoins"] = [{"sym": s, "prix": tk[s]["last"], "chg_24h_pct": tk[s]["chg_pct"], "spread_pct": tk[s]["spread_pct"],
                         "vol_24h_eur": round(tk[s]["vol_eur"]), "indicateurs_15m": sig.get("indicateurs", {}).get(s)}
                        for s in memes if s in tk]
    ch = load("chasseur.json", {})
    out["chasseur_de_mouvements"] = {"t": ch.get("t"), "nb_actifs_analyses": ch.get("nb_analyses"), "tendance_reseaux": ch.get("tendance"), "buzz_reseaux_sociaux": ch.get("buzz_reseaux"),
                                     "candidats": ch.get("candidats", [])[:8], "ajoutes_automatiquement": ch.get("ajoutes", []),
                                     "note": "Cryptos et actions Kraken hors univers qui bougent beaucoup. Ceux avec une impulsion sont ajoutés et traités seuls par le moteur. Pour en ajouter un dont on parle (réseaux, actualité), utiliser l'action ajouter_actif."}
    out["derniers_trades"] = load("trades.json", [])[-5:]
    out["dernieres_decisions"] = [{"id": d["id"], "action": d.get("action"), "sym": d.get("sym"),
                                   "synthese": d.get("synthese"), "resultat": d.get("resultat", {}).get("statut")}
                                  for d in load("decisions.json", [])[-5:]]
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
