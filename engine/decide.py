"""Depot d'une decision du comite.

  python engine/decide.py check  decision.json   -> verifie avec les garde-fous du code (prix live), n'ecrit rien
  python engine/decide.py submit decision.json   -> verifie, puis depose dans docs/data/inbox/
                                                   (le moteur l'execute au prochain tick)
  python engine/decide.py submit decision.json --now  -> depose ET lance un tick immediatement

Le comite n'ecrit jamais directement dans le portefeuille : seul le moteur le fait.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import INBOX, config, iso, load, now_utc, rp, tickers
from risk import check_open

REQUIRED_AGENTS = ["analyste_technique", "analyste_macro", "analyste_sentiment", "trader", "risk_manager"]


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("check", "submit"):
        print(__doc__); return 2
    mode, path = sys.argv[1], sys.argv[2]
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("id", "D-" + now_utc().strftime("%Y%m%d-%H%M%S"))
    d.setdefault("cree_le", iso())
    problems = []
    action = d.get("action")
    if action not in ("open", "close", "tighten_stop", "none"):
        problems.append("action doit etre open, close, tighten_stop ou none")
    missing = [a for a in REQUIRED_AGENTS if a not in d.get("agents", {})]
    if missing:
        problems.append("avis manquants : " + ", ".join(missing))
    if not d.get("synthese"):
        problems.append("synthese manquante")
    disc = d.get("discussion") or []
    if len(disc) < 8:
        problems.append("discussion trop courte : au moins 8 messages où les agents se répondent")
    elif not any(m.get("repond_a") for m in disc):
        problems.append("discussion sans échange : au moins un agent doit répondre à un autre (repond_a)")
    if not isinstance(d.get("compte_rendu"), dict) or not d["compte_rendu"].get("decision"):
        problems.append("compte_rendu manquant (points, desaccords, decision, a_surveiller)")
    if action == "open":
        for k in ("sym", "side", "stop", "tp", "entry_ref", "strategie"):
            if k not in d:
                problems.append(f"champ manquant : {k}")
    if problems:
        print(json.dumps({"ok": False, "problemes": problems}, ensure_ascii=False, indent=1)); return 1

    if action == "open":
        cfg = config()
        st = load("state.json", None)
        tk = tickers(cfg["univers"])
        ok, reasons, sizing = check_open(cfg, st, d, tk.get(d["sym"]), {s: t["last"] for s, t in tk.items()})
        report = {"ok": ok, "motifs_refus": reasons,
                  "simulation": {k: (rp(v) if isinstance(v, float) else v) for k, v in (sizing or {}).items()}}
        print(json.dumps(report, ensure_ascii=False, indent=1))
        if not ok and mode == "submit":
            print("-> Refuse par les garde-fous. La decision est quand meme journalisee (statut : bloque).")
    if mode == "submit":
        os.makedirs(INBOX, exist_ok=True)
        out = os.path.join(INBOX, d["id"] + ".json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print(f"Depose : {out}")
        if "--now" in sys.argv:
            subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "tick.py"), "--no-scan"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
