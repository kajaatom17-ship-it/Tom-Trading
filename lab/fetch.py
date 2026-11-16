import sys, json, time, os
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import core
cfg = core.config()
out = {}
for iv in (15, 60):
    for a in cfg["univers"]:
        sym = a["sym"]; pair = core.pair_of(cfg, sym)
        try:
            cs = core.ohlc(pair, iv)
            out[f"{sym}|{iv}"] = cs
        except Exception as e:
            print("ERR", sym, iv, str(e)[:80])
        time.sleep(0.35)
json.dump(out, open("candles.json", "w"))
print(len(out), "séries")
for k in ("BTC|15", "NVDA|15", "GLD|60", "SPY|15"):
    c = out.get(k); print(k, len(c) if c else None, c[0]["t"] if c else "", c[-1] if c else "")
