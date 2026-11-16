"""Strategies v1 : regles fixes et mesurables, ecrites AVANT de trader.

TPB-1  Pullback dans la tendance : tendance 1 h confirmee, repli sur l'EMA20
       en 15 min, puis reprise (RSI et MACD qui repartent).
       Stop >= max(1,5 ATR, 1 %) sous le dernier creux, objectif 3R.
BRK-1  Cassure avec volume : cloture 15 min au-dela du plus haut / plus bas
       des 12 dernieres heures, volume au moins 1,8 x la moyenne.
       Stop >= max(2 ATR, 1 %), objectif 3R.

SWG-1  (depuis le 16 nov 2026, seule strategie automatique) : meme repli dans la
       tendance, mais en bougies 1 h, uniquement dans le sens de la tendance de
       fond 20 jours de l'actif ET de son marche (BTC ou QQQ), stop deux fois
       plus large, objectif 3R, tenue jusqu'a 8 jours. Voir lab/RESULTATS.md.

TPB-1 et BRK-1 en 15 min sont retirees : sur l'historique elles perdent meme sans frais.
"""
from core import aggregate, atr, ema, macd_hist, net_rr, rp, rsi


def analyse(candles15):
    """Indicateurs sur bougies 15 min CLOTUREES (la derniere bougie Kraken est en cours)."""
    c = candles15[:-1]
    if len(c) < 120:
        return None
    closes = [x["c"] for x in c]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    r = rsi(closes); a = atr(c); mh = macd_hist(closes)
    vols = [x["v"] for x in c]
    vavg = sum(vols[-21:-1]) / 20 or 1
    h1 = aggregate(c, 4)
    h_closes = [x["c"] for x in h1]
    he20, he50 = ema(h_closes, 20), ema(h_closes, 50)
    if h_closes[-1] > he50[-1] and he20[-1] > he50[-1] and he50[-1] >= he50[-4]:
        trend = "haussiere"
    elif h_closes[-1] < he50[-1] and he20[-1] < he50[-1] and he50[-1] <= he50[-4]:
        trend = "baissiere"
    else:
        trend = "neutre"
    last = c[-1]
    hi48 = max(x["h"] for x in c[-49:-1]); lo48 = min(x["l"] for x in c[-49:-1])
    return {
        "close": last["c"], "t": last["t"], "ema20": e20[-1], "ema50": e50[-1],
        "rsi": round(r[-1], 1), "rsi_prev": round(r[-2], 1), "atr": a[-1],
        "atr_pct": round(a[-1] / last["c"] * 100, 3),
        "macd_h": mh[-1], "macd_h_prev": mh[-2], "vol_ratio": round(last["v"] / vavg, 2),
        "trend_1h": trend, "plus_haut_12h": hi48, "plus_bas_12h": lo48,
        "bas_recent": min(x["l"] for x in c[-6:]), "haut_recent": max(x["h"] for x in c[-6:]),
        "touche_ema20_bas": any(x["l"] <= e20[-1 - i] * 1.002 for i, x in enumerate(reversed(c[-3:]))),
        "touche_ema20_haut": any(x["h"] >= e20[-1 - i] * 0.998 for i, x in enumerate(reversed(c[-3:]))),
        "var_24h_pct": round((last["c"] / c[-97]["c"] - 1) * 100, 2) if len(c) > 97 else None,
    }


