"""Un 'tick' du moteur : prix -> gestion des positions -> ordres des agents -> scanner -> sauvegarde.

Lance toutes les 5 minutes par GitHub Actions (et a chaque ordre pousse par le comite).
Usage local : python engine/tick.py [--no-scan]
"""
import glob
import json
import re
import os
import shutil
import sys
import time
import urllib.request
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import (costs_roundtrip_pct, is_meme, ARCHIVE, INBOX, KrakenError, config, equity, iso, kraken, load, log_event, new_state,
                  now_utc, ohlc, pair_of, paris_day, parse_iso, position_value, r2, rp, save, tickers, tier_of)
from risk import check_open
from strategy import analyse, signals

ENGINE_VERSION = "1.0"


# ------------------------------------------------------------------ clotures
def close_position(cfg, state, p, exit_px, reason, when=None, maker=False):
    rate = cfg["frais"]["maker_pct"] if maker else cfg["frais"]["taker_pct"]
    fee = p["qty"] * exit_px * rate / 100
    value = position_value(p, exit_px)
    state["cash"] += value - fee
    gross = value - p["notionnel"]
    net = gross - fee - p["frais_entree"] - p.get("rollover", 0)
    state["frais_cumules"] += fee
    state["pnl_realise"] += net
    state["positions"] = [x for x in state["positions"] if x["id"] != p["id"]]
    t_close = when or iso()
    dur = (parse_iso(t_close) - parse_iso(p["ouvert_le"])).total_seconds() / 3600
    trade = {
        "id": p["id"], "sym": p["sym"], "side": p["side"], "strategie": p["strategie"],
        "qty": p["qty"], "entry": p["entry"], "exit": rp(exit_px), "stop": p["stop_initial"], "tp": p["tp"],
        "notionnel": r2(p["notionnel"]), "ouvert_le": p["ouvert_le"], "ferme_le": t_close,
        "duree_h": round(dur, 2), "frais": r2(p["frais_entree"] + fee + p.get("rollover", 0)),
        "pnl_brut": r2(gross), "pnl_net": r2(net), "pnl_pct": round(net / p["notionnel"] * 100, 2),
        "r_multiple": round(net / p["risque_eur"], 2) if p["risque_eur"] else None,
        "raison_sortie": reason, "decision_id": p.get("decision_id"),
    }
    trades = load("trades.json", [])
    trades.append(trade)
    save("trades.json", trades)
    sign = "+" if net >= 0 else ""
    log_event("Execution", "cloture", f"{p['sym']} {p['side']} fermé ({reason}) à {rp(exit_px)} : {sign}{net:.2f} € net", {"id": p["id"]})
    return trade


def net_if_closed(cfg, p, exit_px, maker=False):
    """Gain ou perte net (frais d'entrée, de sortie et de financement compris) si on ferme à exit_px."""
    rate = cfg["frais"]["maker_pct"] if maker else cfg["frais"]["taker_pct"]
    fee = p["qty"] * exit_px * rate / 100
    return position_value(p, exit_px) - p["notionnel"] - fee - p["frais_entree"] - p.get("rollover", 0)


def partial_close(cfg, state, p, frac, exit_px, reason, when, maker=True):
    """Encaisse une partie de la position ; le reste continue."""
    part = dict(p)
    for k in ("qty", "notionnel", "frais_entree", "risque_eur"):
        part[k] = p[k] * frac
        p[k] = p[k] * (1 - frac)
    part["rollover"] = p.get("rollover", 0) * frac
    p["rollover"] = p.get("rollover", 0) * (1 - frac)
    part["id"] = p["id"] + "a"
    state["positions"].append(part)
    close_position(cfg, state, part, exit_px, reason, when, maker=maker)


def runner_step(cfg, p, c):
    """Position « laissée courir » : le stop suit le meilleur prix à 1R, il ne recule jamais."""
    L = cfg.get("trader_de_garde", {}).get("laisser_courir", {})
    dist = L.get("stop_suiveur_R", 1.0) * abs(p["entry"] - p["stop_initial"])
    if p["side"] == "long":
        p["meilleur"] = max(p.get("meilleur", p["entry"]), c["h"])
        new = p["meilleur"] - dist
        if new > p["stop"]:
            p["stop"] = new
    else:
        p["meilleur"] = min(p.get("meilleur", p["entry"]), c["l"])
        new = p["meilleur"] + dist
        if new < p["stop"]:
            p["stop"] = new


def take_profit(cfg, state, p, when):
    """Objectif atteint : soit on ferme tout, soit on encaisse la moitié et on laisse courir le reste."""
    L = cfg.get("trader_de_garde", {}).get("laisser_courir", {})
    if not (L.get("actif") and not p.get("runner")):
        close_position(cfg, state, p, p["tp"], "objectif atteint", when, maker=True)
        return True
    partial_close(cfg, state, p, L.get("part_encaissee", 0.5), p["tp"], "objectif atteint (moitié encaissée)", when)
    R1 = abs(p["entry"] - p["stop_initial"])
    p["runner"] = True
    p["meilleur"] = p["tp"]
    lock = p["tp"] - R1 if p["side"] == "long" else p["tp"] + R1
    p["stop"] = max(p["stop"], lock) if p["side"] == "long" else min(p["stop"], lock)
    p["tp"] = p["entry"] + 50 * R1 if p["side"] == "long" else max(p["entry"] - 50 * R1, p["entry"] * 0.02)
    p["duree_max_h"] = max(p.get("duree_max_h", 24), L.get("duree_max_h", 72))
    log_event("Trader de garde", "laisser courir",
              f"{p['sym']} : objectif atteint, moitié encaissée. Le reste continue, stop suiveur à {rp(p['stop'])}.")
    return False


