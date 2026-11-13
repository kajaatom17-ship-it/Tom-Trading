"""Trading Desk IA - noyau du moteur de paper trading.

Regle absolue : ce code n'envoie JAMAIS d'ordre reel. Il n'utilise que l'API
publique de Kraken (lecture des prix), sans cle API.
"""
import json
import math
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("TD_DATA") or os.path.join(ROOT, "docs", "data")
INBOX = os.path.join(DATA, "inbox")
ARCHIVE = os.path.join(os.environ.get("TD_ARCHIVE") or os.path.join(ROOT, "archive"), "inbox")
KRAKEN = "https://api.kraken.com/0/public/"

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    PARIS = timezone(timedelta(hours=1))


# ----------------------------------------------------------------- utilitaires
def now_utc():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or now_utc()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def paris_day(dt=None):
    return (dt or now_utc()).astimezone(PARIS).strftime("%Y-%m-%d")


def load(name, default):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(name, obj, compact=False):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def config():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def r2(x):
    return round(x, 2)


def rp(x):
    """Arrondi de prix lisible quelle que soit l'echelle (BTC ou PEPE)."""
    if x == 0:
        return 0
    digits = max(2, 6 - int(math.floor(math.log10(abs(x)))))
    return round(x, min(digits, 12))


# ---------------------------------------------------------------- API Kraken
class KrakenError(Exception):
    pass


def kraken(method, params=None, retries=3):
    url = KRAKEN + method
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "trading-desk-paper/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode())
            if d.get("error"):
                last = KrakenError(";".join(d["error"]))
                if any("Rate limit" in e or "Too many" in e for e in d["error"]):
                    time.sleep(3 * (attempt + 1))
                    continue
                raise last
            return d["result"]
        except KrakenError:
            raise
        except Exception as e:  # reseau, timeout, JSON
            last = e
            time.sleep(2 * (attempt + 1))
    raise KrakenError(f"{method}: {last}")


def tickers(universe):
    """Retourne {sym: {bid, ask, last, open, high, low, vol_eur, spread_pct, chg_pct}}."""
    alt = {a["pair"]: a["sym"] for a in universe}
    names = kraken("AssetPairs", {"pair": ",".join(alt)})
    canon = {k: alt[v["altname"]] for k, v in names.items() if v["altname"] in alt}
    res = kraken("Ticker", {"pair": ",".join(alt)})
    out = {}
    for k, v in res.items():
        sym = canon.get(k)
        if not sym:
            continue
        last = float(v["c"][0]); bid = float(v["b"][0]); ask = float(v["a"][0])
        op = float(v["o"])
        out[sym] = {
            "bid": bid, "ask": ask, "last": last, "open": op,
            "high": float(v["h"][1]), "low": float(v["l"][1]),
            "vol_eur": r2(float(v["v"][1]) * float(v["p"][1])),
            "spread_pct": round((ask - bid) / last * 100, 4) if last else 99,
            "chg_pct": round((last / op - 1) * 100, 2) if op else 0,
        }
    return out


def ohlc(pair, interval, since=None):
    """Bougies Kraken : liste de dicts t,o,h,l,c,v (la derniere est en cours)."""
    p = {"pair": pair, "interval": interval}
    if since:
        p["since"] = int(since)
    res = kraken("OHLC", p)
    key = [k for k in res if k != "last"][0]
    return [{"t": int(c[0]), "o": float(c[1]), "h": float(c[2]), "l": float(c[3]),
             "c": float(c[4]), "v": float(c[6])} for c in res[key]]


