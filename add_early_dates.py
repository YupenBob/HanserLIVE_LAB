import json, os, re, sys
sys.path.insert(0, ".")
from torii_solve import ToriiSession

DATA = "data"
PAGES = os.path.join(DATA, "pages")

# check prevDate chain of earliest known page
pg = json.load(open(os.path.join(PAGES, "2017-08-01.json"), encoding="utf-8"))
print("2017-08-01 prevDate:", pg.get("prevDate"), "nextDate:", pg.get("nextDate"))
pg2 = json.load(open(os.path.join(PAGES, "2017-08-02.json"), encoding="utf-8"))
print("2017-08-02 prevDate:", pg2.get("prevDate"))

s = ToriiSession()
s.solve(verbose=False)
extra = ["2017-07-18", "2017-07-25"]
for d in extra:
    fp = os.path.join(PAGES, d + ".json")
    if os.path.exists(fp):
        print("exists", d); continue
    code, body = s.get("/livestreams?date=" + d)
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', body, re.S)
    if not m:
        print("FAIL", d, code); continue
    pp = json.loads(m.group(1))["props"]["pageProps"]
    json.dump(pp, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    songs = pp.get("songs") or {}
    ns = sum(len(v) for v in songs.values() if isinstance(v, list))
    rec = pp.get("record") or {}
    print("fetched", d, "songs", ns, "prev", pp.get("prevDate"), "next", pp.get("nextDate"),
          "content", len(rec.get("content") or "") if isinstance(rec, dict) else 0)

# update dates.json
meta = json.load(open(os.path.join(DATA, "dates.json"), encoding="utf-8"))
all_dates = sorted(set(meta["all_dates"]) | set(extra))
meta["all_dates"] = all_dates
json.dump(meta, open(os.path.join(DATA, "dates.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("all_dates now", len(all_dates), all_dates[:3])
