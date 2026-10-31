#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Batch-match Bilibili recordings for livestreams that lack a site recording link.

Reads data/archive.json, writes/updates data/bili_matches.json:
  { "YYYY-MM-DD": {"bvid","url","title","author","mid","pubdate","score","reasons",
                   "confidence","source","alternates":[...]} }

Usage:
  python match_bilibili.py --mode offline          # local catalogue only (fast, no network)
  python match_bilibili.py --mode online --limit 40  # add web-search fallback for remaining ones
  python match_bilibili.py --mode offline --dates 2020-01-03,2020-01-06
"""
import argparse, json, os, sys, time, re

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "tools"))
DATA = os.path.join(BASE, "data")
ARCHIVE = os.path.join(DATA, "archive.json")
MATCHES = os.path.join(DATA, "bili_matches.json")

import bili_search as bs  # noqa: E402


def bv_url(bvid, page=None):
    u = "https://www.bilibili.com/video/" + bvid
    if page and int(page) > 1:
        u += "?p=%s" % page
    return u


def confidence(score, cand, date_str):
    s = score or 0
    reasons = " ".join(cand.get("reasons") or [])
    exact = "title-date" in reasons and ("%d" % int(date_str[5:7])) in (cand.get("title") or "")
    if s >= 95:
        c = "high"
    elif s >= 80:
        c = "medium"
    elif s >= 70:
        c = "low-medium"
    else:
        c = "low"
    return c


def candidate_record(c):
    return {
        "bvid": c.get("bvid"),
        "url": bv_url(c.get("bvid"), c.get("page")),
        "title": c.get("title"),
        "author": c.get("author"),
        "mid": c.get("mid"),
        "pubdate": c.get("pubdate"),
        "pubdate_iso": c.get("pubdate_iso"),
        "score": c.get("score"),
        "reasons": c.get("reasons"),
        "duration": c.get("duration"),
        "page": c.get("page"),
        "source": c.get("source"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["offline", "online"], default="offline")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dates", default="")
    ap.add_argument("--min-interval", type=float, default=1.5)
    ap.add_argument("--min-score", type=float, default=70)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    a = json.load(open(ARCHIVE, encoding="utf-8"))
    rows = a["rows"]
    matches = {}
    if os.path.exists(MATCHES):
        matches = json.load(open(MATCHES, encoding="utf-8"))

    only = set(d.strip() for d in args.dates.split(",") if d.strip())
    todo = []
    for r in rows:
        if r.get("link_pure") or r.get("link_barrage"):
            continue  # site already has a link
        if only and r["date"] not in only:
            continue
        m = matches.get(r["date"])
        # offline pass: fill anything missing; online pass: only weak/empty
        if args.mode == "offline" and m and (m.get("bvid") or m.get("source") == "none"):
            continue
        if args.mode == "online" and m and (m.get("score") or 0) >= args.min_score:
            continue
        todo.append(r)
    if args.limit:
        todo = todo[: args.limit]
    print("todo:", len(todo), "mode:", args.mode, flush=True)

    client = bs.BiliClient(min_interval=args.min_interval, verbose=args.verbose)
    t0 = time.time()
    for i, r in enumerate(todo, 1):
        date = r["date"]
        title = r.get("title") or ""
        online = "never" if args.mode == "offline" else "auto"
        try:
            ranked = bs.match_stream(client, date, title, online=online,
                                     top=5, use_index=True)
        except Exception as e:
            print("ERR", date, repr(e)[:160], flush=True)
            ranked = []
        if ranked:
            best = ranked[0]
            rec = candidate_record(best)
            rec["confidence"] = confidence(best.get("score"), best, date)
            rec["alternates"] = [candidate_record(c) for c in ranked[1:4]]
            rec["source"] = "catalogue" if args.mode == "offline" else "catalogue+search"
        else:
            rec = {"bvid": None, "source": "none",
                   "confidence": "none", "score": 0}
        matches[date] = rec
        if i % 10 == 0 or i == len(todo):
            json.dump(matches, open(MATCHES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("progress %d/%d  %.0fs  %s -> %s (%s, score=%s)" % (
                i, len(todo), time.time() - t0, date,
                (rec.get("bvid") or "-"), rec.get("confidence"), rec.get("score")), flush=True)

    json.dump(matches, open(MATCHES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    have = sum(1 for v in matches.values() if v.get("bvid"))
    print("done. matches with bvid: %d / %d dates in file" % (have, len(matches)))


if __name__ == "__main__":
    main()
