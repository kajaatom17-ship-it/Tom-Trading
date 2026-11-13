"""Garde-fous de risque appliques PAR LE CODE, quoi que decident les agents IA.

Le Risk Manager IA donne son avis ; ces regles sont la derniere barriere.
Un ordre qui echoue a une seule regle n'est jamais execute.
"""
from core import (costs_roundtrip_pct, equity, is_stock, net_rr, pair_of, paris_day, tier_of)

MAJEURES_HORS_CORRELATION = {"BTC", "PAXG"}


def check_open(cfg, state, prop, tick, prices):
    """Retourne (ok, motifs_de_refus, dimensionnement)."""
    R = cfg["risque"]; F = cfg["frais"]
    sym, side = prop.get("sym"), prop.get("side")
    reasons = []

    if state.get("coupe_circuit"):
        reasons.append("Coupe-circuit actif (drawdown max atteint) : aucune nouvelle entrée.")
    if sym not in {a["sym"] for a in cfg["univers"]}:
        reasons.append(f"{sym} n'est pas dans l'univers surveillé.")
        return False, reasons, None
    if side not in ("long", "short"):
        reasons.append("Sens invalide (long ou short attendu).")
        return False, reasons, None
    if tick is None:
        reasons.append("Pas de prix Kraken disponible pour cet actif.")
        return False, reasons, None

    stop, tp = float(prop["stop"]), float(prop["tp"])
    stock = is_stock(pair_of(cfg, sym) or "")
    opp = prop.get("strategie") == "OPP-1"
    O = cfg.get("opportunite", {})
    rr_min = O.get("rr_net_min", 2.0) if opp else R["rr_net_min"]
    risk_pct = O.get("risque_par_trade_pct", 0.5) if opp else R["risque_par_trade_pct"]
    if prop.get("risque_pct_override"):
        risk_pct = min(risk_pct, float(prop["risque_pct_override"]))
    if opp:
        cat = prop.get("catalyseur") or {}
        if not (cat.get("evenement") and cat.get("source") and cat.get("date")):
            reasons.append("OPP-1 : il faut un catalyseur précis avec événement, source et date.")
        n_opp = state.get("opp_par_jour", {}).get(paris_day(), 0)
        if n_opp >= O.get("max_par_jour", 1):
            reasons.append("OPP-1 : déjà une opportunité prise aujourd'hui.")
    tier = tier_of(cfg, sym)
    slip = F["slippage_pct_par_tier"][tier]
    fill = tick["ask"] * (1 + slip / 100) if side == "long" else tick["bid"] * (1 - slip / 100)

    # coherence stop / objectif
    if side == "long" and not (stop < fill < tp):
        reasons.append(f"Long : il faut stop < prix ({fill:.6g}) < objectif.")
    if side == "short" and not (tp < fill < stop):
        reasons.append(f"Short : il faut objectif < prix ({fill:.6g}) < stop.")

    dist_pct = abs(fill - stop) / fill * 100
    if dist_pct < R["distance_stop_min_pct"]:
        reasons.append(f"Stop trop proche ({dist_pct:.2f} % < {R['distance_stop_min_pct']} %) : il sauterait sur le bruit et les frais.")
    if dist_pct > R["distance_stop_max_pct"]:
        reasons.append(f"Stop trop loin ({dist_pct:.2f} % > {R['distance_stop_max_pct']} %).")

    rr = net_rr(cfg, sym, side, fill, stop, tp)
    if rr < rr_min:
        reasons.append(f"Ratio rendement/risque net de frais {rr:.2f} < {rr_min}.")

    # derive de prix depuis la proposition (l'ordre arrive quelques minutes apres)
    ref = prop.get("entry_ref"); a = prop.get("atr")
    if ref and a:
        drift = abs(fill - float(ref)) / float(a)
        if drift > R["derive_prix_max_atr"]:
            reasons.append(f"Le prix a trop bougé depuis la décision ({drift:.2f} ATR) : ordre expiré.")

    # liquidite
    if tick["spread_pct"] > R["spread_max_pct"]:
        reasons.append(f"Spread trop large ({tick['spread_pct']:.2f} %).")
    vmin = R.get("volume_24h_min_eur_actions", 2000) if stock else R["volume_24h_min_eur"]
    if tick["vol_eur"] < vmin:
        reasons.append(f"Volume 24 h trop faible ({tick['vol_eur']:.0f} EUR).")

    # limites de portefeuille
    day = paris_day()
    if state["entrees_par_jour"].get(day, 0) >= R["max_entrees_par_jour"]:
        reasons.append(f"Déjà {R['max_entrees_par_jour']} entrées aujourd'hui.")
    if len(state["positions"]) >= R["max_positions_ouvertes"]:
        reasons.append(f"Déjà {R['max_positions_ouvertes']} positions ouvertes.")
    if any(p["sym"] == sym for p in state["positions"]):
        reasons.append(f"Une position {sym} est déjà ouverte.")
    if stock:
        same = [p for p in state["positions"] if p["side"] == side and is_stock(p.get("pair", ""))]
        if len(same) >= R.get("max_actions_meme_sens", 2):
            reasons.append(f"Déjà {len(same)} actions dans le même sens (risque de corrélation).")
    elif sym not in MAJEURES_HORS_CORRELATION:
        same = [p for p in state["positions"] if p["side"] == side and p["sym"] not in MAJEURES_HORS_CORRELATION
                and not is_stock(p.get("pair", ""))]
        if len(same) >= R["max_alts_meme_sens"]:
            reasons.append(f"Déjà {len(same)} altcoins dans le même sens (risque de corrélation).")

    eq = equity(state, prices)
    day_pnl = eq - state.get("equity_debut_jour", {}).get(day, eq)
    if day_pnl <= -R["perte_jour_max_pct"] / 100 * state["capital_initial"]:
        reasons.append(f"Perte du jour {day_pnl:.2f} EUR : limite journalière atteinte.")

    # dimensionnement : on risque au plus X % du capital, frais compris
    risk_eur = eq * risk_pct / 100
    per_unit = abs(fill - stop) + F["taker_pct"] / 100 * (fill + stop)
    qty = risk_eur / per_unit if per_unit > 0 else 0
    cap = eq * R["notionnel_max_pct_par_tier"][tier] / 100
    fee_rate = F["taker_pct"] / 100
    cap = min(cap, state["cash"] / (1 + fee_rate))
    capped = False
    if qty * fill > cap:
        qty = cap / fill; capped = True
    notional = qty * fill
    if notional < 10:
        reasons.append(f"Taille de position trop petite ({notional:.2f} EUR) : cash insuffisant ou limite atteinte.")

    sizing = {
        "fill": fill, "qty": qty, "notionnel": notional, "frais_entree": notional * fee_rate,
        "risque_eur": qty * per_unit, "risque_cible_eur": risk_eur, "plafonne": capped,
        "rr_net": rr, "distance_stop_pct": dist_pct, "tier": tier, "slippage_pct": slip,
        "couts_aller_retour_pct": costs_roundtrip_pct(cfg, sym),
    }
    return (len(reasons) == 0), reasons, sizing
