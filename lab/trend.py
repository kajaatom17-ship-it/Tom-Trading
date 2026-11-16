"""Suivi de tendance (cassure de canal + stop suiveur ATR) en 4 h et en journalier, vrais frais + coût du short."""
import sys, json, collections, statistics as st
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import core
cfg = core.config(); C = json.load(open("candles2.json"))
ACT = {a["sym"] for a in cfg["univers"] if a.get("classe") == "action"}
MEME = {a["sym"] for a in cfg["univers"] if core.is_meme(cfg, a["sym"])}
def cls(sym): return "action" if sym in ACT else ("meme" if sym in MEME else "crypto")
ROLL = cfg["frais"]["rollover_short_pct_par_4h"] / 100

def bt(sym, iv, N, k, sides=("long", "short"), M=None, filt=None, maxbars=10**9):
    cs = C.get(f"{sym}|{iv}")
    if not cs or len(cs) < N + 40: return []
    cs = cs[:-1]; A = core.atr(cs, 20); mk, tk = core.fees(cfg, sym); tk /= 100
    sl = cfg["frais"]["slippage_pct_par_tier"][core.tier_of(cfg, sym)] / 100
    closes = [c["c"] for c in cs]; E200 = core.ema(closes, 100)
    out = []; pos = None
    for i in range(N + 21, len(cs) - 1):
        c = cs[i]
        if pos:
            d = pos["d"]
            pos["ext"] = max(pos["ext"], c["c"]) if d == 1 else min(pos["ext"], c["c"])
            trail = pos["ext"] - d * k * pos["atr"]
            stop = max(pos["stop"], trail) if d == 1 else min(pos["stop"], trail)
            hit = c["l"] <= pos["stop"] if d == 1 else c["h"] >= pos["stop"]
            chan = M and ((d == 1 and c["c"] < min(x["l"] for x in cs[i - M:i])) or (d == -1 and c["c"] > max(x["h"] for x in cs[i - M:i])))
            if hit or chan or i - pos["i"] >= maxbars:
                x = (min(pos["stop"], c["o"]) if d == 1 else max(pos["stop"], c["o"])) if hit else c["c"]
                x *= (1 - d * sl); e = pos["e"]
                gross = (x - e) * d / e; cost = 2 * tk + (ROLL * (i - pos["i"]) * iv / 240 if d == -1 else 0)
                net = gross - cost
                out.append({"sym": sym, "cls": cls(sym), "side": "long" if d == 1 else "short", "t": cs[pos["i"]]["t"], "R": net / pos["risk"], "net_pct": net * 100, "gross_pct": gross * 100, "bars": i - pos["i"]})
                pos = None
            else:
                pos["stop"] = stop
            continue
        hi = max(x["h"] for x in cs[i - N:i]); lo = min(x["l"] for x in cs[i - N:i])
        d = 1 if c["c"] > hi else (-1 if c["c"] < lo else 0)
        if not d or ("long" if d == 1 else "short") not in sides: continue
        if filt == "ema" and ((d == 1 and c["c"] < E200[i]) or (d == -1 and c["c"] > E200[i])): continue
        e = cs[i + 1]["o"] * (1 + d * sl); a = A[i]
        if a <= 0 or k * a / e < 0.004: continue
        pos = {"d": d, "e": e, "i": i + 1, "atr": a, "stop": e - d * k * a, "ext": e, "risk": k * a / e}
    return out

def stats(tr):
    if not tr: return "n=0"
    R = [t["R"] for t in tr]; w = [r for r in R if r > 0]; gp = sum(w); gl = -sum(r for r in R if r <= 0)
    return f"n={len(R):4d} réussite={len(w)/len(R)*100:3.0f}% R moyen={st.mean(R):+.2f} net moyen={st.mean(t['net_pct'] for t in tr):+.2f}% PF={gp/gl if gl else 9.9:.2f} durée moy={st.mean(t['bars'] for t in tr):.0f} bougies"

def report(name, iv, **kw):
    allt = [t for a in cfg["univers"] for t in bt(a["sym"], iv, **kw)]
    for c in ("action", "crypto", "meme"):
        g = sorted([t for t in allt if t["cls"] == c], key=lambda t: t["t"])
        if not g: continue
        m = g[len(g) // 2]["t"]; a = [t for t in g if t["t"] < m]; b = [t for t in g if t["t"] >= m]
        f = lambda x: f"{st.mean(t['R'] for t in x):+.2f}R" if x else "—"
        print(f"{name:34s} {c:6s} {stats(g)} | moitiés {f(a)} / {f(b)}")
    return allt

if __name__ == "__main__":
    for iv, lab in ((1440, "JOUR"), (240, "4H")):
        for N in (20, 55):
            for k in (2, 3):
                for sides in (("long", "short"), ("long",)):
                    report(f"{lab} canal {N} stop {k}ATR {'L+S' if len(sides)==2 else 'long'}", iv, N=N, k=k, sides=sides)
                print()
