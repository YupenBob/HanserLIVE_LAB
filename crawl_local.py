#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Local polite crawler for song.2550505.com livestream pages.

3 workers, each with its own CAPTCHA-verified session (~0.7 req/s total).
Saves data/pages/YYYY-MM-DD.json (pageProps). Resumable.
"""
import json, os, re, sys, time, random, traceback, threading, queue
from datetime import datetime
from torii_solve import ToriiSession

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
PAGES = os.path.join(DATA, "pages")
os.makedirs(PAGES, exist_ok=True)
LOG = open(os.path.join(BASE, "crawl_local.log"), "a", encoding="utf-8")
LOCK = threading.Lock()
DELAY = float(os.environ.get("CRAWL_DELAY", "0.4"))
WORKERS = int(os.environ.get("CRAWL_WORKERS", "3"))

def log(*a):
    line = "%s %s" % (datetime.now().strftime("%H:%M:%S"), " ".join(str(x) for x in a))
    with LOCK:
        print(line, flush=True)
        LOG.write(line + "\n"); LOG.flush()

NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)

class Crawler:
    def __init__(self, idx):
        self.idx = idx
        self.s = ToriiSession()
        self.s.solve(verbose=False)

    def page(self, date_str):
        path = "/livestreams?date=" + date_str
        for attempt in range(6):
            code, body = self.s.get(path)
            if code == 200 and "__NEXT_DATA__" in body:
                m = NEXT_RE.search(body)
                if m:
                    return json.loads(m.group(1))["props"]["pageProps"]
            if code == 403:
                log("[w%d] hard 403 on %s; sleep 300s" % (self.idx, date_str))
                time.sleep(300)
                continue
            if code == 503 or "Server Torii" in body[:3000]:
                log("[w%d] CAPTCHA on %s; backoff+solve" % (self.idx, date_str))
                time.sleep(20 + attempt * 25)
                self.s.solve(verbose=False)
                continue
            log("[w%d] HTTP %s %s len=%d" % (self.idx, code, date_str, len(body)))
            time.sleep(8 + attempt * 10)
        raise RuntimeError("page failed " + date_str)

def worker(q, idx, stats):
    try:
        c = Crawler(idx)
    except Exception as e:
        log("[w%d] init failed %r" % (idx, e)); return
    while True:
        try:
            d = q.get_nowait()
        except queue.Empty:
            return
        try:
            pp = c.page(d)
            with open(os.path.join(PAGES, d + ".json"), "w", encoding="utf-8") as f:
                json.dump(pp, f, ensure_ascii=False)
            songs = pp.get("songs") or {}
            ns = sum(len(v) for v in songs.values() if isinstance(v, list))
            rec = pp.get("record") or {}
            content = rec.get("content") or "" if isinstance(rec, dict) else ""
            info = pp.get("info") or {}
            title = info.get("title") if isinstance(info, dict) else None
            with LOCK:
                stats["done"] += 1
                n = stats["done"]
            if n % 5 == 0 or n <= 3:
                el = time.time() - stats["t0"]
                log("page %d/%d %s title=%r songs=%d tr=%d link=%s (%.0fs, %.2fs/p)" % (
                    n, stats["total"], d, title, ns,
                    0 if content == "暂无" else len(content),
                    "Y" if (rec.get("link_pure") or "").startswith("http") else "N",
                    el, el / max(n, 1)))
        except Exception as e:
            log("[w%d] page ERR %s %r" % (idx, d, str(e)[:160]))
        time.sleep(DELAY + random.random() * 0.3)

def main():
    meta = json.load(open(os.path.join(DATA, "dates.json"), encoding="utf-8"))
    all_dates = meta["all_dates"]
    pending = [d for d in all_dates if not os.path.exists(os.path.join(PAGES, d + ".json"))]
    log("total", len(all_dates), "pending", len(pending), "workers", WORKERS)
    q = queue.Queue()
    for d in pending:
        q.put(d)
    stats = {"done": 0, "total": len(pending), "t0": time.time()}
    threads = [threading.Thread(target=worker, args=(q, i, stats), daemon=True)
               for i in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log("DONE pages now", len(os.listdir(PAGES)))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("FATAL", traceback.format_exc())
