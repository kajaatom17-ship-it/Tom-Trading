"""Prepare la publication : python engine/pack.py
Ecrit publish/ (ce que sert la page) et publish/sys/bundle.json (code + etat, pour la prochaine execution).
Affiche la liste JSON des fichiers a publier (champ 'files' de publish_files).
"""
import json, os, shutil, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "publish")
CODE = ["config.json", "README.md", "agents/COMITE.md", "engine/core.py", "engine/risk.py", "engine/strategy.py",
        "engine/tick.py", "engine/brief.py", "engine/decide.py", "engine/pack.py", "engine/veille.py", "tests/test_engine.py", "docs/index.html"]
STATE = ["state.json", "trades.json", "decisions.json", "activite.json", "equity.json", "signals.json", "market.json", "status.json"]


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "data")); os.makedirs(os.path.join(OUT, "sys"))
    files = {}
    for p in CODE:
        with open(os.path.join(ROOT, p), encoding="utf-8") as f:
            files[p] = f.read()
    for n in STATE:
        src = os.path.join(ROOT, "docs", "data", n)
        if os.path.exists(src):
            with open(src, encoding="utf-8") as f:
                files["docs/data/" + n] = f.read()
            shutil.copyfile(src, os.path.join(OUT, "data", n))
    for n in ("candles.json",):
        src = os.path.join(ROOT, "docs", "data", n)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(OUT, "data", n))
    shutil.copyfile(os.path.join(ROOT, "docs", "index.html"), os.path.join(OUT, "index.html"))
    shutil.copyfile(os.path.join(ROOT, "config.json"), os.path.join(OUT, "config.json"))
    with open(os.path.join(OUT, "sys", "bundle.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "files": files}, f, ensure_ascii=False)
    listing = []
    for dp, _, fs in os.walk(OUT):
        for fn in sorted(fs):
            full = os.path.join(dp, fn)
            listing.append({"as": os.path.relpath(full, OUT), "path": full})
    print(json.dumps(listing, indent=1))


if __name__ == "__main__":
    sys.exit(main())