# --------------------------------------------------------------- indicateurs
def ema(values, n):
    if not values:
        return []
    k = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return [50] * len(closes)
    gains, losses = [0.0], [0.0]
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains[1:n + 1]) / n; al = sum(losses[1:n + 1]) / n
    out = [50] * (n + 1)
    out[n] = 100 - 100 / (1 + ag / al) if al else 100
    for i in range(n + 1, len(closes)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out.append(100 - 100 / (1 + ag / al) if al else 100)
    return out


def atr(c, n=14):
    trs = [c[0]["h"] - c[0]["l"]]
    for i in range(1, len(c)):
        trs.append(max(c[i]["h"] - c[i]["l"], abs(c[i]["h"] - c[i - 1]["c"]), abs(c[i]["l"] - c[i - 1]["c"])))
    out = [trs[0]]
    for t in trs[1:]:
        out.append((out[-1] * (n - 1) + t) / n)
    return out


def macd_hist(closes):
    e12, e26 = ema(closes, 12), ema(closes, 26)
    line = [a - b for a, b in zip(e12, e26)]
    sig = ema(line, 9)
    return [a - b for a, b in zip(line, sig)]


def aggregate(candles, factor):
    """Agrege des bougies (ex. 4 x 15 min = 1 h), aligne sur l'horloge."""
    out, bucket = [], []
    span = candles[1]["t"] - candles[0]["t"] if len(candles) > 1 else 900
    size = span * factor
    for c in candles:
        if bucket and (c["t"] // size) != (bucket[0]["t"] // size):
            out.append(_merge(bucket)); bucket = []
        bucket.append(c)
    if bucket:
        out.append(_merge(bucket))
    return out


def _merge(b):
    return {"t": b[0]["t"], "o": b[0]["o"],
            "h": max(x["h"] for x in b), "l": min(x["l"] for x in b), "c": b[-1]["c"],
            "v": sum(x["v"] for x in b)}


# ------------------------------------------------------------- portefeuille
def new_state(cfg):
    return {
        "mode": "PAPER_ONLY",
        "devise": "EUR",
        "capital_initial": cfg["capital_initial_eur"],
        "cash": float(cfg["capital_initial_eur"]),
        "positions": [],
        "frais_cumules": 0.0,
        "pnl_realise": 0.0,
        "pic_equity": float(cfg["capital_initial_eur"]),
        "entrees_par_jour": {},
        "coupe_circuit": False,
        "cree_le": iso(),
        "maj": iso(),
        "seq": 0,
    }


def tier_of(cfg, sym):
    for a in cfg["univers"]:
        if a["sym"] == sym:
            return a["tier"]
    return "C"


def pair_of(cfg, sym):
    for a in cfg["univers"]:
        if a["sym"] == sym:
            return a["pair"]
    return None


def position_value(p, price):
    """Valeur liquidative d'une position (sans frais de sortie)."""
    if p["side"] == "long":
        return p["qty"] * price
    # short sans levier : collateral bloque = notionnel d'entree
    return p["notionnel"] + (p["entry"] - price) * p["qty"]


def unrealized(p, price):
    return position_value(p, price) - p["notionnel"]


def equity(state, prices):
    eq = state["cash"]
    for p in state["positions"]:
        px = prices.get(p["sym"], p.get("dernier_prix", p["entry"]))
        eq += position_value(p, px)
    return eq


def fill_price(side_action, bid, ask, slip_pct):
    """Prix d'execution simule d'un ordre au marche."""
    if side_action == "buy":
        return ask * (1 + slip_pct / 100)
    return bid * (1 - slip_pct / 100)


def costs_pct(cfg, sym):
    """Couts aller-retour en % : (si objectif atteint, si stop touche)."""
    f = cfg["frais"]; slip = f["slippage_pct_par_tier"][tier_of(cfg, sym)]
    win = f["taker_pct"] + slip + f["maker_pct"]          # entree marche + sortie limite
    loss = 2 * f["taker_pct"] + 2 * slip                   # entree marche + stop marche
    return win, loss


def costs_roundtrip_pct(cfg, sym):
    return costs_pct(cfg, sym)[1]


def net_rr(cfg, sym, side, entry, stop, tp):
    """Ratio rendement/risque APRES frais et slippage estimes."""
    w, l = costs_pct(cfg, sym)
    if side == "long":
        gain, loss = (tp - entry) - w / 100 * entry, (entry - stop) + l / 100 * entry
    else:
        gain, loss = (entry - tp) - w / 100 * entry, (stop - entry) + l / 100 * entry
    if loss <= 0:
        return 0
    return gain / loss


# ------------------------------------------------------------ journal activite
def log_event(agent, kind, msg, data=None):
    ev = load("activite.json", [])
    ev.append({"t": iso(), "agent": agent, "type": kind, "msg": msg, **({"data": data} if data else {})})
    save("activite.json", ev[-400:])
