"""Agent de veille : actualites (flux RSS gratuits) + alertes de mouvements brusques.

Tourne a chaque passage du moteur (toutes les 5 min). Gratuit, sans IA :
il trie et signale. Le comite d'agents lit ces alertes a chaque reunion.
"""
import email.utils
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from core import iso, load, log_event, now_utc, parse_iso, save

FEEDS = [
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Investing.com", "https://www.investing.com/rss/news.rss"),
]
GNEWS = ["crypto market", "bitcoin", "stock market today", "Federal Reserve", "Nasdaq stocks",
         "crypto hack exploit", "SEC crypto"]

# mots-cles -> (poids, etiquette)
KEYWORDS = [
    (r"\bhack(ed|ers?)?\b|exploit|drained|stolen", 3, "piratage"),
    (r"bankrupt|insolven|faillite|collapse", 3, "faillite"),
    (r"\bSEC\b|lawsuit|sues?\b|charged|indict|ban(s|ned)?\b", 2, "régulation"),
    (r"\bETF\b", 2, "ETF"),
    (r"liquidat", 2, "liquidations"),
    (r"crash|plunge|tumble|sell-?off|dump|chute|s'effondre", 2, "chute"),
    (r"surge|soar|rall(y|ies)|skyrocket|jump|bondit|flamb", 2, "hausse"),
    (r"\bFed\b|Powell|rate (cut|hike)|interest rate|FOMC|BCE|ECB|Lagarde", 2, "banque centrale"),
    (r"\bCPI\b|inflation|jobs report|payrolls|PPI|GDP", 1, "macro"),
    (r"tariff|sanction|war\b|guerre|missile|invasion", 2, "géopolitique"),
    (r"earnings|guidance|résultats|revenue miss|beats? estimates", 2, "résultats"),
    (r"whale|baleine", 1, "baleines"),
]
SEUIL_15M = {"crypto": 2.5, "action": 1.5}
SEUIL_1H = {"crypto": 5.0, "action": 3.0}


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 trading-desk-paper"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _parse(xml, source):
    out = []
    for item in re.findall(r"<item\b.*?</item>", xml, flags=re.S)[:40]:
        def tag(t):
            m = re.search(rf"<{t}[^>]*>(.*?)</{t}>", item, flags=re.S)
            if not m:
                return ""
            v = m.group(1).strip()
            v = re.sub(r"^<!\[CDATA\[|\]\]>$", "", v).strip()
            return html.unescape(re.sub(r"<[^>]+>", "", v)).strip()
        title, link, pub = tag("title"), tag("link"), tag("pubDate")
        src = tag("source") or source
        try:
            dt = email.utils.parsedate_to_datetime(pub).astimezone(timezone.utc)
        except Exception:
            dt = now_utc()
        if title:
            out.append({"titre": title, "lien": link, "source": src, "t": iso(dt)})
    return out


def _tag(item, univers):
    txt = item["titre"]
    score, labels = 0, []
    for rx, w, lab in KEYWORDS:
        if re.search(rx, txt, flags=re.I):
            score += w; labels.append(lab)
    actifs = []
    for a in univers:
        if a["sym"] == "TRUMP":  # le memecoin, pas le president
            if re.search(r"\$TRUMP|TRUMP (coin|token)|meme ?coin", txt, flags=re.I):
                actifs.append("TRUMP")
            continue
        names = {a["sym"], a["nom"].split(" (")[0]}
        if a["sym"] == "BTC":
            names |= {"Bitcoin"}
        if a["sym"] == "ETH":
            names |= {"Ether", "Ethereum"}
        for n in names:
            if len(n) >= 3 and re.search(rf"\b{re.escape(n)}\b", txt, flags=re.I if len(n) > 4 else 0):
                actifs.append(a["sym"]); break
    if actifs:
        score += 1
    item.update(score=score, themes=labels, actifs=actifs)
    return item


