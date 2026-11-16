"""Autres familles : retour à la moyenne journalier (RSI2), cassure d'ouverture actions (ORB 30 min), impulsions 5 min."""
import sys, json, statistics as st, datetime as dt
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import core
from trend import cfg, C, cls, ROLL
def cost(sym, maker_exit=False, maker_entry=False):
    mk, tk = core.fees(cfg, sym); sl = cfg["frais"]["slippage_pct_par_tier"][core.tier_of(cfg, sym)]
    return ((mk if maker_entry else tk + sl) + (mk if maker_exit else tk + sl)) / 100
def sma(v, n, i): return sum(v[i - n + 1:i + 1]) / n
def summ(name, tr):
    for c in ("action", "crypto", "meme"):
        g = sorted([t for t in tr if t["cls"] == c], key=lambda t: t["t"])
        if len(g) < 5: continue
        m = g[len(g) // 2]["t"]; a = [t["net"] for t in g if t["t"] < m]; b = [t["net"] for t in g if t["t"] >= m]
        N = [t["net"] for t in g]; w = [x for x in N if x > 0]; gl = -sum(x for x in N if x <= 0)
        print(f"{name:44s} {c:6s} n={len(N):4d} réussite={len(w)/len(N)*100:3.0f}% net moyen={st.mean(N):+.2f}% PF={sum(w)/gl if gl else 9.9:.2f} | moitiés {st.mean(a) if a else 0:+.2f}% / {st.mean(b) if b else 0:+.2f}%")

def rsi2(sym, lo=10, trend=200, exit_n=5, maxhold=10, stop_pct=None):
    cs = C.get(f"{sym}|1440"); out = []
    if not cs or len(cs) < trend + 20: return out
    cs = cs[:-1]; cl = [c["c"] for c in cs]; R = core.rsi(cl, 2); i = trend
    while i < len(cs) - 1:
        if R[i] < lo and cl[i] > sma(cl, trend, i):
            e = cs[i + 1]["o"]; j = i + 1; x = None
            while j < len(cs):
                if stop_pct and cs[j]["l"] <= e * (1 - stop_pct / 100): x = min(cs[j]["o"], e * (1 - stop_pct / 100)); break
                if cl[j] > sma(cl, exit_n, j) or j - i >= maxhold: x = cl[j]; break
                j += 1
            if x is None: break
            out.append({"cls": cls(sym), "t": cs[i]["t"], "net": ((x - e) / e - cost(sym)) * 100, "sym": sym}); i = j
        i += 1
    return out

def orb(sym, tpR=None, both=True, minrange=0.3):
    """Actions : range des 30 premières minutes (14h30-15h00 UTC), entrée sur cassure, stop à l'autre borne, sortie à la clôture (21h00 UTC)."""
    cs = C.get(f"{sym}|30"); out = []
    if not cs: return out
    days = {}
    for c in cs[:-1]:
        d = dt.datetime.utcfromtimestamp(c["t"]); days.setdefault(d.date(), []).append((d.hour * 60 + d.minute, c))
    for day, bars in days.items():
        if day.weekday() >= 5: continue
        op = [c for m, c in bars if m == 870]; rest = [c for m, c in bars if 900 <= m < 1260]
        if not op or len(rest) < 8 or op[0]["v"] == 0: continue
        hi, lo = op[0]["h"], op[0]["l"]; rng = (hi - lo) / lo * 100
        if rng < minrange: continue
        pos = None
        for c in rest:
            if not pos:
                if c["h"] > hi: pos = (1, hi, lo)
                elif both and c["l"] < lo: pos = (-1, lo, hi)
                if pos:
                    d, e, s = pos; tp = e + d * tpR * abs(e - s) if tpR else None
                    continue
            else:
                d, e, s = pos
                if (d == 1 and c["l"] <= s) or (d == -1 and c["h"] >= s): x = s; break
                if tp and ((d == 1 and c["h"] >= tp) or (d == -1 and c["l"] <= tp)): x = tp; break
        else:
            x = rest[-1]["c"] if pos else None
        if pos and x:
            d, e, s = pos
            out.append({"cls": "action", "t": op[0]["t"], "net": ((x - e) * d / e - cost(sym)) * 100, "sym": sym})
    return out

def impulse(sym, iv=5, nb=3, move=2.5, volx=3.0, stop_part=0.5, tpR=2.0, maxbars=24, fade=False):
    cs = C.get(f"{sym}|{iv}"); out = []
    if not cs or cls(sym) == "action": return out
    cs = cs[:-1]; i = 40
    while i < len(cs) - 2:
        w = cs[i - nb + 1:i + 1]; mv = (w[-1]["c"] / w[0]["o"] - 1) * 100
        vavg = sum(c["v"] for c in cs[i - nb - 29:i - nb + 1]) / 30 or 1e-9
        if abs(mv) >= move and sum(c["v"] for c in w) / nb >= volx * vavg:
            d = (1 if mv > 0 else -1) * (-1 if fade else 1); e = cs[i + 1]["o"]; risk = abs(mv) / 100 * stop_part * e
            stop = e - d * risk; tp = e + d * tpR * risk; x = None
            for j in range(i + 1, min(len(cs), i + 1 + maxbars)):
                c = cs[j]
                if (d == 1 and c["l"] <= stop) or (d == -1 and c["h"] >= stop): x = stop; mexit = False; break
                if (d == 1 and c["h"] >= tp) or (d == -1 and c["l"] <= tp): x = tp; mexit = True; break
            else:
                j = min(len(cs) - 1, i + maxbars); x = cs[j]["c"]; mexit = False
            out.append({"cls": cls(sym), "t": cs[i]["t"], "net": ((x - e) * d / e - cost(sym, maker_exit=mexit)) * 100, "sym": sym}); i = j
        i += 1
    return out

if __name__ == "__main__":
    U = [a["sym"] for a in cfg["univers"]]
    for lo in (5, 10, 20):
        summ(f"RSI2<{lo}, au-dessus MM200, sortie > MM5", [t for s in U for t in rsi2(s, lo=lo)])
    summ("RSI2<10, MM100, sortie > MM5", [t for s in U for t in rsi2(s, trend=100)])
    summ("RSI2<10, MM200, stop 8 %", [t for s in U for t in rsi2(s, stop_pct=8)])
    idx = [t for s in ("SPY", "QQQ", "GLD") for t in rsi2(s, lo=20, trend=100)]
    print("   dont SPY/QQQ/GLD RSI2<20 MM100 :", len(idx), round(st.mean(t["net"] for t in idx), 2) if idx else None)
    print()
    for kw, lab in (({}, "ORB 30 min, sortie clôture"), ({"tpR": 2}, "ORB 30 min, objectif 2R"), ({"both": False}, "ORB long seul"), ({"minrange": 0.8}, "ORB range>=0,8 %")):
        summ(lab, [t for s in U for t in orb(s, **kw)])
    print()
    for kw, lab in (({}, "Impulsion 5 min 2,5 % vol x3 (MOM-1)"), ({"move": 4}, "Impulsion 5 min 4 %"), ({"move": 4, "tpR": 3, "maxbars": 48}, "Impulsion 4 %, 3R, 4 h"), ({"fade": True}, "Contre-impulsion 2,5 %"), ({"move": 4, "fade": True}, "Contre-impulsion 4 %")):
        summ(lab, [t for s in U for t in impulse(s, **kw)])
