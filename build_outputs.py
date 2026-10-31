#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate human + machine deliverables from data/archive.json.

Outputs (under output/):
  hanser直播记录_完整档案.md      (index + per-year sections, links to transcripts)
  transcripts/YYYY-MM-DD.md      (full transcript for streams that have one)
  hanser直播记录档案.xlsx         (总表 / 歌单明细 / 转录索引 / 统计)
  archive.json                   (copy of machine-readable data)
"""
import json, os, re
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "output")
TR = os.path.join(OUT, "transcripts")
os.makedirs(TR, exist_ok=True)

ARCHIVE = os.path.join(DATA, "archive.json")

def load():
    a = json.load(open(ARCHIVE, encoding="utf-8"))
    rows = a["rows"]
    return a, rows

def bv_of(url):
    m = re.search(r"(BV[0-9A-Za-z]{10})", url or "")
    return m.group(1) if m else ""

def clean_transcript(s):
    if not s:
        return ""
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)      # editorial markers
    s = s.replace("\u200b", "").replace("\xa0", " ")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

CONF_ZH = {"high": "高", "medium": "中", "low-medium": "中低", "low": "低",
           "none": "无", "offline": "目录匹配", "suspected": "疑似", "continuation": "续接"}

def fmt_time(s):
    # "2020-01-03 20:00:00" -> "2020-01-03 20:00"
    if not s:
        return ""
    return s[:16]

def fmt_span(r):
    st, en = r.get("start") or "", r.get("end") or ""
    if not st:
        return ""
    if not en:
        return fmt_time(st)
    if st[:10] == en[:10]:
        return "%s – %s" % (fmt_time(st), en[11:16])
    return "%s – %s（次日）" % (fmt_time(st), fmt_time(en))

def dur_str(m):
    if not m:
        return ""
    h, mm = divmod(int(m), 60)
    s = ("%d小时%02d分" % (h, mm)) if h else ("%d分钟" % mm)
    if m > 600:
        s += "（站点数据异常）"
    return s

def rec_link(r):
    """Unified recording link: site link first, else bili match."""
    lp = r.get("link_pure") or ""
    lb = r.get("link_barrage") or ""
    if lp:
        return lp, "站点·纯净版"
    if lb:
        return lb, "站点·含弹幕"
    st = r.get("bili_status") or ""
    if st == "matched":
        conf = CONF_ZH.get(r.get("bili_conf"), r.get("bili_conf") or "")
        return r.get("bili_url") or "", "B站匹配（%s置信度）" % conf
    if st == "continuation":
        return r.get("bili_url") or "", "B站匹配（跨零点续接）"
    if st == "suspected":
        return r.get("bili_url") or "", "B站疑似（待核实）"
    return "", "未找到"

MD_HEAD = """# hanser（憨色）直播记录完整档案