def signals(cfg, sym, ind, btc_trend):
    out = []
    if not ind:
        return out
    px, a = ind["close"], ind["atr"]

    def make(strat, side, stop, why, score):
        # stop au moins a 1,5 ATR et 1 % : en dessous, les frais Kraken mangent le trade
        dmin = max(1.5 * a, 0.01 * px)
        stop = min(stop, px - dmin) if side == "long" else max(stop, px + dmin)
        risk = abs(px - stop)
        tp = px + 3 * risk if side == "long" else px - 3 * risk  # objectif 3R
        rr = net_rr(cfg, sym, side, px, stop, tp)
        warn = []
        if sym not in ("BTC", "PAXG"):
            if side == "long" and btc_trend == "baissiere":
                warn.append("contre la tendance de BTC"); score -= 15
            if side == "short" and btc_trend == "haussiere":
                warn.append("contre la tendance de BTC"); score -= 15
        if rr < cfg["risque"]["rr_net_min"]:
            warn.append(f"RR net {rr:.2f} trop faible après frais"); score -= 30
        out.append({"sym": sym, "strategie": strat, "side": side, "entry_ref": rp(px),
                    "stop": rp(stop), "tp": rp(tp), "atr": rp(a), "rr_net": round(rr, 2),
                    "score": max(0, min(100, score)), "pourquoi": why, "alertes": warn})

    # TPB-1 pullback dans la tendance
    if ind["trend_1h"] == "haussiere" and ind["touche_ema20_bas"] and px > ind["ema20"] \
            and 42 <= ind["rsi"] <= 65 and ind["rsi"] > ind["rsi_prev"] and ind["macd_h"] > ind["macd_h_prev"]:
        make("TPB-1", "long", ind["bas_recent"] - 0.3 * a,
             "Tendance 1 h haussière, repli sur l'EMA20 15 min puis reprise (RSI et MACD en hausse).",
             60 + (10 if ind["vol_ratio"] > 1.2 else 0))
    if ind["trend_1h"] == "baissiere" and ind["touche_ema20_haut"] and px < ind["ema20"] \
            and 35 <= ind["rsi"] <= 58 and ind["rsi"] < ind["rsi_prev"] and ind["macd_h"] < ind["macd_h_prev"]:
        make("TPB-1", "short", ind["haut_recent"] + 0.3 * a,
             "Tendance 1 h baissière, rebond sur l'EMA20 15 min puis rechute (RSI et MACD en baisse).",
             60 + (10 if ind["vol_ratio"] > 1.2 else 0))

    # BRK-1 cassure avec volume
    if px > ind["plus_haut_12h"] and ind["vol_ratio"] >= 1.8 and ind["trend_1h"] != "baissiere" and ind["rsi"] < 78:
        make("BRK-1", "long", px - 2 * a,
             f"Cassure du plus haut 12 h avec volume x{ind['vol_ratio']}.", 55 + min(20, int(ind["vol_ratio"] * 4)))
    if px < ind["plus_bas_12h"] and ind["vol_ratio"] >= 1.8 and ind["trend_1h"] != "haussiere" and ind["rsi"] > 22:
        make("BRK-1", "short", px + 2 * a,
             f"Cassure du plus bas 12 h avec volume x{ind['vol_ratio']}.", 55 + min(20, int(ind["vol_ratio"] * 4)))
    return out


def swing_signals(cfg, sym, ind, regime, ref_regime):
    """SWG-1. `ind` = analyse() sur bougies 1 h ; regime / ref_regime = +1, -1, 0 (None = pas de marché de référence)."""
    out = []
    S = cfg.get("swing", {})
    if not ind or not S.get("actif"):
        return out
    px, a = ind["close"], ind["atr"]

    def make(side, stop, why):
        d = 1 if side == "long" else -1
        if regime != d or (ref_regime is not None and ref_regime != d):
            return
        dmin = max(1.5 * a, 0.01 * px)
        stop = min(stop, px - dmin) if side == "long" else max(stop, px + dmin)
        risk = abs(px - stop) * S.get("stop_x", 2.0)
        stop = px - d * risk
        tp = px + d * S.get("objectif_R", 3.0) * risk
        rr = net_rr(cfg, sym, side, px, stop, tp)
        score = 70 + (10 if ind["vol_ratio"] > 1.2 else 0); warn = []
        if rr < cfg["risque"]["rr_net_min"]:
            warn.append(f"RR net {rr:.2f} trop faible après frais"); score -= 30
        out.append({"sym": sym, "strategie": "SWG-1", "side": side, "entry_ref": rp(px), "stop": rp(stop), "tp": rp(tp), "atr": rp(a),
                    "rr_net": round(rr, 2), "score": max(0, min(100, score)), "pourquoi": why, "alertes": warn,
                    "duree_max_h": S.get("duree_max_h", 192), "t_signal": ind["t"]})

    if ind["trend_1h"] == "haussiere" and ind["touche_ema20_bas"] and px > ind["ema20"] \
            and 42 <= ind["rsi"] <= 65 and ind["rsi"] > ind["rsi_prev"] and ind["macd_h"] > ind["macd_h_prev"]:
        make("long", ind["bas_recent"] - 0.3 * a, "Tendance de fond 20 jours haussière (actif et marché), tendance 4 h haussière, repli sur l'EMA20 1 h puis reprise.")
    if ind["trend_1h"] == "baissiere" and ind["touche_ema20_haut"] and px < ind["ema20"] \
            and 35 <= ind["rsi"] <= 58 and ind["rsi"] < ind["rsi_prev"] and ind["macd_h"] < ind["macd_h_prev"]:
        make("short", ind["haut_recent"] + 0.3 * a, "Tendance de fond 20 jours baissière (actif et marché), tendance 4 h baissière, rebond sur l'EMA20 1 h puis rechute.")
    return out


def ref_of(a):
    """Marché de référence pour la tendance de fond : QQQ pour les actions, BTC pour les cryptos, aucun pour l'or."""
    if a.get("cat") == "Or":
        return None
    return "QQQ" if a.get("classe") == "action" else "BTC"
