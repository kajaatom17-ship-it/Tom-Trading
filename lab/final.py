"""Candidat SWG-1 rejoué avec la mécanique du moteur (protection, moitié à l'objectif, stop suiveur, coût du short) + portefeuille de 500 €."""
import sys, json, bisect, collections, statistics as st
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import core
from sim import cfg, C, S, cls, slip
C2 = json.load(open("candles2.json"))
D = {k.split("|")[0]: ([c["t"] for c in v], [c["c"] for c in v]) for k, v in C2.items() if k.endswith("|1440")}
ROLL = cfg["frais"]["rollover_short_pct_par_4h"] / 100
def regime(sym, t, n=20):
    ts, cl = D.get(sym, ([], [])); j = bisect.bisect_right(ts, t - 86400) - 1
    return 0 if j < n else (1 if cl[j] > cl[j - n] else -1)
def reg_ok(s, n=20):
    d = 1 if s["side"] == "long" else -1
    ref = "QQQ" if cls(s["sym"]) == "action" else "BTC"
    return regime(s["sym"], s["t"], n) == d and regime(ref, s["t"], n) == d

def sim(sig, tpR=3.0, maxbars=192, stop_mult=2.0, protect=True, half=True, entry="market"):
    cs = C[f"{sig['sym']}|{sig['iv']}"]; i = sig["i"]; sym = sig["sym"]; d = 1 if sig["side"] == "long" else -1
    mk, tk = core.fees(cfg, sym); mk /= 100; tk /= 100; sl = slip(sym)
    if i + 1 >= len(cs): return None
    if entry == "market": e = cs[i + 1]["o"] * (1 + d * sl); fe = tk; j0 = i + 1
    else:
        px = sig["px"]; j0 = next((j for j in (i + 1, i + 2) if j < len(cs) and ((d == 1 and cs[j]["l"] <= px) or (d == -1 and cs[j]["h"] >= px))), None)
        if j0 is None: return None
        e = px; fe = mk
    R1 = abs(sig["px"] - sig["stop"]) * stop_mult; stop = e - d * R1; tp = e + d * tpR * R1
    rem = 1.0; pnl = -fe; runner = False; best = e; j = j0
    for j in range(j0, min(len(cs), j0 + maxbars)):
        c = cs[j]; hi, lo = c["h"], c["l"]
        if (lo <= stop) if d == 1 else (hi >= stop):
            x = (min(c["o"], stop) if d == 1 else max(c["o"], stop)) * (1 - d * sl)
            pnl += rem * ((x - e) * d / e - tk); rem = 0; break
        if not runner and ((hi >= tp) if d == 1 else (lo <= tp)):
            if not half:
                pnl += rem * ((tp - e) * d / e - mk); rem = 0; break
            pnl += 0.5 * ((tp - e) * d / e - mk); rem = 0.5; runner = True; best = tp
            stop = max(stop, tp - R1) if d == 1 else min(stop, tp + R1)
        ext = hi if d == 1 else lo
        if runner:
            best = max(best, ext) if d == 1 else min(best, ext)
            stop = max(stop, best - R1) if d == 1 else min(stop, best + R1)
        elif protect:
            fav = (ext - e) * d
            if fav >= 2 * R1: lvl = e + d * R1
            elif fav >= R1: lvl = e * (1 + d * 2 * tk)
            else: lvl = None
            if lvl is not None: stop = max(stop, lvl) if d == 1 else min(stop, lvl)
    if rem > 0:
        x = cs[j]["c"] * (1 - d * sl); pnl += rem * ((x - e) * d / e - tk)
    bars = j - j0 + 1
    if d == -1: pnl -= ROLL * bars * sig["iv"] / 240
    return {"R": pnl / (R1 / e), "net_pct": pnl * 100, "exit_i": j, "risk_pct": R1 / e * 100, "bars": bars, "entry_i": j0}

