#!/usr/bin/env python3
"""
Collecteur de pronostics foot : récupère les pronos de plusieurs sources,
les regroupe par match et calcule un consensus -> predictions.json

Usage :
  python3 collector.py --demo              # test hors-ligne avec de fausses sources
  python3 collector.py                     # lit sources.json et interroge le net
  python3 collector.py --min-sources 2     # ignore les pronos vus par < 2 sources

sources.json (liste d'API JSON ; adapte les chemins à chaque source) :
[
  {"name": "MaSource",
   "url": "https://exemple.com/api/predictions?date={date}",
   "headers": {"Authorization": "Bearer XXX"},
   "list_path": "data.matches",
   "fields": {"home": "home.name", "away": "away.name",
              "market": "tip", "confidence": "probability", "odds": "odd"}}
]
Respecte les conditions d'utilisation de chaque site / utilise leurs API officielles.
"""
import argparse, json, sys, unicodedata, urllib.request
from collections import defaultdict
from datetime import date

ALIASES = {  # noms d'équipes -> forme normalisée
    "rep. of ireland": "ireland", "republic of ireland": "ireland", "irlande": "ireland",
    "wales": "wales", "pays de galles": "wales", "northern ireland": "northern ireland",
    "irlande du nord": "northern ireland", "denmark": "denmark", "danemark": "denmark",
    "norway": "norway", "norvege": "norway", "sweden": "sweden", "suede": "sweden",
    "hungary": "hungary", "hongrie": "hungary", "poland": "poland", "pologne": "poland",
    "georgia": "georgia", "georgie": "georgia",
}
MARKETS = {"1x": "1X", "x2": "X2", "12": "12", "1": "1", "2": "2", "x": "X",
           "over 1.5": "Plus de 1.5", "plus de 1.5": "Plus de 1.5", "o1.5": "Plus de 1.5",
           "over 2.5": "Plus de 2.5", "plus de 2.5": "Plus de 2.5", "btts": "BTTS"}


def norm_team(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()
    return ALIASES.get(s, s)


def norm_market(s):
    return MARKETS.get(str(s).lower().strip(), str(s).strip())


def dig(obj, path):
    for k in path.split("."):
        obj = obj[int(k)] if isinstance(obj, list) else obj.get(k)
        if obj is None:
            return None
    return obj


def fetch_source(src, day):
    req = urllib.request.Request(src["url"].format(date=day),
                                 headers=src.get("headers", {"User-Agent": "Mozilla/5.0"}))
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    rows = dig(data, src["list_path"]) if src.get("list_path") else data
    f, out = src["fields"], []
    for row in rows:
        try:
            out.append({"source": src["name"], "home": dig(row, f["home"]), "away": dig(row, f["away"]),
                        "market": dig(row, f["market"]), "confidence": float(dig(row, f["confidence"])),
                        "odds": float(dig(row, f["odds"])) if f.get("odds") and dig(row, f["odds"]) else None})
        except (KeyError, TypeError, ValueError):
            continue  # ligne inexploitable
    return out


def demo_rows():
    d = [("Rep. Of Ireland", "Kosovo", "1X", 76, 1.24), ("Denmark", "Norway", "Over 1.5", 79, 1.17),
         ("Ukraine", "Georgia", "1X", 79, 1.38)]
    rows = []
    for i, name in enumerate(["DemoA", "DemoB", "DemoC"]):
        for h, a, m, c, o in d:
            if name == "DemoC" and h == "Denmark":
                m = "BTTS"  # désaccord volontaire
            rows.append({"source": name, "home": h, "away": a, "market": m,
                         "confidence": c - 3 * i, "odds": o})
    return rows


def consensus(rows, min_sources=1):
    games = defaultdict(lambda: defaultdict(list))
    names = {}
    for r in rows:
        k = (norm_team(r["home"]), norm_team(r["away"]))
        names.setdefault(k, (r["home"], r["away"]))
        games[k][norm_market(r["market"])].append(r)
    out = []
    for k, markets in games.items():
        # prono retenu = marché le plus cité, puis confiance moyenne la plus haute
        best = max(markets.items(), key=lambda kv: (len(kv[1]), sum(x["confidence"] for x in kv[1]) / len(kv[1])))
        mk, items = best
        if len(items) < min_sources:
            continue
        odds = [x["odds"] for x in items if x["odds"]]
        out.append({"home": names[k][0], "away": names[k][1], "market": mk,
                    "confidence": round(sum(x["confidence"] for x in items) / len(items)),
                    "odds": round(sum(odds) / len(odds), 2) if odds else None,
                    "sources": sorted({x["source"] for x in items}),
                    "agreement": f"{len(items)}/{len({x['source'] for g in markets.values() for x in g})}"})
    return sorted(out, key=lambda x: -x["confidence"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--config", default="sources.json")
    ap.add_argument("--min-sources", type=int, default=1)
    ap.add_argument("--out", default="predictions.json")
    a = ap.parse_args()
    day, rows = date.today().isoformat(), []
    if a.demo:
        rows = demo_rows()
    else:
        try:
            sources = json.load(open(a.config))
        except FileNotFoundError:
            sys.exit(f"{a.config} introuvable (voir l'en-tête du script).")
        for s in sources:
            try:
                got = fetch_source(s, day)
                print(f"[ok] {s['name']}: {len(got)} pronos")
                rows += got
            except Exception as e:
                print(f"[erreur] {s['name']}: {e}")
    res = consensus(rows, a.min_sources)
    json.dump({"date": day, "matches": res}, open(a.out, "w"), ensure_ascii=False, indent=2)
    for m in res:
        print(f"{m['home']} - {m['away']}: {m['market']} {m['confidence']}% "
              f"(cote {m['odds']}, accord {m['agreement']})")


if __name__ == "__main__":
    main()