def manage_positions(cfg, state, tk):
    F = cfg["frais"]
    for p in list(state["positions"]):
        slip = F["slippage_pct_par_tier"][tier_of(cfg, p["sym"])]
        since = parse_iso(p["verifie_jusqu_a"]).timestamp()
        try:
            candles = [c for c in ohlc(p["pair"], 1, since - 60) if c["t"] >= since]
        except KrakenError as e:
            log_event("Execution", "erreur", f"Bougies 1 min indisponibles pour {p['sym']} : {e}")
            candles = []
        time.sleep(1.0)
        closed = False
        for c in candles[:-1]:  # bougies cloturees uniquement
            when = iso(now_utc().fromtimestamp(c["t"] + 60, tz=now_utc().tzinfo))
            if p["side"] == "long":
                hit_stop = c["l"] <= p["stop"]; hit_tp = c["h"] >= p["tp"]
                if hit_stop:  # prudence : si les deux sont touches dans la minute, on retient le stop
                    px = min(c["o"], p["stop"]) * (1 - slip / 100)
                    close_position(cfg, state, p, px, ("stop suiveur (gains encaissés)" if p.get("runner") else "stop-loss" if p["stop"] <= p["stop_initial"] else "stop protégé"), when); closed = True; break
                if hit_tp:
                    if take_profit(cfg, state, p, when):
                        closed = True; break
                if p.get("runner"):
                    runner_step(cfg, p, c)
            else:
                hit_stop = c["h"] >= p["stop"]; hit_tp = c["l"] <= p["tp"]
                if hit_stop:
                    px = max(c["o"], p["stop"]) * (1 + slip / 100)
                    close_position(cfg, state, p, px, ("stop suiveur (gains encaissés)" if p.get("runner") else "stop-loss" if p["stop"] >= p["stop_initial"] else "stop protégé"), when); closed = True; break
                if hit_tp:
                    if take_profit(cfg, state, p, when):
                        closed = True; break
                if p.get("runner"):
                    runner_step(cfg, p, c)
            if p.get("fermer_si_positif"):
                px = c["c"] * (1 + slip / 100) if p["side"] == "short" else c["c"] * (1 - slip / 100)
                if net_if_closed(cfg, p, px) >= p.get("seuil_gain_eur", 0.05):
                    close_position(cfg, state, p, px, "fermé dès le gain (demandé par Tom)", when); closed = True; break
            p["verifie_jusqu_a"] = iso(now_utc().fromtimestamp(c["t"] + 60, tz=now_utc().tzinfo))
        if closed:
            continue
        t = tk.get(p["sym"])
        if t:
            p["dernier_prix"] = t["last"]
            if p.get("fermer_si_positif"):
                px = t["bid"] * (1 - slip / 100) if p["side"] == "long" else t["ask"] * (1 + slip / 100)
                if net_if_closed(cfg, p, px) >= p.get("seuil_gain_eur", 0.05):
                    close_position(cfg, state, p, px, "fermé dès le gain (demandé par Tom)")
                    continue
        # frais de financement simules pour les shorts (emprunt de l'actif)
        if p["side"] == "short":
            hours = (now_utc() - parse_iso(p["ouvert_le"])).total_seconds() / 3600
            periods = int(hours // 4)
            if periods > p.get("rollover_periodes", 0):
                add = (periods - p.get("rollover_periodes", 0)) * p["notionnel"] * F["rollover_short_pct_par_4h"] / 100
                p["rollover"] = p.get("rollover", 0) + add
                p["rollover_periodes"] = periods
                state["cash"] -= add; state["frais_cumules"] += add
        # sortie au temps
        age_h = (now_utc() - parse_iso(p["ouvert_le"])).total_seconds() / 3600
        if age_h >= p.get("duree_max_h", cfg["risque"]["duree_max_position_h"]) and t:
            px = t["bid"] * (1 - slip / 100) if p["side"] == "long" else t["ask"] * (1 + slip / 100)
            close_position(cfg, state, p, px, "durée maximale atteinte")


# ---------------------------------------------------------- ordres du comite
def open_position(cfg, state, prop, sizing):
    state["seq"] += 1
    pid = f"P{state['seq']:04d}"
    fee = sizing["frais_entree"]
    state["cash"] -= sizing["notionnel"] + fee
    state["frais_cumules"] += fee
    day = paris_day()
    if cfg.get("memecoins") and is_meme(cfg, prop["sym"]):  # l'entrée memecoin s'ajoute aux 3 entrées normales
        state.setdefault("entrees_meme_par_jour", {})[day] = state.get("entrees_meme_par_jour", {}).get(day, 0) + 1
    else:
        state["entrees_par_jour"][day] = state["entrees_par_jour"].get(day, 0) + 1
    if prop.get("strategie") == "OPP-1":
        state.setdefault("opp_par_jour", {})[day] = state.get("opp_par_jour", {}).get(day, 0) + 1
    p = {
        "id": pid, "sym": prop["sym"], "pair": pair_of(cfg, prop["sym"]), "side": prop["side"],
        "strategie": prop.get("strategie", "?"), "qty": sizing["qty"], "entry": rp(sizing["fill"]),
        "notionnel": sizing["notionnel"], "frais_entree": fee, "stop": float(prop["stop"]),
        "stop_initial": float(prop["stop"]), "tp": float(prop["tp"]), "risque_eur": sizing["risque_eur"],
        "rr_net": round(sizing["rr_net"], 2), "ouvert_le": iso(), "verifie_jusqu_a": iso(),
        "duree_max_h": min(float(prop.get("duree_max_h", cfg["risque"]["duree_max_position_h"])), 72,
                           *( [cfg["memecoins"]["duree_max_h"]] if cfg.get("memecoins") and is_meme(cfg, prop["sym"]) else [] )),
        "decision_id": prop["id"], "dernier_prix": sizing["fill"],
        **({"catalyseur": prop.get("catalyseur")} if prop.get("strategie") == "OPP-1" else {}),
    }
    state["positions"].append(p)
    log_event("Execution", "ouverture",
              f"{p['sym']} {p['side']} ouvert à {p['entry']} | {sizing['notionnel']:.2f} € engagés | stop {rp(p['stop'])} | objectif {rp(p['tp'])} | risque {sizing['risque_eur']:.2f} EUR",
              {"id": pid})
    return pid


def process_inbox(cfg, state, tk):
    os.makedirs(INBOX, exist_ok=True); os.makedirs(ARCHIVE, exist_ok=True)
    decisions = load("decisions.json", [])
    known = {d["id"] for d in decisions}
    for path in sorted(glob.glob(os.path.join(INBOX, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                prop = json.load(f)
        except Exception as e:
            log_event("Execution", "erreur", f"Fichier d'ordre illisible {os.path.basename(path)} : {e}")
            shutil.move(path, os.path.join(ARCHIVE, os.path.basename(path) + ".invalide"))
            continue
        prop.setdefault("id", os.path.basename(path)[:-5])
        if prop["id"] in known:
            shutil.move(path, os.path.join(ARCHIVE, os.path.basename(path)))
            continue
        if prop.get("action") == "ajouter_actif":
            add_asset(cfg, prop)
            shutil.move(path, os.path.join(ARCHIVE, os.path.basename(path)))
            known.add(prop["id"])
            continue
        if prop.get("action") == "agenda":
            add_agenda(prop)
            shutil.move(path, os.path.join(ARCHIVE, os.path.basename(path)))
            known.add(prop["id"])
            continue
        res = execute_decision(cfg, state, prop, tk)
        prop["resultat"] = res
        prop["traite_le"] = iso()
        decisions.append(prop)
        shutil.move(path, os.path.join(ARCHIVE, os.path.basename(path)))
    save("decisions.json", decisions[-500:])


def add_agenda(prop):
    """Ajoute des événements au calendrier des annonces (docs/data/calendrier.json)."""
    cal = load("calendrier.json", [])
    known = {(e["titre"], e["quand_utc"]) for e in cal}
    n = 0
    for e in prop.get("evenements", []):
        if not e.get("titre") or not e.get("quand_utc"):
            continue
        key = (e["titre"], e["quand_utc"])
        if key in known:
            continue
        cal.append({"titre": e["titre"], "quand_utc": e["quand_utc"], "impact": e.get("impact", "moyen"),
                    "actifs": e.get("actifs", []), "source": e.get("source", ""), "attendu": e.get("attendu", "")})
        known.add(key); n += 1
    limite = now_utc() - timedelta(hours=6)
    cal = [e for e in cal if parse_iso(e["quand_utc"]) > limite]
    cal.sort(key=lambda e: e["quand_utc"])
    save("calendrier.json", cal[-80:])
    if n:
        log_event("News & Macro", "agenda", f"{n} annonce(s) ajoutée(s) au calendrier")
    return {"statut": "execute", "ajoutes": n}


def add_asset(cfg, prop, dry=False):
    """Ajoute une crypto émergente à l'univers. Le moteur vérifie tout lui-même sur Kraken."""
    A = cfg.get("memecoins", {}).get("ajouts", {})
    sym = str(prop.get("sym", "")).upper().strip()
    problems = []
    if not re.fullmatch(r"[A-Z0-9]{2,12}", sym):
        return {"statut": "refuse", "motifs": ["Symbole invalide (2 à 12 lettres ou chiffres)."]}
    if not prop.get("raison") or not prop.get("source"):
        problems.append("Il faut une raison précise et une source (lien) pour ajouter un actif.")
    if sym in {a["sym"] for a in cfg["univers"]}:
        return {"statut": "refuse", "motifs": [f"{sym} est déjà dans l'univers."]}
    extra = load("univers_ajouts.json", [])
    if len(extra) >= A.get("max_total", 12):
        problems.append(f"Déjà {len(extra)} actifs ajoutés (maximum {A.get('max_total', 12)}).")
    jour = paris_day()
    n_jour = sum(1 for e in extra if paris_day(parse_iso(e["ajoute_le"])) == jour)
    if n_jour >= A.get("max_par_jour", 2):
        problems.append(f"Déjà {n_jour} ajouts aujourd'hui (maximum {A.get('max_par_jour', 2)}).")
    pair = str(prop.get("pair") or f"{sym}EUR").upper()
    alt = None
    if not problems:
        try:
            res = kraken("AssetPairs", {"pair": pair})
            v = next(iter(res.values()))
            alt = v.get("altname", pair)
            if v.get("quote") not in ("ZEUR", "EUR"):
                problems.append("La paire n'est pas cotée en euros sur Kraken.")
            if v.get("status", "online") != "online":
                problems.append(f"Paire non disponible (statut : {v.get('status')}).")
        except (KrakenError, StopIteration):
            problems.append(f"Paire {pair} introuvable sur Kraken.")
    if not problems and alt:
        tkr = tickers([{"sym": sym, "pair": alt, "nom": sym, "cat": "Emergent", "tier": "C"}]).get(sym)
        if not tkr:
            problems.append("Pas de prix Kraken pour cette paire.")
        else:
            if tkr["vol_eur"] < A.get("volume_24h_min_eur", 40000):
                problems.append(f"Volume 24 h trop faible ({tkr['vol_eur']:.0f} EUR < {A.get('volume_24h_min_eur', 40000)}).")
            if tkr["spread_pct"] > A.get("spread_max_pct", 0.5):
                problems.append(f"Spread trop large ({tkr['spread_pct']:.2f} %).")
    if problems:
        if not dry:
            log_event("Spécialiste memecoins", "ajout refusé", f"{sym} : " + " | ".join(problems))
        return {"statut": "refuse", "motifs": problems}
    if dry:
        return {"statut": "ok", "pair": alt}
    cat = prop.get("cat") if prop.get("cat") in ("Meme", "Emergent") else "Emergent"
    extra.append({"sym": sym, "pair": alt, "nom": prop.get("nom") or sym, "cat": cat, "tier": "C",
                  "ajoute_le": iso(), "raison": prop["raison"], "source": prop["source"]})
    save("univers_ajouts.json", extra)
    log_event("Spécialiste memecoins", "ajout actif",
              f"{sym} ajouté à l'univers (catégorie {cat}, budget memecoin) : {prop['raison']}")
    return {"statut": "execute", "pair": alt}


def execute_decision(cfg, state, prop, tk):
    action = prop.get("action", "none")
    risk_ai = (prop.get("agents", {}).get("risk_manager", {}) or {}).get("verdict", "").lower()
    if action == "none":
        log_event("Comité", "aucune action", prop.get("synthese", "Le comité a décidé de ne pas trader."))
        return {"statut": "aucune action"}
    if action == "agenda":
        return add_agenda(prop)
    if action == "open":
        label = f"{prop.get('sym')} {prop.get('side')}"
        if risk_ai != "valide":
            log_event("Risk Manager", "refus", f"{label} refusé par le Risk Manager IA : {prop.get('agents', {}).get('risk_manager', {}).get('motif', '')}")
            return {"statut": "refuse par le Risk Manager IA"}
        ok, reasons, sizing = check_open(cfg, state, prop, tk.get(prop.get("sym")), {s: t["last"] for s, t in tk.items()})
        if not ok:
            log_event("Garde-fou", "refus", f"{label} bloqué par les règles du code : " + " | ".join(reasons))
            return {"statut": "bloque par les garde-fous du code", "motifs": reasons}
        pid = open_position(cfg, state, prop, sizing)
        return {"statut": "execute", "position_id": pid, "prix": rp(sizing["fill"]), "qty": sizing["qty"],
                "notionnel": r2(sizing["notionnel"]), "risque_eur": r2(sizing["risque_eur"]),
                "rr_net": round(sizing["rr_net"], 2), "plafonne": sizing["plafonne"]}
    if action == "pending":
        return place_pending(cfg, state, prop, tk)
    if action == "cancel":
        before = len(state.get("ordres_attente", []))
        state["ordres_attente"] = [o for o in state.get("ordres_attente", []) if o["id"] != prop.get("ordre_id")]
        if len(state["ordres_attente"]) < before:
            log_event("Execution", "annulation", f"Ordre en attente {prop.get('ordre_id')} annulé par le comité")
            return {"statut": "execute"}
        return {"statut": "ignore", "motifs": ["Ordre en attente introuvable"]}
    pos = next((p for p in state["positions"] if p["id"] == prop.get("position_id") or p["sym"] == prop.get("sym")), None)
    if not pos:
        return {"statut": "ignore", "motifs": ["Position introuvable"]}
    t = tk.get(pos["sym"])
    if action == "close":
        if not t:
            return {"statut": "ignore", "motifs": ["Pas de prix"]}
        slip = cfg["frais"]["slippage_pct_par_tier"][tier_of(cfg, pos["sym"])]
        px = t["bid"] * (1 - slip / 100) if pos["side"] == "long" else t["ask"] * (1 + slip / 100)
        tr = close_position(cfg, state, pos, px, "clôture décidée par le comité")
        return {"statut": "execute", "pnl_net": tr["pnl_net"]}
    if action == "tighten_stop":
        new = float(prop["stop"])
        tighter = new > pos["stop"] if pos["side"] == "long" else new < pos["stop"]
        valid = (new < t["bid"]) if pos["side"] == "long" else (new > t["ask"])
        if not (tighter and valid):
            return {"statut": "refuse", "motifs": ["Un stop ne peut que se resserrer et doit rester du bon côté du prix."]}
        old = pos["stop"]; pos["stop"] = new
        log_event("Execution", "stop", f"{pos['sym']} : stop resserré de {rp(old)} a {rp(new)}")
        return {"statut": "execute"}
    if action == "fermer_si_positif":
        pos["fermer_si_positif"] = True
        pos["seuil_gain_eur"] = float(prop.get("seuil_gain_eur", 0.05))
        log_event("Execution", "consigne", f"{pos['sym']} : fermeture automatique dès que le gain net dépasse {pos['seuil_gain_eur']:.2f} € (consigne de Tom).")
        return {"statut": "execute"}
    if action == "set_target":
        new = float(prop["tp"])
        cost = costs_roundtrip_pct(cfg, pos["sym"]) / 100
        short = pos["side"] == "short"
        closer = new > pos["tp"] if short else new < pos["tp"]
        profit_side = new < pos["entry"] * (1 - cost) if short else new > pos["entry"] * (1 + cost)
        valid = (new < t["ask"] * 0.997) if short else (new > t["bid"] * 1.003)
        if not (closer and profit_side and valid):
            return {"statut": "refuse", "motifs": ["Un objectif ne peut que se rapprocher, rester du côté du gain (frais compris) et à au moins 0,3 % du prix actuel."]}
        old = pos["tp"]; pos["tp"] = new
        log_event("Execution", "objectif", f"{pos['sym']} : objectif rapproché de {rp(old)} à {rp(new)}")
        return {"statut": "execute", "ancien_objectif": old, "nouvel_objectif": new}
    return {"statut": "ignore", "motifs": [f"Action inconnue : {action}"]}


# ------------------------------------------------------- ordres en attente
def place_pending(cfg, state, prop, tk):
    """Ordre conditionnel : le moteur ouvre la position quand le prix atteint le déclencheur."""
    t = tk.get(prop.get("sym"))
    if not t:
        return {"statut": "ignore", "motifs": ["Pas de prix pour cet actif"]}
    trig = float(prop["declencheur"]); kind = prop.get("type_ordre", "stop")
    side = prop.get("side")
    test = dict(prop, entry_ref=trig)
    test.pop("atr", None)
    # contrôle à l'avance, comme si le prix était au déclencheur
    ok, reasons, _ = check_open(cfg, state, dict(test, sym=prop["sym"]),
                                {**t, "bid": trig, "ask": trig, "last": trig}, {s: x["last"] for s, x in tk.items()})
    reasons = [r for r in reasons if "entrées aujourd'hui" not in r and "positions ouvertes" not in r]
    if reasons:
        log_event("Garde-fou", "refus", f"Ordre en attente {prop['sym']} refusé : " + " | ".join(reasons))
        return {"statut": "bloque par les garde-fous du code", "motifs": reasons}
    if len(state.get("ordres_attente", [])) >= 4:
        return {"statut": "bloque par les garde-fous du code", "motifs": ["Déjà 4 ordres en attente."]}
    state["seq"] += 1
    o = {"id": f"O{state['seq']:04d}", "sym": prop["sym"], "side": side, "type_ordre": kind,
         "declencheur": trig, "stop": float(prop["stop"]), "tp": float(prop["tp"]),
         "strategie": prop.get("strategie", "TPB-1"), "duree_max_h": prop.get("duree_max_h", 24),
         "place_le": iso(), "expire_le": iso(now_utc() + timedelta(hours=min(float(prop.get("expire_h", 4)), 24))),
         "decision_id": prop["id"], "agents": prop.get("agents"), "catalyseur": prop.get("catalyseur"),
         "groupe": prop.get("groupe"), "evenement": prop.get("evenement"), "verifie_le": iso()}
    state.setdefault("ordres_attente", []).append(o)
    sens = "vend à découvert" if side == "short" else "achète"
    cond = ("passe sous" if side == "short" else "passe au-dessus de") if kind == "stop" else ("remonte à" if side == "short" else "redescend à")
    log_event("Execution", "ordre en attente", f"Ordre {o['id']} : on {sens} {o['sym']} si le prix {cond} {rp(trig)} (valable jusqu'à {o['expire_le'][11:16]} UTC)")
    return {"statut": "execute", "ordre_id": o["id"]}


def _pending_hit(o, c):
    """Prix d'exécution théorique si la bougie c déclenche l'ordre o, sinon None.
    Si le prix ouvre en 'gap' au-delà du déclencheur, on est exécuté au prix d'ouverture (pas au déclencheur)."""
    trig = o["declencheur"]
    if o["type_ordre"] == "stop":
        if o["side"] == "short":
            return min(trig, c["o"]) if c["l"] <= trig else None
        return max(trig, c["o"]) if c["h"] >= trig else None
    if o["side"] == "short":
        return max(trig, c["o"]) if c["h"] >= trig else None
    return min(trig, c["o"]) if c["l"] <= trig else None


def process_pending(cfg, state, tk):
    """Ordres en attente, vérifiés minute par minute (bougies 1 min) depuis la dernière vérification.
    Autour d'une annonce, un ordre « stop » est exécuté moins bien que prévu (glissement d'annonce).
    Ordres jumeaux (même 'groupe') : dès que l'un se déclenche, l'autre est annulé."""
    slip_ann = float(cfg.get("ordres_attente", {}).get("slippage_annonce_pct", 0.30))
    triggered, keep = [], []
    for o in state.get("ordres_attente", []):
        t = tk.get(o["sym"])
        if now_utc() >= parse_iso(o["expire_le"]):
            log_event("Execution", "expiration", f"Ordre en attente {o['id']} ({o['sym']}) expiré sans être déclenché")
            continue
        if not t:
            keep.append(o); continue
        since = parse_iso(o.get("verifie_le") or o["place_le"]).timestamp()
        hit = None
        try:
            candles = [c for c in ohlc(pair_of(cfg, o["sym"]), 1, since - 60) if c["t"] >= since - 60]
            time.sleep(1.0)
            closed = candles[:-1]
            for c in closed:
                if c["t"] + 60 <= since:
                    continue
                px = _pending_hit(o, c)
                if px is not None:
                    hit = (c["t"] + 60, px, c); break
            if not hit:
                o["verifie_le"] = iso(now_utc().fromtimestamp(closed[-1]["t"] + 60, tz=now_utc().tzinfo)) if closed else o.get("verifie_le", o["place_le"])
                # la bougie en cours : on regarde aussi le dernier prix (déclenchement en direct)
                cur = candles[-1] if candles else None
                if cur and cur["t"] + 60 > since:
                    px = _pending_hit(o, cur)
                    if px is not None:
                        hit = (int(now_utc().timestamp()), px, cur)
            if not hit:  # filet de sécurité : dernier prix en direct (les bougies peuvent avoir du retard)
                last = t["last"]
                px = _pending_hit(o, {"o": last, "h": last, "l": last})
                if px is not None:
                    hit = (int(now_utc().timestamp()), px, {"o": last, "h": last, "l": last})
        except KrakenError as e:
            log_event("Execution", "erreur", f"Bougies 1 min indisponibles pour l'ordre {o['id']} : {e}")
            last = t["last"]
            fake = {"o": last, "h": last, "l": last}
            px = _pending_hit(o, fake)
            if px is not None:
                hit = (int(now_utc().timestamp()), px, fake)
        if hit:
            triggered.append((hit, o))
        else:
            keep.append(o)
    # ordres déclenchés : le plus tôt d'abord ; son jumeau est annulé
    triggered.sort(key=lambda x: (x[0][0], abs(x[0][1] - x[0][2]["o"])))
    cancelled = set()
    for (when_ts, px, c), o in triggered:
        if o["id"] in cancelled:
            continue
        for (_, _), o2 in [((0, 0), x[1]) for x in triggered]:
            if o2 is not o and o.get("groupe") and o2.get("groupe") == o["groupe"] and o2["id"] not in cancelled:
                cancelled.add(o2["id"])
                log_event("Execution", "annulation", f"Ordre {o2['id']} ({o2['sym']}) annulé : son jumeau {o['id']} s'est déclenché")
        for o2 in list(keep):
            if o.get("groupe") and o2.get("groupe") == o["groupe"]:
                keep.remove(o2)
                log_event("Execution", "annulation", f"Ordre {o2['id']} ({o2['sym']}) annulé : son jumeau {o['id']} s'est déclenché")
        t = tk[o["sym"]]
        fill = px
        extra = slip_ann if (o.get("evenement") and o["type_ordre"] == "stop") else 0.0
        fill = px * (1 + extra / 100) if o["side"] == "long" else px * (1 - extra / 100)
        when = iso(now_utc().fromtimestamp(when_ts, tz=now_utc().tzinfo))
        prop = {"id": o["decision_id"] + "-" + o["id"], "action": "open", "sym": o["sym"], "side": o["side"],
                "strategie": o["strategie"], "stop": o["stop"], "tp": o["tp"], "duree_max_h": o["duree_max_h"],
                "agents": o.get("agents") or {}, "catalyseur": o.get("catalyseur")}
        ok, reasons, sizing = check_open(cfg, state, prop, {**t, "bid": fill, "ask": fill, "last": fill},
                                         {s: x["last"] for s, x in tk.items()})
        if ok:
            pid = open_position(cfg, state, prop, sizing)
            pos = state["positions"][-1]
            pos["ouvert_le"] = when
            pos["verifie_jusqu_a"] = when  # on rejoue les minutes suivantes : un retournement brutal touche le stop
            note = f" (glissement d'annonce +{extra:.2f} %)" if extra else ""
            log_event("Execution", "déclenchement", f"Ordre {o['id']} déclenché : {o['sym']} {o['side']} ouvert à {rp(pos['entry'])}{note} ({pid})")
        else:
            log_event("Garde-fou", "refus", f"Ordre {o['id']} déclenché mais bloqué : " + " | ".join(reasons))
    state["ordres_attente"] = [o for o in keep if o["id"] not in cancelled]


def urgences(cfg, state, sig, veille_data):
    """Liste des raisons de réunir le comité en urgence (lue par la veille d'urgence)."""
    out = []
    held = {p["sym"] for p in state.get("positions", [])}
    for a in (veille_data or {}).get("alertes", []):
        if (now_utc() - parse_iso(a["t"])).total_seconds() < 1200 and (a.get("position") == "contre nous" or abs(a["variation_pct"]) >= 4):
            out.append(f"Mouvement brusque {a['sym']} {a['variation_pct']} % en {a['horizon']}" + (f", position {a['position']}" if a.get("position") else ""))
    for n in (veille_data or {}).get("actus", []):
        if n.get("score", 0) >= 5 and (now_utc() - parse_iso(n["t"])).total_seconds() < 1800:
            out.append(f"Actualité majeure : {n['titre'][:120]}")
        elif n.get("score", 0) >= 3 and set(n.get("actifs", [])) & held and (now_utc() - parse_iso(n["t"])).total_seconds() < 1800:
            out.append(f"Actualité sur une position ouverte : {n['titre'][:120]}")
    try:
        for e in load("calendrier.json", []):
            dt = (parse_iso(e["quand_utc"]) - now_utc()).total_seconds() / 60
            if e.get("impact") == "haut" and 0 < dt <= 120:
                out.append(f"Annonce à fort impact dans {round(dt)} min : {e['titre']}")
    except Exception:
        pass
    strong = [c for c in (sig or {}).get("candidats", []) if c["score"] >= 70 and c["rr_net"] >= 2.0 and c["sym"] not in held]
    if strong:
        out.append("Signal fort : " + ", ".join(f"{c['sym']} {c['side']} (RR {c['rr_net']})" for c in strong[:3]))
    return out[:8]


# ---------------------------------------------------------- trader de garde
def guard_protect(cfg, state, tk):
    """Gestion pro des positions : stop au prix d'entrée à +1R, profit verrouillé à +2R. Le stop ne recule jamais."""
    G = cfg.get("trader_de_garde", {})
    if not G.get("actif"):
        return
    P = G.get("protection", {})
    fee = cfg["frais"]["taker_pct"] / 100
    for p in state["positions"]:
        t = tk.get(p["sym"])
        if not t or p.get("runner"):
            continue
        risk_px = abs(p["entry"] - p["stop_initial"])
        if risk_px <= 0:
            continue
        px = t["last"]
        gain_R = ((px - p["entry"]) if p["side"] == "long" else (p["entry"] - px)) / risk_px
        new = None; why = ""
        if gain_R >= P.get("seuil_verrouillage_R", 2.0):
            lock = P.get("verrouille_R", 1.0) * risk_px
            new = p["entry"] + lock if p["side"] == "long" else p["entry"] - lock
            why = f"+{gain_R:.1f}R atteint : profit de {P.get('verrouille_R', 1.0)}R verrouillé"
        elif gain_R >= P.get("seuil_breakeven_R", 1.0):
            be = p["entry"] * (1 + 2 * fee) if p["side"] == "long" else p["entry"] * (1 - 2 * fee)
            new = be; why = f"+{gain_R:.1f}R atteint : stop remonté au prix d'entrée (plus de perte possible)"
        if new is None:
            continue
        tighter = new > p["stop"] if p["side"] == "long" else new < p["stop"]
        valid = new < t["bid"] if p["side"] == "long" else new > t["ask"]
        if tighter and valid:
            old = p["stop"]; p["stop"] = new
            log_event("Trader de garde", "protection", f"{p['sym']} : stop {rp(old)} → {rp(new)}. {why}.")


def guard_entry(cfg, state, tk, sig):
    """Entrée seule sur un signal exceptionnel du scanner, risque réduit, une fois par jour maximum."""
    G = cfg.get("trader_de_garde", {})
    if not G.get("actif") or state.get("coupe_circuit"):
        return
    E = G.get("entree_auto", {})
    day = paris_day()
    if state.get("garde_par_jour", {}).get(day, 0) >= E.get("max_par_jour", 1):
        return
    held = {p["sym"] for p in state["positions"]}
    pending = {o["sym"] for o in state.get("ordres_attente", [])}
    for c in sig.get("candidats", []):
        if c["score"] < E.get("score_min", 75) or c["rr_net"] < E.get("rr_net_min", 2.5) or c.get("alertes"):
            continue
        if c["sym"] in held or c["sym"] in pending:
            continue
        prop = {"id": f"G-{now_utc().strftime('%Y%m%d-%H%M%S')}", "action": "open", "sym": c["sym"], "side": c["side"],
                "strategie": c["strategie"], "entry_ref": c["entry_ref"], "atr": c["atr"], "stop": c["stop"], "tp": c["tp"],
                "duree_max_h": 24, "risque_pct_override": E.get("risque_par_trade_pct", 0.5),
                "agents": {"trader_de_garde": {"avis": "favorable", "resume": c["pourquoi"]},
                           "risk_manager": {"verdict": "valide", "motif": "Règles automatiques du trader de garde (risque 0,5 %)."}},
                "synthese": f"Le trader de garde a agi seul : signal {c['strategie']} très fort sur {c['sym']} (score {c['score']}, RR net {c['rr_net']}). À contrôler à la prochaine réunion du comité."}
        ok, reasons, sizing = check_open(cfg, state, prop, tk.get(c["sym"]), {s: x["last"] for s, x in tk.items()})
        if not ok:
            continue
        pid = open_position(cfg, state, prop, sizing)
        state.setdefault("garde_par_jour", {})[day] = state.get("garde_par_jour", {}).get(day, 0) + 1
        prop["resultat"] = {"statut": "execute", "position_id": pid, "prix": rp(sizing["fill"]), "risque_eur": r2(sizing["risque_eur"])}
        prop["cree_le"] = prop["traite_le"] = iso()
        decisions = load("decisions.json", []); decisions.append(prop); save("decisions.json", decisions[-500:])
        log_event("Trader de garde", "entrée", f"Entrée seule : {c['sym']} {c['side']} ({c['strategie']}, score {c['score']}, RR net {c['rr_net']}), risque {sizing['risque_eur']:.2f} €.")
        return


# ----------------------------------------------------------------- scanner
DIAG = []


def compact(cs, n):
    return [[c["t"], rp(c["o"]), rp(c["h"]), rp(c["l"]), rp(c["c"]), round(c["v"], 4)] for c in cs[-n:]]


def scan(cfg):
    inds, cands = {}, []
    btc_trend = "neutre"
    candles, books = {}, {}
    for a in cfg["univers"]:
        try:
            c = ohlc(a["pair"], 15)
            ind = analyse(c)
            if not ind:
                DIAG.append(f"{a['sym']}: {len(c)} bougies")
            candles[a["sym"]] = {"15": compact(c, 300)}
        except Exception as e:
            DIAG.append(f"{a['sym']}: {type(e).__name__} {str(e)[:120]}")
            ind = None
        time.sleep(1.1)
        if os.environ.get("TD_SNAPSHOT"):  # archive bougies et carnets (inutile quand la page lit Kraken en direct)
            for tf, n in ((60, 400), (1440, 200)):
                try:
                    candles.setdefault(a["sym"], {})[str(tf)] = compact(ohlc(a["pair"], tf), n)
                except KrakenError:
                    pass
                time.sleep(1.1)
            try:
                d = kraken("Depth", {"pair": a["pair"], "count": 12})
                b = list(d.values())[0]
                books[a["sym"]] = {"bids": [[float(x[0]), float(x[1])] for x in b["bids"]],
                                   "asks": [[float(x[0]), float(x[1])] for x in b["asks"]]}
            except Exception:
                pass
            time.sleep(1.1)
        if not ind:
            continue
        if a["sym"] == "BTC":
            btc_trend = ind["trend_1h"]
        inds[a["sym"]] = {k: (rp(v) if isinstance(v, float) else v) for k, v in ind.items()}
    for sym, ind in inds.items():
        cands += signals(cfg, sym, ind, btc_trend)
    cands.sort(key=lambda s: -s["score"])
    if os.environ.get("TD_SNAPSHOT"):
        save("candles.json", {"t": iso(), "candles": candles, "carnets": books}, compact=True)
    return {"t": iso(), "btc_trend_1h": btc_trend, "candidats": cands, "indicateurs": inds}


def sentiment(market):
    prev = market.get("sentiment", {})
    if prev.get("t") and (now_utc() - parse_iso(prev["t"])).total_seconds() < 3500:
        return prev
    out = {"t": iso()}
    try:
        with urllib.request.urlopen("https://api.alternative.me/fng/?limit=1", timeout=15) as r:
            d = json.loads(r.read().decode())["data"][0]
        out["fear_greed"] = int(d["value"]); out["fear_greed_label"] = d["value_classification"]
    except Exception as e:
        out["fear_greed_erreur"] = str(e)[:120]
    try:
        req = urllib.request.Request("https://api.coingecko.com/api/v3/global", headers={"User-Agent": "trading-desk-paper"})
        with urllib.request.urlopen(req, timeout=15) as r:
            g = json.loads(r.read().decode())["data"]
        out["dominance_btc"] = round(g["market_cap_percentage"]["btc"], 2)
        out["capi_totale_var_24h"] = round(g.get("market_cap_change_percentage_24h_usd", 0), 2)
    except Exception as e:
        out["dominance_erreur"] = str(e)[:120]
    return out


# -------------------------------------------------------------------- main
def main():
    cfg = config()
    from core import ROOT, DATA
    def write_ui_config():
        with open(os.path.join(os.path.dirname(DATA), "config.json"), "w", encoding="utf-8") as fh:
            json.dump(config(), fh, ensure_ascii=False, indent=1)
    write_ui_config()
    do_scan = "--no-scan" not in sys.argv
    state = load("state.json", None) or new_state(cfg)
    status = {"t": iso(), "version": ENGINE_VERSION, "mode": "PAPER_ONLY", "ok": True, "erreurs": []}
    try:
        tk = tickers(cfg["univers"])
    except Exception as e:
        status.update(ok=False, erreurs=[f"Prix Kraken indisponibles : {e}"])
        save("status.json", status); log_event("Moteur", "erreur", status["erreurs"][0])
        return 1
    prices = {s: t["last"] for s, t in tk.items()}
    day = paris_day()
    state.setdefault("equity_debut_jour", {})
    if day not in state["equity_debut_jour"]:
        state["equity_debut_jour"][day] = r2(equity(state, prices))
        state["equity_debut_jour"] = dict(list(state["equity_debut_jour"].items())[-60:])

    manage_positions(cfg, state, tk)
    process_inbox(cfg, state, tk)
    process_pending(cfg, state, tk)
    write_ui_config()  # un actif ajouté pendant ce passage apparaît tout de suite dans l'application
    guard_protect(cfg, state, tk)

    eq = equity(state, prices)
    state["pic_equity"] = max(state["pic_equity"], eq)
    dd = (state["pic_equity"] - eq) / state["pic_equity"] * 100
    if dd >= cfg["risque"]["drawdown_coupe_circuit_pct"] and not state["coupe_circuit"]:
        state["coupe_circuit"] = True
        log_event("Garde-fou", "coupe-circuit", f"Drawdown {dd:.1f} % : nouvelles entrées suspendues jusqu'à la revue.")
    state["maj"] = iso()
    save("state.json", state)

    hist = load("equity.json", [])
    hist.append({"t": iso(), "eq": r2(eq), "cash": r2(state["cash"]), "n": len(state["positions"])})
    if len(hist) > 6000:  # on garde le detail recent, on allege l'ancien
        hist = hist[:3000:2] + hist[3000:]
    save("equity.json", hist)

    market = load("market.json", {})
    market.update({"t": iso(), "tickers": tk, "sentiment": sentiment(market)})
    try:
        import veille
        veille.run(cfg, tk, market, state)
    except Exception as e:  # la veille ne doit jamais bloquer le moteur
        log_event("Veille", "erreur", f"Veille indisponible : {str(e)[:150]}")
    save("market.json", market)

    if do_scan:
        sig = scan(cfg)
        save("signals.json", sig)
        try:
            guard_entry(cfg, state, tk, sig)
            save("state.json", state)
        except Exception as e:
            log_event("Trader de garde", "erreur", str(e)[:150])
        n = len(sig["candidats"])
        top = ", ".join(f"{c['sym']} {c['side']} ({c['strategie']}, {c['score']})" for c in sig["candidats"][:3])
        prev = load("activite.json", [])
        last_scan = next((e for e in reversed(prev) if e["agent"] == "Scanner"), None)
        msg = f"{len(sig['indicateurs'])} actifs analysés, {n} signal(aux)" + (f" : {top}" if n else ". Rien qui respecte les règles.")
        if not last_scan or last_scan["msg"] != msg:
            log_event("Scanner", "scan", msg)

    status["equity"] = r2(eq); status["drawdown_pct"] = round(dd, 2)
    try:
        status["urgences"] = urgences(cfg, state, load("signals.json", {}), load("veille.json", {}))
    except Exception as e:
        status["urgences_erreur"] = str(e)[:120]
    if DIAG:
        status["diagnostic_scanner"] = DIAG[:30]
    save("status.json", status)
    print(json.dumps({"equity": r2(eq), "cash": r2(state["cash"]), "positions": len(state["positions"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
