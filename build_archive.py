#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build consolidated archive from crawled page JSONs.

Inputs:
  data/pages/YYYY-MM-DD.json   (parsed __NEXT_DATA__ pageProps)
  data/bili_matches.json       (optional: {"YYYY-MM-DD": {bvid,title,...}})
Outputs:
  data/archive.json            machine-readable full archive
  data/archive_flat.json       one row per livestream
"""
import json, os, glob, re
from datetime import datetime, date

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
PAGES = os.path.join(DATA, "pages")

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

def _list(x):
    """Normalise song containers.

    Site shapes seen:
      {"2020-01-03": [ {..}, .. ]}       (pageProps.songs keyed by date)
      {"list": [...]}                     (API getbydate)
      {"empty": true}                    (no songs)
      []
    """
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        if x.get("empty"):
            return []
        if isinstance(x.get("list"), list):
            return x["list"]
        out = []
        for k, v in x.items():
            if isinstance(v, list):
                out.extend(v)
        return out
    return []

def load_pages():
    pages = {}
    for fp in sorted(glob.glob(os.path.join(PAGES, "*.json"))):
        try:
            pg = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        d = pg.get("date") or os.path.basename(fp)[:-5]
        if d:
            pages[d] = pg
    return pages

def clean_text(s):
    if s is None:
        return ""
    s = str(s).replace("\r\n", "\n").replace("\r", "\n")
    return s.strip()

def is_missing_transcript(content):
    c = clean_text(content)
    return c == "" or c in ("暂无", "无", "/", "-", "——")

BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")

def norm_link(v):
    """Normalise site link fields: bare BV ids, iframe snippets -> canonical URL."""
    v = clean_text(v)
    if not v or v in ("暂无", "无", "null", "None", "-", "1"):
        return ""
    if v.startswith("http"):
        return v
    m = BV_RE.search(v)
    if m:
        return "https://www.bilibili.com/video/" + m.group(0)
    return ""

def parse_dt(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def build():
    pages = load_pages()
    matches = {}
    mp = os.path.join(DATA, "bili_matches.json")
    if os.path.exists(mp):
        matches = json.load(open(mp, encoding="utf-8"))

    rows = []
    for d in pages:
        pg = pages[d]
        info = pg.get("info") or {}
        record = pg.get("record") or {}
        if isinstance(info, dict) and info.get("empty"):
            info = {}
        if isinstance(record, dict) and record.get("empty"):
            record = {}
        songs = _list(pg.get("songs"))
        content = clean_text(record.get("content"))

        start = info.get("start_time") or record.get("start_time") or ""
        end = info.get("end_time") or record.get("end_time") or ""
        if end and (end.startswith("0000") or (start and end < start)):
            end = ""   # site data glitch (0000-00-00 / end before start)
        start = clean_text(start)
        end = clean_text(end)
        duration_min = None
        sdt, edt = parse_dt(start), parse_dt(end)
        if sdt and edt:
            dur = (edt - sdt).total_seconds() / 60.0
            if dur > 0:
                duration_min = round(dur)

        row = {
            "date": d,
            "weekday": WEEKDAYS[date.fromisoformat(d).weekday()],
            "title": clean_text(info.get("title")),
            "start": start,
            "end": end,
            "duration_min": duration_min,
            "brief": clean_text(record.get("brief")),
            "content": content,
            "has_transcript": (not is_missing_transcript(content)) and len(content) > 30,
            "transcript_chars": 0 if is_missing_transcript(content) else len(content),
            "link_pure": norm_link(record.get("link_pure")),
            "link_barrage": norm_link(record.get("link_barrage")),
            "info_link": norm_link(info.get("link")),
            "songs": [{"time": s.get("time", ""), "name": clean_text(s.get("name")),
                       "author": clean_text(s.get("author"))} for s in songs],
            "song_count": len(songs),
            "prevDate": pg.get("prevDate"),
            "nextDate": pg.get("nextDate"),
        }
        for k in ("link_pure", "link_barrage", "info_link"):
            if row[k] in ("暂无", "无", "null", "None", "-"):
                row[k] = ""
        row["has_link"] = bool(row["link_pure"] or row["link_barrage"] or row["info_link"])
        if d in matches:
            row["bili_match"] = matches[d]
            bm = matches[d] or {}
            row["bili_conf"] = bm.get("confidence") or ""
            row["bili_url"] = bm.get("url") or (("https://www.bilibili.com/video/" + bm["bvid"])
                                                if bm.get("bvid") else "")
            row["bili_status"] = ("suspected" if bm.get("confidence") == "suspected"
                                  else "continuation" if bm.get("source") == "continuation"
                                  else "matched" if (bm.get("bvid") or bm.get("url")) else "none")
        else:
            row["bili_status"] = "none"
        rows.append(row)

    rows.sort(key=lambda r: r["date"])
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "https://song.2550505.com/livestreams (API: https://2550505.com/song)",
        "stream_count": len(rows),
        "rows": rows,
    }
    json.dump(out, open(os.path.join(DATA, "archive.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("archive.json:", len(rows), "streams,",
          sum(1 for r in rows if r["songs"]), "with songs,",
          sum(1 for r in rows if r["has_transcript"]), "with transcript,",
          sum(1 for r in rows if not r["has_link"]), "without any link")
    return out

if __name__ == "__main__":
    build()
