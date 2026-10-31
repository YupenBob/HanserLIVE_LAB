#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Crawl all hanser livestream records from song.2550505.com backend API."""
import json, os, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

API = "https://2550505.com/song"
RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")
os.makedirs(RAW, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

def get(path, params=None, tries=4, timeout=25):
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
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
            return json.loads(body)
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
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

def main():
    ms = months()
    dates = set()
    errors = []
    # 1) enumerate days with records, one request per month
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(get, "/lives/getdate", {"date": m}): m for m in ms}
        for f in as_completed(futs):
            m = futs[f]
            d = f.result()
            if d.get("code") != 0:
                errors.append(("getdate", m, d.get("error")))
                continue
            for day in d.get("list") or []:
                dates.add("%s-%s" % (m[:7], day))
    print("months=%d dates=%d errors=%d" % (len(ms), len(dates), len(errors)), flush=True)

    # 2) per date: info + songs + content
    results = {}
    def fetch(d):
        rec = {
            "date": d,
            "info": get("/lives/getinfo", {"date": d}).get("list") or [],
            "songs": get("/lives/getbydate", {"date": d}).get("list") or [],
            "contents": get("/livecontents/getbydate", {"date": d}).get("list") or [],
        }
        return d, rec
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch, d): d for d in sorted(dates)}
        for n, f in enumerate(as_completed(futs), 1):
            d, rec = f.result()
            results[d] = rec
            if n % 50 == 0:
                print("fetched %d/%d" % (n, len(dates)), flush=True)

    out = {"crawled_at": datetime.now().isoformat(timespec="seconds"),
           "count": len(results), "records": [results[d] for d in sorted(results)]}
    with open(os.path.join(os.path.dirname(RAW), "lives_all.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("saved", len(results), "records", flush=True)
    if errors:
        print("errors:", json.dumps(errors, ensure_ascii=False))

if __name__ == "__main__":
    main()