def portfolio(filt, iv, label, risk_pct=1.0, max_crypto=2, max_stock=3, **kw):
    cap = cfg["risque"]["notionnel_max_pct_par_tier"]
    eq = 500.0; peak = eq; dd = 0; open_ = []; out = []; lastsym = {}
    for s in sorted([x for x in S if x["iv"] == iv and filt(x)], key=lambda x: x["t"]):
        tclose = lambda p: C[f"{p['sym']}|{iv}"][p["exit_i"]]["t"]
        for p in [p for p in open_ if tclose(p) <= s["t"]]:
            eq += p["eur"]; open_.remove(p); peak = max(peak, eq); dd = max(dd, (peak - eq) / peak * 100)
        if any(p["sym"] == s["sym"] for p in open_) or lastsym.get(s["sym"], -1) >= s["i"]: continue
        c = cls(s["sym"]); nc = sum(1 for p in open_ if p["cls"] != "action"); ns = sum(1 for p in open_ if p["cls"] == "action")
        if (c == "action" and ns >= max_stock) or (c != "action" and nc >= max_crypto): continue
        r = sim(s, **kw)
        if not r: continue
        risk_eur = min(eq * risk_pct / 100, eq * cap[core.tier_of(cfg, s["sym"])] / 100 * r["risk_pct"] / 100)
        if c == "meme": risk_eur = min(risk_eur, eq * 0.005)
        r.update(sym=s["sym"], cls=c, side=s["side"], t=s["t"], eur=r["R"] * risk_eur, strat=s["strat"]); open_.append(r); out.append(r); lastsym[s["sym"]] = r["exit_i"]
    for p in open_: eq += p["eur"]
    peak = max(peak, eq); dd = max(dd, (peak - eq) / peak * 100)
    days = (max(x["t"] for x in out) - min(x["t"] for x in out)) / 86400 if out else 0
    R = [t["R"] for t in out]; gl = -sum(r for r in R if r <= 0)
    by = collections.defaultdict(float); n = collections.Counter()
    for t in out: by[(t["cls"], t["side"])] += t["eur"]; n[(t["cls"], t["side"])] += 1
    print(f"{label:46s} {days:4.0f} j  n={len(out):3d}  réussite={sum(r>0 for r in R)/max(1,len(R))*100:3.0f}%  R moyen={st.mean(R) if R else 0:+.2f}  PF={sum(r for r in R if r>0)/gl if gl else 9.9:.2f}  résultat={eq-500:+7.2f} €  pire baisse={dd:4.1f}%  durée moy={st.mean(t['bars'] for t in out)*iv/60 if out else 0:.0f} h")
    print("     " + "  ".join(f"{k[0]} {k[1]} {n[k]}: {v:+.1f} €" for k, v in sorted(by.items())))
    return out

if __name__ == "__main__":
    tpb = lambda s: s["strat"] == "TPB-1" and reg_ok(s)
    for iv in (60, 240):
        print(f"\n===== bougies {iv} min =====")
        portfolio(lambda s: True, iv, "ANCIEN (tous signaux, stop serré, 24 bougies)", stop_mult=1, maxbars=24 if iv == 60 else 6)
        portfolio(tpb, iv, "SWG-1 marché, protection, moitié+suiveur")
        portfolio(tpb, iv, "SWG-1 sans protection", protect=False)
        portfolio(tpb, iv, "SWG-1 sans protection, tout à 3R", protect=False, half=False)
        portfolio(tpb, iv, "SWG-1 limite, sans protection", protect=False, entry="limit")
        portfolio(tpb, iv, "SWG-1 limite, protection", entry="limit")
        portfolio(lambda s: reg_ok(s), iv, "SWG-1 + cassures, sans protection", protect=False)
        portfolio(lambda s: tpb(s) and cls(s["sym"]) != "meme", iv, "SWG-1 sans memecoins, sans protection", protect=False)