> 数据来源：毛怪俱乐部 · [直播记录](https://song.2550505.com/livestreams) / [直播歌单](https://song.2550505.com/music)
> 抓取整理时间：{gen}
> 覆盖范围：{first} ～ {last}，共 **{n} 场直播记录**，其中 **{with_songs} 场有歌单**、**{with_tr} 场有文本转录**。

## 说明

- **歌单**：每场直播中演唱歌曲的曲目名、原唱、演唱时间点（来自站点「直播记录」页）。
- **文本转录**：站点收录的直播文字记录（带时间戳的转录稿），有则单独存放到 `transcripts/` 目录，本文件内给出链接。
- **录播链接**：优先使用站点登记的 B 站录播地址（纯净版 / 含弹幕版）；站点没有的，通过 B 站检索 hanser 直播录播进行日期匹配，并标注匹配结果。

## 年度索引

{year_index}

## 统计

{stats}

"""

def build_markdown(a, rows):
    by_year = {}
    for r in rows:
        by_year.setdefault(r["date"][:4], []).append(r)

    stats = {
        "streams": len(rows),
        "songs": sum(r["song_count"] for r in rows),
        "with_songs": sum(1 for r in rows if r["song_count"]),
        "with_tr": sum(1 for r in rows if r["has_transcript"]),
        "site_link": sum(1 for r in rows if r.get("link_pure") or r.get("link_barrage")),
        "bili_match": sum(1 for r in rows if not (r.get("link_pure") or r.get("link_barrage"))
                          and r.get("bili_status") in ("matched", "continuation")),
        "suspected": sum(1 for r in rows if not (r.get("link_pure") or r.get("link_barrage"))
                         and r.get("bili_status") == "suspected"),
        "no_link": sum(1 for r in rows if not (r.get("link_pure") or r.get("link_barrage"))
                       and r.get("bili_status") not in ("matched", "continuation", "suspected")),
    }
    stats_md = "\n".join([
        "- 直播场次：**%d**" % stats["streams"],
        "- 有歌单场次：**%d**（共 %d 首歌）" % (stats["with_songs"], stats["songs"]),
        "- 有文本转录场次：**%d**" % stats["with_tr"],
        "- 有站点登记录播：**%d**" % stats["site_link"],
        "- 站点无录播、B 站检索匹配成功：**%d**；B 站疑似（待核实）：**%d**；未找到：**%d**" % (
            stats["bili_match"], stats["suspected"], stats["no_link"]),
        "",
        "说明：2017-07 ~ 2019 年上半年部分场次站点只收录了歌单，未记录标题 / 起止时间 / 转录 / 录播，"
        "此类场次在下方标记为「站点未记录」，录播链接由 B 站按日期+标题检索匹配（标注置信度）；"
        "匹配证据不足的列为「疑似」；确实找不到的列入文末附录。",
    ])

    year_index = "\n".join(
        "- [%s 年](#%s-年) — %d 场，%d 首歌" % (y, y, len(v), sum(r["song_count"] for r in v))
        for y, v in sorted(by_year.items(), reverse=True))

    gen = a.get("generated_at", "")
    parts = [MD_HEAD.format(gen=gen, first=rows[0]["date"], last=rows[-1]["date"],
                            n=len(rows), with_songs=stats["with_songs"],
                            with_tr=stats["with_tr"], year_index=year_index, stats=stats_md)]

    for y, v in sorted(by_year.items(), reverse=True):
        parts.append("\n---\n\n## %s 年\n" % y)
        for r in sorted(v, key=lambda x: x["date"], reverse=True):
            parts.append(render_stream(r))

    # appendix: streams without a verified recording link
    no_link = [r for r in rows if not (r.get("link_pure") or r.get("link_barrage"))
               and r.get("bili_status") not in ("matched", "continuation", "suspected")]
    susp = [r for r in rows if not (r.get("link_pure") or r.get("link_barrage"))
            and r.get("bili_status") == "suspected"]
    if susp:
        parts.append("\n---\n\n## 附录 A：疑似录播（待核实，%d 场）\n" % len(susp))
        parts.append("B 站检索到标题日期一致的视频，但为片段/合集或证据较弱，请自行核实。\n")
        parts.append("| 日期 | 标题 | 疑似视频 | 说明 |")
        parts.append("|------|------|----------|------|")
        for r in sorted(susp, key=lambda x: x["date"]):
            bm = r.get("bili_match") or {}
            parts.append("| %s | %s | [%s](%s) | %s |" % (
                r["date"], (r.get("title") or "（未记录）").replace("|", "\\|"),
                (bm.get("title") or "").replace("|", "\\|"), r.get("bili_url") or "",
                (bm.get("note") or "").replace("|", "\\|")))
    if no_link:
        parts.append("\n---\n\n## 附录 B：未找到录播的场次（%d 场）\n" % len(no_link))
        parts.append("这些场次站点未登记录播，且在 B 站按日期检索没有可靠匹配；"
                     "歌单与转录（如有）仍在上方对应小节中。\n")
        deep_fp = os.path.join(BASE, "research", "bili_matches_deep.json")
        if os.path.exists(deep_fp):
            try:
                deep = json.load(open(deep_fp, encoding="utf-8"))
                confirmed = deep.get("confirmed_no_archive") or []
                any_none = deep.get("no_upload_found_anywhere") or []
                if confirmed:
                    parts.append("- 深挖结论：**2017-07-18 ～ 2017-10-07 期间 B 站没有 hanser 专属录播存档**"
                                 "（官方「直播回放」合集始于 2021-10，589P 直播合集始于 2017-10-24，"
                                 "粉丝录播号最早 2017-10-25），因此这一段的场次只能确认「无录播」。")
                if any_none:
                    parts.append("- 其中 %s 这 %d 个日期全网（含当日同场直播的其它录像）也未找到任何上传。\n" % (
                        "、".join(any_none), len(any_none)))
                else:
                    parts.append("")
            except Exception:
                pass
        parts.append("| 日期 | 星期 | 标题 | 歌曲数 | 文本转录 |")
        parts.append("|------|------|------|--------|----------|")
        for r in sorted(no_link, key=lambda x: x["date"]):
            parts.append("| %s | %s | %s | %d | %s |" % (
                r["date"], r["weekday"], (r.get("title") or "（未记录）").replace("|", "\\|"),
                r["song_count"], "有" if r["has_transcript"] else "无"))

    md = "\n".join(parts)
    open(os.path.join(OUT, "hanser直播记录_完整档案.md"), "w", encoding="utf-8").write(md)

    # per-year files
    yd = os.path.join(OUT, "by_year")
    os.makedirs(yd, exist_ok=True)
    for y, v in sorted(by_year.items()):
        yparts = ["# hanser 直播记录 · %s 年\n" % y,
                  "> 共 %d 场，%d 首歌。完整索引见上级目录 `hanser直播记录_完整档案.md`。\n" % (
                      len(v), sum(r["song_count"] for r in v))]
        for r in sorted(v, key=lambda x: x["date"], reverse=True):
            yparts.append(render_stream(r, tr_prefix="../transcripts/"))
        open(os.path.join(yd, "%s.md" % y), "w", encoding="utf-8").write("\n".join(yparts))

    # csv (utf-8-sig for Excel)
    import csv
    with open(os.path.join(OUT, "hanser直播记录总表.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        wtr = csv.writer(fh)
        wtr.writerow(["日期", "星期", "直播标题", "开始时间", "结束时间", "时长(分钟)",
                      "歌曲数", "歌单", "有文本转录", "转录字数", "录播链接", "录播来源"])
        for r in rows:
            link, src = rec_link(r)
            wtr.writerow([r["date"], r["weekday"], r.get("title") or "",
                          fmt_time(r.get("start")), fmt_time(r.get("end")),
                          r.get("duration_min") or "", r["song_count"],
                          " / ".join(s["name"] for s in r["songs"]),
                          "有" if r["has_transcript"] else "无",
                          r["transcript_chars"] if r["has_transcript"] else "",
                          link, src])
    return stats

def render_stream(r, tr_prefix="transcripts/"):
    lines = []
    title = r.get("title") or "（站点未记录标题）"
    lines.append("\n### %s（%s）· %s\n" % (r["date"], r["weekday"], title))
    meta = []
    if r.get("start"):
        meta.append("**时间**：%s（%s）" % (fmt_span(r), dur_str(r.get("duration_min"))))
    if r.get("brief"):
        meta.append("**标签**：%s" % r["brief"])
    link, src = rec_link(r)
    if r.get("link_pure") or r.get("link_barrage"):
        extra = []
        if r.get("link_pure"):
            extra.append("[纯净版](%s)" % r["link_pure"])
        if r.get("link_barrage"):
            extra.append("[含弹幕版](%s)" % r["link_barrage"])
        meta.append("**录播**：" + " · ".join(extra) + "（站点登记）")
    elif r.get("bili_status") in ("matched", "continuation", "suspected"):
        bm = r.get("bili_match") or {}
        conf = CONF_ZH.get(bm.get("confidence"), bm.get("confidence") or "")
        t = (bm.get("title") or "").replace("|", "\\|")
        if r.get("bili_status") == "suspected":
            meta.append("**录播**：疑似（待核实）[%s](%s) — %s" % (
                t, link, bm.get("note") or ""))
        elif bm.get("source") == "continuation":
            meta.append("**录播**：[与前夜同一录播](%s) — %s" % (link, bm.get("note") or ""))
        else:
            meta.append("**录播**：[B站匹配 · %s置信度](%s) — %s（%s）" % (
                conf, link, t, bm.get("author") or ""))
    else:
        meta.append("**录播**：未找到（站点未登记，B站检索无可靠匹配）")
    lines.extend("- " + m for m in meta)

    if r["songs"]:
        lines.append("\n**歌单（%d 首）**\n" % len(r["songs"]))
        lines.append("| # | 时间 | 歌曲 | 原唱 |")
        lines.append("|---|------|------|------|")
        for i, s in enumerate(r["songs"], 1):
            t = (s.get("time") or "")[:8]
            name = (s.get("name") or "").replace("|", "\\|")
            auth = (s.get("author") or "").replace("|", "\\|")
            lines.append("| %d | %s | %s | %s |" % (i, t, name, auth))
    else:
        lines.append("\n**歌单**：本次直播无演唱记录 / 站点未收录歌单")

    if r["has_transcript"]:
        fn = tr_prefix + "%s.md" % r["date"]
        lines.append("\n**文本转录**：有（约 %d 字）→ [%s](%s)" % (
            r["transcript_chars"], fn, fn))
        body = clean_transcript(r["content"])
        open(os.path.join(TR, r["date"] + ".md"), "w", encoding="utf-8").write(
            "# %s（%s）· %s — 直播文本转录\n\n来源：https://song.2550505.com/livestreams?date=%s\n\n---\n\n%s\n" % (
                r["date"], r["weekday"], r.get("title") or "（站点未记录标题）", r["date"], body))
    else:
        lines.append("\n**文本转录**：无")
    return "\n".join(lines) + "\n"

def build_xlsx(a, rows):
    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill
        from openpyxl.utils import get_column_letter
    except Exception as e:
        print("openpyxl missing:", e)
        return
    wb = openpyxl.Workbook()

    # ---- 总表 ----
    ws = wb.active
    ws.title = "直播总表"
    heads = ["序号", "日期", "星期", "直播标题", "开始时间", "结束时间", "时长",
             "歌曲数", "歌单", "文本转录", "转录字数", "录播链接", "录播来源",
             "匹配视频标题", "纯净版录播", "含弹幕录播"]
    ws.append(heads)
    for i, r in enumerate(rows, 1):
        link, src = rec_link(r)
        songs_txt = " / ".join(s["name"] for s in r["songs"])
        bm = (r.get("bili_match") or {})
        ws.append([
            i, r["date"], r["weekday"], r.get("title") or "", fmt_time(r.get("start")),
            fmt_time(r.get("end")), dur_str(r.get("duration_min")), r["song_count"],
            songs_txt, "有" if r["has_transcript"] else "无",
            r["transcript_chars"] if r["has_transcript"] else "",
            link, src,
            (bm.get("title") or "") if (not (r.get("link_pure") or r.get("link_barrage"))
                                        and r.get("bili_status") in ("matched", "suspected")) else "",
            r.get("link_pure") or "", r.get("link_barrage") or "",
        ])
    w = {"A": 6, "B": 12, "C": 6, "D": 24, "E": 17, "F": 17, "G": 10,
         "H": 8, "I": 60, "J": 9, "K": 10, "L": 44, "M": 22, "N": 40, "O": 42, "P": 42}
    for k, v in w.items():
        ws.column_dimensions[k].width = v
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="4472C4")
        c.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = "A1:P%d" % ws.max_row
    for ridx in range(2, ws.max_row + 1):
        for col in (12, 15, 16):
            c = ws.cell(row=ridx, column=col)
            if c.value and str(c.value).startswith("http"):
                c.hyperlink = str(c.value)
                c.font = Font(color="0563C1", underline="single")

    # ---- 歌单明细 ----
    ws2 = wb.create_sheet("歌单明细")
    ws2.append(["日期", "星期", "直播标题", "演唱时间", "歌曲", "原唱"])
    for r in rows:
        for s in r["songs"]:
            ws2.append([r["date"], r["weekday"], r.get("title") or "",
                        (s.get("time") or "")[:8], s.get("name") or "", s.get("author") or ""])
    for k, v in {"A": 12, "B": 6, "C": 20, "D": 10, "E": 40, "F": 30}.items():
        ws2.column_dimensions[k].width = v
    for c in ws2[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="70AD47")
    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = "A1:F%d" % ws2.max_row

    # ---- 转录索引 ----
    ws3 = wb.create_sheet("转录索引")
    ws3.append(["日期", "直播标题", "转录字数", "文件"])
    for r in rows:
        if r["has_transcript"]:
            ws3.append([r["date"], r.get("title") or "", r["transcript_chars"],
                        "transcripts/%s.md" % r["date"]])
    for k, v in {"A": 12, "B": 22, "C": 10, "D": 34}.items():
        ws3.column_dimensions[k].width = v
    for c in ws3[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="ED7D31")

    # ---- 统计 ----
    ws4 = wb.create_sheet("统计")
    ws4.append(["指标", "数值"])
    st = [
        ("直播场次", len(rows)),
        ("有歌单场次", sum(1 for r in rows if r["song_count"])),
        ("歌曲条目总数", sum(r["song_count"] for r in rows)),
        ("有文本转录场次", sum(1 for r in rows if r["has_transcript"])),
        ("站点登记录播场次", sum(1 for r in rows if r.get("link_pure") or r.get("link_barrage"))),
        ("B站检索匹配场次", sum(1 for r in rows if not (r.get("link_pure") or r.get("link_barrage"))
                                and r.get("bili_status") in ("matched", "continuation"))),
        ("B站疑似录播场次", sum(1 for r in rows if not (r.get("link_pure") or r.get("link_barrage"))
                                and r.get("bili_status") == "suspected")),
        ("仍缺录播场次", sum(1 for r in rows if not (r.get("link_pure") or r.get("link_barrage"))
                            and r.get("bili_status") not in ("matched", "continuation", "suspected"))),
        ("最早一场", rows[0]["date"] if rows else ""),
        ("最近一场", rows[-1]["date"] if rows else ""),
        ("数据抓取时间", a.get("generated_at", "")),
    ]
    for k, v in st:
        ws4.append([k, v])
    ws4.column_dimensions["A"].width = 22
    ws4.column_dimensions["B"].width = 24

    # ---- 无录播场次 ----
    ws5 = wb.create_sheet("无录播场次")
    ws5.append(["日期", "星期", "直播标题", "歌曲数", "文本转录", "备注"])
    for r in rows:
        if (r.get("link_pure") or r.get("link_barrage")):
            continue
        if r.get("bili_status") in ("matched", "continuation"):
            continue
        note = "B站疑似（待核实）" if r.get("bili_status") == "suspected" else "B站检索无匹配"
        ws5.append([r["date"], r["weekday"], r.get("title") or "", r["song_count"],
                    "有" if r["has_transcript"] else "无", note])
    for k, v in {"A": 12, "B": 6, "C": 26, "D": 8, "E": 9, "F": 18}.items():
        ws5.column_dimensions[k].width = v
    for c in ws5[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="C00000")

    wb.save(os.path.join(OUT, "hanser直播记录档案.xlsx"))
    print("xlsx saved")

if __name__ == "__main__":
    a, rows = load()
    stats = build_markdown(a, rows)
    build_xlsx(a, rows)
    json.dump(a, open(os.path.join(OUT, "archive.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("stats:", stats)