def news(cfg):
    items, errs = [], []
    for name, url in FEEDS:
        try:
            items += _parse(_get(url), name)
        except Exception as e:
            errs.append(f"{name}: {str(e)[:60]}")
    for q in GNEWS:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
        try:
            items += _parse(_get(url), "Google Actualités")[:15]
        except Exception as e:
            errs.append(f"Google ({q}): {str(e)[:60]}")
    seen, out = set(), []
    cutoff = time.time() - 24 * 3600
    for it in sorted(items, key=lambda x: x["t"], reverse=True):
        key = re.sub(r"\W+", "", it["titre"].lower())[:80]
        if key in seen or parse_iso(it["t"]).timestamp() < cutoff:
            continue
        seen.add(key)
        out.append(_tag(it, cfg["univers"]))
    return out[:150], errs


def price_alerts(cfg, tk, market, state):
    """Compare les prix a ceux d'il y a ~15 min et ~1 h (historique garde dans market.json)."""
    hist = market.get("historique_prix", [])
    now = time.time()
    hist.append({"ts": now, "p": {s: t["last"] for s, t in tk.items()}})
    hist = [h for h in hist if h["ts"] > now - 2 * 3600][-30:]
    market["historique_prix"] = hist

    def ref(age):
        cand = [h for h in hist if h["ts"] <= now - age]
        return cand[-1]["p"] if cand else None

    p15, p60 = ref(14 * 60), ref(55 * 60)
    classe = {a["sym"]: ("action" if a.get("classe") == "action" else "crypto") for a in cfg["univers"]}
    held = {p["sym"]: p["side"] for p in state.get("positions", [])}
    alerts = []
    for sym, t in tk.items():
        c = classe.get(sym, "crypto")
        for refp, horizon, seuil in ((p15, "15 min", SEUIL_15M[c]), (p60, "1 h", SEUIL_1H[c])):
            if not refp or sym not in refp or not refp[sym]:
                continue
            chg = (t["last"] / refp[sym] - 1) * 100
            if abs(chg) >= seuil:
                a = {"sym": sym, "horizon": horizon, "variation_pct": round(chg, 2), "prix": t["last"], "t": iso()}
                if sym in held:
                    contre = (held[sym] == "long" and chg < 0) or (held[sym] == "short" and chg > 0)
                    a["position"] = "contre nous" if contre else "en notre faveur"
                alerts.append(a)
                break
    return alerts


def run(cfg, tk, market, state):
    v = load("veille.json", {"actus": [], "alertes": []})
    last = v.get("t_actus")
    # actualites toutes les 10 min (les flux ne changent pas plus vite)
    if not last or (now_utc() - parse_iso(last)).total_seconds() > 540:
        actus, errs = news(cfg)
        if actus:
            old = {a["titre"] for a in v.get("actus", [])}
            fresh = [a for a in actus if a["titre"] not in old and a["score"] >= 4]
            for a in fresh[:3]:
                log_event("Veille", "actu", f"[{', '.join(a['themes']) or 'actu'}] {a['titre']} ({a['source']})",
                          {"lien": a["lien"], "actifs": a["actifs"]})
            v["actus"] = actus
        v["t_actus"] = iso(); v["erreurs_sources"] = errs
    alerts = price_alerts(cfg, tk, market, state)
    prev = {(a["sym"], a["horizon"]) for a in v.get("alertes", []) if (now_utc() - parse_iso(a["t"])).total_seconds() < 3600}
    for a in alerts:
        if (a["sym"], a["horizon"]) not in prev:
            sign = "+" if a["variation_pct"] > 0 else ""
            extra = f" — position {a['position']}" if a.get("position") else ""
            log_event("Veille", "alerte", f"{a['sym']} {sign}{a['variation_pct']} % en {a['horizon']}{extra}")
    keep = [a for a in v.get("alertes", []) if (now_utc() - parse_iso(a["t"])).total_seconds() < 6 * 3600]
    keep = [a for a in keep if (a["sym"], a["horizon"]) not in {(b["sym"], b["horizon"]) for b in alerts}]
    v["alertes"] = (alerts + keep)[:40]
    v["t"] = iso()
    save("veille.json", v)
    return v
