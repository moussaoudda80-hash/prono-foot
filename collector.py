#!/usr/bin/env python3
"""
Collecteur de pronostics foot -> predictions.json (consensus par match).

  python3 collector.py --demo        # test hors-ligne
  python3 collector.py               # lit sources.json

Types de sources dans sources.json :
 - {"type":"manual","name":"Manuel","file":"manual.json"}
     manual.json = liste de {"league","kickoff","home","away","market","confidence","odds","source"}
     kickoff au format ISO UTC, ex. "2026-11-17T20:45:00Z" (optionnel)
 - {"type":"apifootball","name":"API-Football","key_env":"APIFOOTBALL_KEY",
    "leagues":[12,20,6,36,29,5,2,39],"max_fixtures":30}
     (cle gratuite sur api-football.com ; le plan gratuit peut ne pas donner la saison en cours)
 - {"type":"json","name":"X","url":"https://...{date}","list_path":"data.matches",
    "fields":{"home":"..","away":"..","market":"..","confidence":"..","odds":"..","league":"..","kickoff":".."}}
Ajoute "enabled": false pour desactiver une source.
"""
import argparse, json, os, sys, unicodedata, urllib.request
from collections import defaultdict
from datetime import date

ALIASES = {"rep. of ireland": "ireland", "republic of ireland": "ireland", "irlande": "ireland",
           "pays de galles": "wales", "irlande du nord": "northern ireland", "danemark": "denmark",
           "norvege": "norway", "suede": "sweden", "hongrie": "hungary", "pologne": "poland",
           "georgie": "georgia", "cote d'ivoire": "ivory coast", "senegal": "senegal",
           "afrique du sud": "south africa", "maroc": "morocco", "algerie": "algeria", "tunisie": "tunisia",
           "egypte": "egypt", "cameroun": "cameroon", "nigeria": "nigeria", "mali": "mali"}
MARKETS = {"1x": "1X", "x2": "X2", "12": "12", "1": "1", "2": "2", "x": "X", "over 1.5": "Plus de 1.5",
           "plus de 1.5": "Plus de 1.5", "o1.5": "Plus de 1.5", "over 2.5": "Plus de 2.5",
           "plus de 2.5": "Plus de 2.5", "btts": "BTTS"}


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


def fetch_json(src, day):
    req = urllib.request.Request(src["url"].format(date=day), headers=src.get("headers", {"User-Agent": "Mozilla/5.0"}))
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    rows = dig(data, src["list_path"]) if src.get("list_path") else data
    f, out = src["fields"], []
    for row in rows:
        try:
            g = lambda k: dig(row, f[k]) if f.get(k) else None
            out.append({"source": src["name"], "home": g("home"), "away": g("away"), "market": g("market"),
                        "confidence": float(g("confidence")), "odds": float(g("odds")) if g("odds") else None,
                        "league": g("league"), "kickoff": g("kickoff")})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetch_manual(src, day):
    rows = json.load(open(src.get("file", "manual.json"), encoding="utf-8"))
    out = []
    for r in rows:
        r.setdefault("source", src.get("name", "Manuel"))
        r.setdefault("odds", None)
        out.append(r)
    return out


def fetch_apifootball(src, day):
    key = os.environ.get(src.get("key_env", "APIFOOTBALL_KEY"))
    if not key:
        raise RuntimeError("cle API manquante (variable APIFOOTBALL_KEY)")
    def get(path):
        req = urllib.request.Request("https://v3.football.api-sports.io" + path, headers={"x-apisports-key": key})
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.load(r)
        if j.get("errors"):
            print("  api:", j["errors"])
        return j.get("response", [])
    ids = set(src.get("leagues", []))
    fx = [f for f in get(f"/fixtures?date={day}") if not ids or f["league"]["id"] in ids][:src.get("max_fixtures", 30)]
    out = []
    for f in fx:
        try:
            p = get(f"/predictions?fixture={f['fixture']['id']}")[0]["predictions"]["percent"]
            h, d, a = [float(p[k].strip("%")) for k in ("home", "draw", "away")]
        except Exception:
            continue
        c = {"1": h, "2": a, "1X": h + d, "X2": d + a}
        mk = max(("1", "2"), key=c.get) if max(h, a) >= 60 else max(("1X", "X2"), key=c.get)
        out.append({"source": src["name"], "home": f["teams"]["home"]["name"], "away": f["teams"]["away"]["name"],
                    "market": mk, "confidence": c[mk], "odds": None,
                    "league": f["league"]["name"], "kickoff": f["fixture"]["date"]})
    return out


ADAPTERS = {"json": fetch_json, "manual": fetch_manual, "apifootball": fetch_apifootball}


def demo_rows():
    d = [("Rep. Of Ireland", "Kosovo", "1X", 76, 1.24), ("Denmark", "Norway", "Over 1.5", 79, 1.17),
         ("Ukraine", "Georgia", "1X", 79, 1.38)]
    rows = []
    for i, name in enumerate(["DemoA", "DemoB", "DemoC"]):
        for h, a, m, c, o in d:
            if name == "DemoC" and h == "Denmark":
                m = "BTTS"
            rows.append({"source": name, "home": h, "away": a, "market": m, "confidence": c - 3 * i, "odds": o,
                         "league": "Nations League", "kickoff": "2026-11-17T20:45:00Z"})
    return rows


def consensus(rows, min_sources=1):
    games, names = defaultdict(lambda: defaultdict(list)), {}
    for r in rows:
        k = (norm_team(r["home"]), norm_team(r["away"]))
        names.setdefault(k, r)
        games[k][norm_market(r["market"])].append(r)
    out = []
    for k, markets in games.items():
        mk, items = max(markets.items(), key=lambda kv: (len(kv[1]), sum(x["confidence"] for x in kv[1]) / len(kv[1])))
        if len(items) < min_sources:
            continue
        odds = [x["odds"] for x in items if x.get("odds")]
        total = len({x["source"] for g in markets.values() for x in g})
        first = names[k]
        out.append({"home": first["home"], "away": first["away"], "market": mk,
                    "league": first.get("league") or "Autres", "kickoff": first.get("kickoff"),
                    "confidence": round(sum(x["confidence"] for x in items) / len(items)),
                    "odds": round(sum(odds) / len(odds), 2) if odds else None,
                    "sources": sorted({x["source"] for x in items}), "agreement": f"{len(items)}/{total}"})
    return sorted(out, key=lambda x: (x["league"], x["kickoff"] or "", -x["confidence"]))


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
            sources = json.load(open(a.config, encoding="utf-8"))
        except FileNotFoundError:
            sys.exit(f"{a.config} introuvable.")
        for s in sources:
            if s.get("enabled") is False:
                continue
            try:
                got = ADAPTERS[s.get("type", "json")](s, day)
                print(f"[ok] {s['name']}: {len(got)} pronos")
                rows += got
            except Exception as e:
                print(f"[erreur] {s['name']}: {e}")
    res = consensus(rows, a.min_sources)
    json.dump({"date": day, "matches": res}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for m in res:
        print(f"[{m['league']}] {m['home']} - {m['away']}: {m['market']} {m['confidence']}% (accord {m['agreement']})")


if __name__ == "__main__":
    main()
