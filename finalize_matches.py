#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Post-process Bilibili matches:

1. Downgrade/reject weak matches: score<80 is only kept when the candidate title
   contains the EXACT livestream date; otherwise the link is rejected.
2. Continuation rows: the site splits a night that crosses midnight into two rows
   (e.g. 21:15-00:59 then 00:49-00:57). Rows starting before 06:00 with no link
   inherit the previous night's recording.
Writes data/bili_matches.json in place.
"""
import json, os, re
from datetime import date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")


def title_has_exact_date(iso, title):
    y, m, d = iso.split("-")
    t = title or ""
    pats = [
        "%s-%s-%s" % (y, int(m), int(d)), "%s-%s-%s" % (y, m, d),
        "%s.%s.%s" % (y, int(m), int(d)),
        "%s年%s月%s日" % (y, int(m), int(d)), "%s年%s月%s日" % (y, m, d),
    ]
    return any(p in t for p in pats)


def main():
    a = json.load(open(os.path.join(DATA, "archive.json"), encoding="utf-8"))
    rows = {r["date"]: r for r in a["rows"]}
    matches = json.load(open(os.path.join(DATA, "bili_matches.json"), encoding="utf-8"))

    rejected = suspected = 0
    for d, v in matches.items():
        if not v.get("bvid"):
            continue
        score = v.get("score") or 0
        if score >= 80:
            continue
        if title_has_exact_date(d, v.get("title")):
            v["confidence"] = "suspected"
            v["note"] = "标题含当日日期，但为片段/合集或弱证据，待核实"
            suspected += 1
        else:
            v["rejected_bvid"] = v.get("bvid")
            v["rejected_title"] = v.get("title")
            v["bvid"] = None
            v["url"] = None
            v["source"] = "rejected"
            v["confidence"] = "rejected"
            v["note"] = "候选标题日期与直播日期不符，已排除"
            rejected += 1

    # continuation rows (early-morning start, no link)
    cont = 0
    for d, r in rows.items():
        if r.get("link_pure") or r.get("link_barrage"):
            continue
        m = matches.get(d) or {}
        if m.get("bvid"):
            continue
        start = r.get("start") or ""
        if len(start) < 13:
            continue
        hour = int(start[11:13])
        if hour > 5:
            continue
        cur = date.fromisoformat(d)
        for back in (1, 2):
            prev = (cur - timedelta(days=back)).isoformat()
            pr = rows.get(prev) or {}
            pm = matches.get(prev) or {}
            if pr.get("link_pure"):
                matches[d] = {"bvid": None, "url": pr["link_pure"], "source": "continuation",
                              "confidence": "continuation",
                              "note": "该场为前夜 %s 场次的跨零点续接，录播与前夜相同" % prev,
                              "ref_date": prev, "title": pr.get("title") or ""}
                cont += 1
                break
            if pm.get("bvid"):
                matches[d] = {"bvid": pm["bvid"], "url": pm.get("url"), "source": "continuation",
                              "confidence": "continuation",
                              "title": pm.get("title"),
                              "note": "该场为前夜 %s 场次的跨零点续接，录播与前夜相同" % prev,
                              "ref_date": prev}
                cont += 1
                break

    json.dump(matches, open(os.path.join(DATA, "bili_matches.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    kept = sum(1 for v in matches.values() if v.get("bvid"))
    real = sum(1 for v in matches.values() if v.get("bvid") and v.get("confidence") != "suspected")
    print("rejected=%d suspected=%d continuation=%d | kept=%d real=%d" % (
        rejected, suspected, cont, kept, real))
    print("still none:", sum(1 for v in matches.values() if not v.get("bvid") and v.get("source") != "continuation"))


if __name__ == "__main__":
    main()
