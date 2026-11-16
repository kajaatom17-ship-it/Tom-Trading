from sim import *
import itertools
def half(tr, iv):
    ts = sorted(t["t"] for t in tr if t["iv"] == iv)
    return ts[len(ts)//2] if ts else 0
def show(name, tr):
    for iv in (15, 60):
        for c in ("action", "crypto", "meme"):
            g = [t for t in tr if t["iv"] == iv and t["cls"] == c]
            if not g: continue
            m = half(g, iv); a = [t for t in g if t["t"] < m]; b = [t for t in g if t["t"] >= m]
            f = lambda x: f"{st.mean(t['R'] for t in x):+.2f}R/{len(x)}" if x else "—"
            print(f"  {name:38s} {iv:2d}m {c:6s} tout {f(g):12s} 1re moitié {f(a):12s} 2e moitié {f(b):12s} net {st.mean(t['net_pct'] for t in g):+.2f}%")
aligned = lambda s: not s["alertes"] or all("BTC" not in a for a in s["alertes"])
for name, filt, kw in [
    ("base 3R", lambda s: True, {}),
    ("2R", lambda s: True, {"tpR": 2}),
    ("5R + 2x durée", lambda s: True, {"tpR": 5, "maxbars": 192}),
    ("3R, stop x2", lambda s: True, {"stop_mult": 2}),
    ("3R, stop x2, 2x durée", lambda s: True, {"stop_mult": 2, "maxbars": 192}),
    ("3R entrée limite", lambda s: True, {"entry": "limit"}),
    ("3R limite, stop x2, 2x durée", lambda s: True, {"entry": "limit", "stop_mult": 2, "maxbars": 192}),
    ("score>=75", lambda s: s["score"] >= 75, {}),
    ("BRK vol>=3", lambda s: s["strat"] == "BRK-1" and s["vol_ratio"] >= 3, {}),
    ("BRK vol>=3 limite", lambda s: s["strat"] == "BRK-1" and s["vol_ratio"] >= 3, {"entry": "limit"}),
    ("TPB seulement, BE à 1R", lambda s: s["strat"] == "TPB-1", {"be_at": 1}),
    ("frais zéro (référence)", lambda s: True, {"fee_override": (0, 0)}),
]:
    show(name, run(filt, **kw)); print()
