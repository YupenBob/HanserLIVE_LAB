#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Merge teammate deep-search corrections (research/bili_matches_deep.json) into
data/bili_matches.json: mainly the 131 missing `?p=` multi-part URLs."""
import json, os, re

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

deep = json.load(open(os.path.join(BASE, "research", "bili_matches_deep.json"), encoding="utf-8"))
matches = json.load(open(os.path.join(DATA, "bili_matches.json"), encoding="utf-8"))

fixed = 0
for d, corr in (deep.get("matches") or {}).items():
    url = corr.get("url") or ""
    m = re.search(r"[?&]p=(\d+)", url)
    page = int(m.group(1)) if m else corr.get("part")
    cur = matches.setdefault(d, {})
    old_url = cur.get("url")
    cur["bvid"] = corr.get("bvid") or cur.get("bvid")
    cur["title"] = corr.get("title") or cur.get("title")
    cur["author"] = corr.get("author") or cur.get("author")
    cur["mid"] = corr.get("mid") or cur.get("mid")
    if page:
        cur["page"] = int(page)
        cur["url"] = "https://www.bilibili.com/video/%s?p=%d" % (cur["bvid"], int(page))
    elif url:
        cur["url"] = url
    cur["source"] = cur.get("source") or "catalogue"
    cur["confidence"] = cur.get("confidence") or "medium"
    cur["deep_checked"] = True
    if old_url != cur.get("url"):
        fixed += 1

json.dump(matches, open(os.path.join(DATA, "bili_matches.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("merged deep corrections, urls fixed:", fixed)

# sanity: any remaining match on the multi-P bvid without ?p=
bad = [d for d, v in matches.items()
       if v.get("bvid") == "BV1Gb4y1k7MX" and not re.search(r"[?&]p=\d+", v.get("url") or "")]
print("multi-P matches still missing ?p=:", len(bad), bad[:5])
