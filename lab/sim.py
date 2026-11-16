"""Étape 2 : rejoue les signaux avec les vrais frais, plusieurs variantes de sortie."""
import sys, json, collections, statistics as st
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import core
cfg = core.config(); C = json.load(open("candles.json")); S = json.load(open("signals.json"))
ACT = {a["sym"] for a in cfg["univers"] if a.get("classe") == "action"}
MEME = {a["sym"] for a in cfg["univers"] if core.is_meme(cfg, a["sym"])}
def cls(sym): return "action" if sym in ACT else ("meme" if sym in MEME else "crypto")
def slip(sym): return cfg["frais"]["slippage_pct_par_tier"][core.tier_of(cfg, sym)] / 100

def sim(sig, tpR=3.0, maxbars=96, be_at=None, stop_mult=1.0, entry="market", fee_override=None):
    """Retourne le R net d'un trade (None si pas d'entrée)."""
    cs = C[f"{sig['sym']}|{sig['iv']}"]; i = sig["i"]; side = sig["side"]; sym = sig["sym"]
    mk, tk = fee_override or core.fees(cfg, sym); mk /= 100; tk /= 100; sl = slip(sym)
    d = 1 if side == "long" else -1
    if i + 1 >= len(cs): return None
    if entry == "market":
        e = cs[i + 1]["o"] * (1 + d * sl); fe = tk; j0 = i + 1
    else:  # ordre limite au prix du signal, valable 2 bougies
        px = sig["px"]; j0 = None
        for j in (i + 1, i + 2):
            if j < len(cs) and ((d == 1 and cs[j]["l"] <= px) or (d == -1 and cs[j]["h"] >= px)):
                j0 = j; break
        if j0 is None: return None
        e = px; fe = mk
    risk = abs(sig["px"] - sig["stop"]) * stop_mult
    stop = e - d * risk; tp = e + d * tpR * risk; moved = False
    for j in range(j0, min(len(cs), j0 + maxbars)):
        c = cs[j]
        hit_stop = c["l"] <= stop if d == 1 else c["h"] >= stop
        hit_tp = c["h"] >= tp if d == 1 else c["l"] <= tp
        if hit_stop:
            x = stop * (1 - d * sl); fx = tk; break
        if hit_tp:
            x = tp; fx = mk; break
        if be_at and not moved and ((c["h"] - e) * d if d == 1 else (e - c["l"])) >= be_at * risk:
            stop = e + d * (fe + tk) * e; moved = True
    else:
        x = cs[min(len(cs) - 1, j0 + maxbars - 1)]["c"] * (1 - d * sl); fx = tk; j = min(len(cs) - 1, j0 + maxbars - 1)
    gross = (x - e) * d / e; net = gross - fe - fx
    return {"R": net / (risk / e), "net_pct": net * 100, "gross_pct": gross * 100, "exit_i": j, "risk_pct": risk / e * 100}

def run(filt, **kw):
    """Une position à la fois par actif. Renvoie les trades."""
    busy = {}; out = []
    for s in sorted(S, key=lambda x: (x["iv"], x["t"])):
        if not filt(s): continue
        k = (s["sym"], s["iv"])
        if busy.get(k, -1) >= s["i"]: continue
        r = sim(s, **kw)
        if not r: continue
        busy[k] = r["exit_i"]; r.update(sym=s["sym"], strat=s["strat"], side=s["side"], cls=cls(s["sym"]), iv=s["iv"], t=s["t"]); out.append(r)
    return out

def stats(tr):
    if not tr: return "n=0"
    R = [t["R"] for t in tr]; w = [r for r in R if r > 0]
    gp = sum(w); gl = -sum(r for r in R if r <= 0)
    return f"n={len(R):4d} réussite={len(w)/len(R)*100:4.0f}% R moyen={st.mean(R):+.2f} net moyen={st.mean(t['net_pct'] for t in tr):+.2f}% brut moyen={st.mean(t['gross_pct'] for t in tr):+.2f}% PF={gp/gl if gl else 9.99:.2f} total={sum(R):+.0f}R"

def table(title, tr, keys=("iv", "cls", "strat")):
    print("\n== " + title)
    g = collections.defaultdict(list)
    for t in tr: g[tuple(t[k] for k in keys)].append(t)
    for k in sorted(g): print(" ", k, stats(g[k]))

if __name__ == "__main__":
    base = run(lambda s: True)
    table("ACTUEL : entrée marché, objectif 3R, 96 bougies max (15 min = 24 h, 1 h = 4 jours)", base)
    table("ACTUEL par sens", base, ("iv", "cls", "side"))
