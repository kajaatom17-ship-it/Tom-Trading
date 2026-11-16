"""Étape 1 : rejoue le scanner du moteur sur l'historique et enregistre tous les signaux bruts."""
import sys, json
from multiprocessing import Pool
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import core, strategy
cfg = core.config()
C = json.load(open("candles.json"))
W = 480

def btc_trends(iv):
    cs = C[f"BTC|{iv}"]; out = {}
    for i in range(121, len(cs) - 1):
        ind = strategy.analyse(cs[max(0, i - W):i + 2])
        if ind: out[cs[i]["t"]] = ind["trend_1h"]
    return out

def work(key):
    sym, iv = key.split("|"); cs = C[key]; res = []
    bt = BT[iv]
    for i in range(121, len(cs) - 1):
        ind = strategy.analyse(cs[max(0, i - W):i + 2])
        if not ind: continue
        for s in strategy.signals(cfg, sym, ind, bt.get(cs[i]["t"], "neutre")):
            res.append({"sym": sym, "iv": int(iv), "i": i, "t": cs[i]["t"], "strat": s["strategie"], "side": s["side"], "px": ind["close"],
                        "atr": ind["atr"], "stop": s["stop"], "score": s["score"], "alertes": s["alertes"], "vol_ratio": ind["vol_ratio"],
                        "rsi": ind["rsi"], "trend": ind["trend_1h"], "var24": ind["var_24h_pct"], "atr_pct": ind["atr_pct"]})
    return res

BT = {"15": btc_trends(15), "60": btc_trends(60)}
if __name__ == "__main__":
    with Pool(4) as p:
        allr = [x for r in p.map(work, list(C.keys())) for x in r]
    json.dump(allr, open("signals.json", "w"))
    import collections
    print(len(allr), collections.Counter((x["iv"], x["strat"]) for x in allr))
