#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Offline (catalogue-only) Bilibili matching for ALL livestream dates.

Fast, no network. Writes data/bili_matches.json with best candidate per date.
Later, match_bilibili.py --mode online fills in the weak/empty ones.
"""
import json, os, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "tools"))
DATA = os.path.join(BASE, "data")
import bili_search as bs


def main():
    dates = json.load(open(os.path.join(DATA, "dates.json"), encoding="utf-8"))["all_dates"]
    matches = {}
    fp = os.path.join(DATA, "bili_matches.json")
    if os.path.exists(fp):
        matches = json.load(open(fp, encoding="utf-8"))
    client = bs.BiliClient(min_interval=0.0)
    t0 = time.time()
    n_new = 0
    for d in dates:
        if d in matches and matches[d].get("bvid"):
            continue
        try:
            ranked = bs.match_stream(client, d, "", online="never", top=3, use_index=True)
        except Exception as e:
            print("ERR", d, repr(e)[:120]); continue
        if ranked:
            b = ranked[0]
            matches[d] = {
                "bvid": b.get("bvid"), "title": b.get("title"), "author": b.get("author"),
                "mid": b.get("mid"), "pubdate": b.get("pubdate"),
                "pubdate_iso": b.get("pubdate_iso"), "score": b.get("score"),
                "reasons": b.get("reasons"), "duration": b.get("duration"),
                "page": b.get("page"),
                "url": "https://www.bilibili.com/video/" + (b.get("bvid") or "") +
                       (("?p=%s" % b["page"]) if b.get("page") and int(b["page"]) > 1 else ""),
                "source": "catalogue", "confidence": "offline",
                "alternates": [{"bvid": c.get("bvid"), "title": c.get("title"),
                                "author": c.get("author"), "score": c.get("score"),
                                "page": c.get("page")} for c in ranked[1:]],
            }
            n_new += 1
        else:
            matches[d] = {"bvid": None, "source": "none", "confidence": "none", "score": 0}
    json.dump(matches, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    have = sum(1 for v in matches.values() if v.get("bvid"))
    strong = sum(1 for v in matches.values() if (v.get("score") or 0) >= 80)
    print("dates=%d matched=%d strong(>=80)=%d new=%d %.1fs" % (
        len(dates), have, strong, n_new, time.time() - t0))


if __name__ == "__main__":
    main()
