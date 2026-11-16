import sys, json
from multiprocessing import Pool
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import core, strategy
cfg = core.config(); C2 = json.load(open("candles2.json")); W = 480
def trends():
    cs = C2["BTC|240"]; out = {}
    for i in range(121, len(cs) - 1):
        ind = strategy.analyse(cs[max(0, i - W):i + 2])
        if ind: out[cs[i]["t"]] = ind["trend_1h"]
    return out
BT = trends()
def work(sym):
    cs = C2.get(f"{sym}|240"); res = []
    if not cs: return res
    for i in range(121, len(cs) - 1):
        ind = strategy.analyse(cs[max(0, i - W):i + 2])
        if not ind: continue
        for s in strategy.signals(cfg, sym, ind, BT.get(cs[i]["t"], "neutre")):
            res.append({"sym": sym, "iv": 240, "i": i, "t": cs[i]["t"], "strat": s["strategie"], "side": s["side"], "px": ind["close"], "atr": ind["atr"], "stop": s["stop"],
                        "score": s["score"], "alertes": s["alertes"], "vol_ratio": ind["vol_ratio"], "rsi": ind["rsi"], "trend": ind["trend_1h"], "var24": ind["var_24h_pct"], "atr_pct": ind["atr_pct"]})
    return res
if __name__ == "__main__":
    with Pool(4) as p: allr = [x for r in p.map(work, [a["sym"] for a in cfg["univers"]]) for x in r]
    S = json.load(open("signals.json")); S = [s for s in S if s["iv"] != 240] + allr
    json.dump(S, open("signals.json", "w"))
    C = json.load(open("candles.json")); C.update({k: v for k, v in C2.items() if k.endswith("|240")}); json.dump(C, open("candles.json", "w"))
    print(len(allr))
