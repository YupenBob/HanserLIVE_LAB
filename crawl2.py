#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Crawl hanser livestream records from 2550505.com song API (v2: resumable, logged)."""
import json, os, sys, time, urllib.request, urllib.parse, socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
RAW = os.path.join(DATA, "raw")
os.makedirs(RAW, exist_ok=True)
LOG = open(os.path.join(BASE, "crawl.log"), "a", encoding="utf-8")

def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg, flush=True)
    LOG.write("%s %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    LOG.flush()

API = "https://2550505.com/song"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
socket.setdefaulttimeout(20)

def get(path, params=None, tries=3):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://song.2550505.com/",
                "Connection": "close",
            })
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8", "replace")
            return json.loads(body)
        except Exception as e:
            last = e
            time.sleep(0.8 * (i + 1))
    return {"code": -1, "error": str(last), "list": []}

def months():
    out = []
    y, m = 2017, 10
    while (y, m) <= (2026, 10):
        out.append("%04d-%02d-01" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out

DATES_FILE = os.path.join(DATA, "dates.json")

def stage_dates():
    if os.path.exists(DATES_FILE):
        d = json.load(open(DATES_FILE, encoding="utf-8"))
        log("stage1: cached", len(d), "dates")
        return d
    ms = months()
    log("stage1: querying", len(ms), "months")
    dates = set()
    batch = 6
    for i in range(0, len(ms), batch):
        chunk = ms[i:i + batch]
        with ThreadPoolExecutor(max_workers=batch) as ex:
            futs = {ex.submit(get, "/lives/getdate", {"date": m}): m for m in chunk}
            for f in as_completed(futs):
                m = futs[f]
                d = f.result()
                if d.get("code") != 0:
                    log("stage1 WARN", m, d.get("error"))
                    continue
                for day in d.get("list") or []:
                    dates.add("%s-%s" % (m[:7], day))
        log("stage1 progress", i + len(chunk), "/", len(ms), "dates=", len(dates))
    dates = sorted(dates)
    json.dump(dates, open(DATES_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    return dates

def stage_records(dates):
    done = 0
    for d in dates:
        fp = os.path.join(RAW, d + ".json")
        if os.path.exists(fp):
            done += 1
            continue
    log("stage2:", len(dates), "dates,", done, "already cached")
    pending = [d for d in dates if not os.path.exists(os.path.join(RAW, d + ".json"))]

    def fetch(d):
        return d, {
            "date": d,
            "info": get("/lives/getinfo", {"date": d}).get("list") or [],
            "songs": get("/lives/getbydate", {"date": d}).get("list") or [],
            "contents": get("/livecontents/getbydate", {"date": d}).get("list") or [],
        }

    for i in range(0, len(pending), 6):
        chunk = pending[i:i + 6]
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(fetch, d): d for d in chunk}
            for f in as_completed(futs):
                d, rec = f.result()
                json.dump(rec, open(os.path.join(RAW, d + ".json"), "w", encoding="utf-8"),
                          ensure_ascii=False)
        log("stage2 progress", min(i + 6, len(pending)), "/", len(pending))

def consolidate():
    recs = []
    for fn in sorted(os.listdir(RAW)):
        if fn.endswith(".json"):
            recs.append(json.load(open(os.path.join(RAW, fn), encoding="utf-8")))
    out = {"crawled_at": datetime.now().isoformat(timespec="seconds"),
           "count": len(recs), "records": recs}
    json.dump(out, open(os.path.join(DATA, "lives_all.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    log("consolidated", len(recs), "records")

if __name__ == "__main__":
    dates = stage_dates()
    log("total dates", len(dates), dates[0], dates[-1])
    stage_records(dates)
    consolidate()
    log("DONE")
