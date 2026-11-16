import sys, json, time
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import core
cfg = core.config(); out = {}
for a in cfg["univers"]:
    sym = a["sym"]; pair = core.pair_of(cfg, sym); stock = a.get("classe") == "action"
    for iv in ([30, 240, 1440] if stock else [5, 240, 1440]):
        try: out[f"{sym}|{iv}"] = core.ohlc(pair, iv)
        except Exception as e: print("ERR", sym, iv, str(e)[:60])
        time.sleep(0.3)
json.dump(out, open("candles2.json", "w"))
import collections
print(len(out)); print({k: len(v) for k, v in out.items() if k.split("|")[0] in ("BTC", "NVDA", "GLD", "PEPE", "HYPE", "CRCL")})
