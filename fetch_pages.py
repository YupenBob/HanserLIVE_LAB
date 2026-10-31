#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Crawl hanser livestream pages (SSR) from song.2550505.com politely.

Each page embeds all needed data in __NEXT_DATA__:
  pageProps = {latest, date, info:{id,title,start_time,end_time,link},
               record:{id,content,brief,link_pure,link_barrage,start_time,end_time},
               songs:{list:[...]} or {empty:true}, days:{'YYYY-MM':[dd,...]},
               prevDate, nextDate}
Saves one JSON per date under data/pages/YYYY-MM-DD.json, plus data/dates.json.
"""
import json, os, sys, time, random, urllib.request, urllib.parse, re, socket
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
PAGES = os.path.join(DATA, "pages")
os.makedirs(PAGES, exist_ok=True)
LOG = open(os.path.join(BASE, "fetch.log"), "a", encoding="utf-8")
socket.setdefaulttimeout(30)

SITE = "https://song.2550505.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
DELAY = float(os.environ.get("FETCH_DELAY", "1.4"))

def log(*a):
    msg = " ".join(str(x) for x in a)
    line = "%s %s" % (datetime.now().strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    LOG.write(line + "\n"); LOG.flush()

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": SITE + "/livestreams",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}

class Blocked(Exception):
    pass

def fetch_html(path, quiet=False):
    url = SITE + path
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 403:
                wait = 180 + attempt * 120
                log("403 blocked on", path, "-> sleeping", wait, "s")
                time.sleep(wait)
                last = e
                continue
            if e.code in (429, 503, 502, 504):
                wait = 30 + attempt * 30
                log("HTTP", e.code, path, "-> sleeping", wait, "s")
                time.sleep(wait); last = e; continue
            raise
        except Exception as e:
            last = e
            time.sleep(5 + attempt * 5)
    raise Blocked(str(last))

NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)

def parse_page(html):
    m = NEXT_RE.search(html)
    if not m:
        raise ValueError("no __NEXT_DATA__")
    data = json.loads(m.group(1))
    pp = data.get("props", {}).get("pageProps", {}) or {}
    return {
        "date": pp.get("date"),
        "latest": pp.get("latest"),
        "info": pp.get("info") or {},
        "record": pp.get("record") or {},
        "songs": pp.get("songs") or {},
        "days": pp.get("days") or {},
        "prevDate": pp.get("prevDate"),
        "nextDate": pp.get("nextDate"),
    }

def page_path(date_str):
    return "/livestreams?date=" + date_str

DATES_FILE = os.path.join(DATA, "dates.json")

def load_dates():
    if os.path.exists(DATES_FILE):
        return json.load(open(DATES_FILE, encoding="utf-8"))
    return {}

# ---------- stage 1: discover all dates ----------
def months(from_ym=(2017, 9), to_ym=(2026, 11)):
    out = []
    y, m = from_ym
    while (y, m) <= to_ym:
        out.append((y, m)); m += 1
        if m == 13: y, m = y + 1, 1
    return out

def stage_dates():
    meta = load_dates()
    # month -> [days]; collect from any page response's `days`
    have = set(meta.get("months_fetched", []))
    ms = months()
    # only need every 3rd month request, but easier: request month start of months not yet covered
    targets = [m for m in ms]
    covered = set()
    for key in have:
        covered.add(key)
    # A request for month M returns M-1, M, M+1. Choose months spaced by 3 starting 2017-10.
    probes = []
    i = 0
    while i < len(ms):
        probes.append(ms[i]); i += 3
    pending = []
    for (y, m) in probes:
        key = "%04d-%02d" % (y, m)
        if key in covered:
            continue
        pending.append((y, m, key))
    log("stage1: probes pending", len(pending), "of", len(probes))
    days = meta.get("days", {})
    for (y, m, key) in pending:
        date_str = "%04d-%02d-01" % (y, m)
        html = fetch_html(page_path(date_str))
        pg = parse_page(html)
        for mk, dl in (pg.get("days") or {}).items():
            days[mk] = dl
            covered.add(mk)
        log("probed", key, "-> days months", sorted((pg.get("days") or {}).keys()))
        time.sleep(DELAY + random.random() * 0.6)
        meta["months_fetched"] = sorted(covered)
        meta["days"] = days
        json.dump(meta, open(DATES_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    # build date list
    all_dates = sorted("%s-%s" % (mk, d) for mk, dl in days.items() for d in dl)
    meta["all_dates"] = all_dates
    json.dump(meta, open(DATES_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("stage1: dates", len(all_dates), all_dates[:3], all_dates[-3:] if all_dates else [])
    return all_dates

# ---------- stage 2: fetch every date page ----------
def stage_pages(dates):
    pending = [d for d in dates if not os.path.exists(os.path.join(PAGES, d + ".json"))]
    log("stage2: pending", len(pending), "/", len(dates))
    for n, d in enumerate(pending, 1):
        try:
            html = fetch_html(page_path(d))
            pg = parse_page(html)
            json.dump(pg, open(os.path.join(PAGES, d + ".json"), "w", encoding="utf-8"),
                      ensure_ascii=False)
            log("page %d/%d %s title=%r songs=%s content=%s" % (
                n, len(pending), d,
                (pg.get("info") or {}).get("title"),
                len((pg.get("songs") or {}).get("list") or []),
                (len((pg.get("record") or {}).get("content") or "") if pg.get("record") else "no-record")))
        except Blocked as e:
            log("BLOCKED, aborting stage2:", e)
            break
        except Exception as e:
            log("ERR", d, repr(e))
        time.sleep(DELAY + random.random() * 0.7)

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("all", "dates"):
        dates = stage_dates()
    else:
        meta = load_dates()
        dates = meta.get("all_dates", [])
    if mode in ("all", "pages"):
        stage_pages(dates)
    log("DONE", mode)

if __name__ == "__main__":
    main()
