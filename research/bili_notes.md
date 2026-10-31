# Bilibili 录播 research — hanser (憨色) livestream archive

_Scope: how to reliably find a Bilibili recording (录播/直播回放) for a given hanser livestream date.
Written 2026-10-31. All findings were verified live from this machine; see `bili_test_results.json`._

## TL;DR

1. The **only reliable source for hanser's own 【直播回放】 uploads is the series/合集 API**
   (`/x/series/archives`), not the space video list and not web search. Series **407852** on
   mid **11073** holds **554** official replays (2021-10-08 → now).
2. A single multi-part video, **BV1Gb4y1k7MX** (`東方延續·HANSER直播合集`, mid 24076741),
   has **589 P**, each one a stream, titled with the date — **2017-10-24 → 2021-06-23**.
   This is the backbone for the Douyu era.
3. Fan catalogue **hanser的aisaka (mid 7521963)**, 204 videos `【Hanser录播】YY-M-D`,
   covers **2020-01 → 2021-11**. **Rayzggz (10501326)** covers **2017-10 → 2018**.
4. Combined local catalogue: **1603 items / 1014 distinct stream dates** covering
   **2017-10-24 → 2026-10-29**. Only two months have no catalogued date: **2019-10** and
   **2021-09** (likely no streams; the online search fallback handles them if needed).
5. Matching precision is high: on the three required test dates the site link was the
   **rank-1 candidate 3/3**, and 2/3 supplementary historical probes hit rank 1 too.

## Accounts / UP主 that post hanser 录播

| mid | name | what they post | coverage |
|---|---|---|---|
| **11073** | hanser (official) | `【直播回放】{title} YYYY年M月D日HH点场` — official, often split per hour (`21点场`, `22点场`) | 2021-10 → 2026-10, 554 in series 407852 |
| **24076741** | 東方延續 | `HANSER 直播合集` = **BV1Gb4y1k7MX**, 589 P, P-title `【YYYY.M.D】…` | 2017-10-24 → 2021-06-23 |
| **7521963** | hanser的aisaka | `【Hanser录播】YY-M-D` (sometimes `…凌晨` / `…晚上`), 4h full streams; **pubdate lags the stream by up to ~5 days** | 2020-01 → 2021-11 |
| **10501326** | Rayzggz | `【hanser】YYYY-MM-DD 直播录制` (uploaded next day) | 2017-10 → 2018 |
| **45471875** | 中打码の゜ | `【斗鱼·直播回放】hanser…YYYY-MM-DD` — not in the local catalogue, reachable via search | 2018-12, 2019 |
| **45449982** | 爱爱爱丽丝_ | `【hanser-YYYY/MM/DD直播录像】…` | 2023-11 → 2024 |
| 317478069 | Hanser直播高能精剪 | `『Hanser』YYYY年M月D日直播实录` — **精剪, not full** (use only as a signal) | 2020-2021 |
| 67175080 / 671291814 | 吃枣的粽子 / 南梦小铺 | generic fan recorders; dual-view / auto-record copies containing `hanser` | 2024-2026 |
| 24076741 | 東方延續 | also has single-stream parts, see above | — |

Not hanser-specific (avoid): `录播员老夏` (8850227) and `被窝的爆米花` (180119) are generic
multi-streamer recording channels; they only match by date coincidence.

## API endpoints — what works, what does not

**Working**

* `GET https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword=…&page=N`
  — global web search, **no WBI signature needed**, but **requires a `buvid3` cookie**.
  Returns 20 items/page; `numResults` caps at 1000 (50 pages). This is the online fallback.
* `GET https://api.bilibili.com/x/web-interface/search/type?search_type=bili_user&keyword=…&page=N&from_source=webtop_search&search_source=5`
  — user search. **Without `from_source`/`search_source` it silently returns 0 results.**
* `GET https://api.bilibili.com/x/series/archives?mid=11073&series_id=407852&only_normal=true&sort=desc&pn=1&ps=30`
  — **the official 直播回放 list.** No WBI. Most reliable endpoint found.
* `GET https://api.bilibili.com/x/space/wbi/arc/search?mid=&ps=50&pn=1&order=pubdate&platform=web&web_location=1550101`
  — a UP's 投稿 list. **WBI-signed**; also needs the `dm_img_*` params
  (`dm_img_list`, `dm_img_str`, `dm_cover_img_str`, `dm_img_inter`) or it 412s.
  **Excludes 直播回放/tid=174** — that is why the official replays are invisible here.
* `GET https://api.bilibili.com/x/player/pagelist?bvid=BV1Gb4y1k7MX` — 589 parts of the multi-P archive.
* `GET https://api.bilibili.com/x/web-interface/view?bvid=…` — ground truth title/owner/pubdate/duration; official
  replays expose `tid=174`.
* `GET https://api.bilibili.com/x/web-interface/nav` — returns `wbi_img` even unauthenticated (code -101).

**Blocked / useless**

* `/x/space/live/replay`, `/xlive/web-room/v1/video/replayList`,
  `/x/polymer/web-space/common/live-replay`, `/x/polymer/web-space/series_archives_list` → **404**.
* `/x/space/arc/search` (old, unsigned) → `code -799 请求过于频繁`.
* `search/type?...&tids=174` → returns old fan clips, **never** the official 直播回放.
* Plain `search/type` **without any cookie → HTTP 412** (`Precondition Failed`). Bootstrap
  cookies first.

## WBI signing & cookies

* A `buvid3` cookie is mandatory. Get it by plain `GET https://www.bilibili.com/` (no login;
  also `GET /x/frontend/finger/spi` for `b_3`/`b_4`). Cache it; re-bootstrap on a risk streak.
  `SESSDATA` is **not** required for any of the above — pass `--cookie-file` if an IP ever gets stuck.
* WBI (only for `/x/space/wbi/*`): read `data.wbi_img.img_url` + `sub_url` from `/nav`, take the
  two filenames without extension, concatenate, permute with the standard 64-entry mixin table,
  keep 32 chars. Add `wts=<unix>` and `w_rid=md5(sorted_query + mixin_key)`, with `quote`
  (`%20`, not `+`) when URL-encoding. Keys rotate; re-fetch `/nav` on failure.

## Rate limits observed (polite thresholds)

| endpoint | safe pacing | behaviour seen |
|---|---|---|
| `search/type` | ~1.2 s | ~30 sequential queries fine; cache locally |
| `/x/series/archives` | ~1.5 s | no failures observed |
| `/x/space/wbi/arc/search` | **≥2 s** | bursts of 5-10 trigger HTTP 412 / `code -352 风控校验失败`; page 1-2 succeed, later pages fail. Back off 6-30 s and refresh cookies, then continue. |

Retry policy used in the tool: exponential 6 s → 30 s, one cookie re-bootstrap per streak,
`urllib` only (no `requests`), browser UA + `Referer`, `Accept-Language: zh-CN`.

## Search-result fields available

`bvid, aid, title` (**wrapped in `<em class="keyword">` — strip it**), `author, mid, pubdate`
(unix), `duration` (`"175:25"`), `description, tag, arcurl, play, danmaku, typeid, senddate,
uid/uname`. `pubdate` relates to *upload*, not to the stream date — fan uploads can lag 1-5 days.

## Pagination

* Search: `page=1..50`, fixed 20/page; stop early when a query stops yielding new bvids.
* Series: `pn=1..N`, `ps=30`; loop until `page.total` (=554) is consumed.
* Space: `pn=1..N`, `ps=50`; loop until `page.count` is consumed.
* Multi-P: one call to `/x/player/pagelist`, then treat each P as its own candidate.

## Recommended matching strategy (implemented)

1. **Build a local catalogue once** (`--build-index`): official series + the 589-P compilation
   parts + whitelisted fan catalogues → `tools/.cache/bili_index.json` (1603 items, ~30 requests).
2. For each date, score every catalogue item:
   * date in title: **+60** if full `YYYY-M-D`/`YYYY年M月D日`/`YYYY.M.D`, **+48** for bare `M-D`;
   * upload date proximity: **+30 / +22 / +16 / +10** for 0 / 1 / 2 / 3 days, decaying to 0 at 8 days;
   * author whitelist: **+16…+26** (official 26, aisaka 24, compilation 22, Rayzggz 20, …);
   * 录播-ish title keyword: +10 直播回放, +9 直播录像, +8 录播, +6 回放 …;
   * title-hint overlap (`冒汗电台`): +15 exact / +5 per token;
   * duration 20 min-9 h: +6; < 3 min: -20 (clips);
   * hard gates: drop items with **no hanser evidence** (title/desc must mention
     hanser/憨色/冒汗电台/… unless the mid is whitelisted) and drop items with **no date signal**
     (no date in title and upload > 7 days away). This kills the many unrelated
     "直播回放 2020-01-05" channels that also put dates in their titles.
3. If the best score is **< 70**, fall back to web search (`--online auto`); use
   `--online never` for fast offline batch runs. Query variants: `hanser 录播 YYYY-MM-DD`,
   `hanser 直播录制 YYYY-MM-DD`, `hanser 直播录像 YYYY-MM-DD`, `hanser 录播 YYYY年M月D日`,
   `hanser 直播回放 YY-M-D`, plus title-hint variants; **do not** require `hanser` in every
   query for official titles that omit it (the series catalogue already has them).

## Catches

* **Official replays are invisible to search and to the space list.** Never rely on search for
  the 2021-10+ era; use the series.
* One night can have **multiple valid candidates**: official `21点场` + `22点场` (split upload),
  dual-view fan copies, auto-recorder copies, 歌切 partials. Ranking handles it; when the dataset
  needs exactly one link, prefer the official single-part replay for its timestamp.
* Multi-P archive parts share **one bvid** — dedupe by `bvid + "#p" + page` and use `?p=N` URLs.
* `Highlights/精剪/切片/混剪/合集/盘点` are penalized but still sometimes rank 4-5; treat
  `reason: bad:*` and short durations as "signal only, not a full recording".
* `2019-10` and `2021-09` are empty in the catalogue; a 2019-05-11 probe returned 0 candidates
  (likely no stream — Mon/Wed/Fri schedule), so empty is a valid answer.
* `book`/`SESSDATA` login is unnecessary; if HTTP 412 persists after a cookie refresh the IP is
  flagged — back off for minutes rather than retrying.

## Run it

```powershell
$py = "C:\Users\Admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

# one-time / occasional catalogue refresh (~30 requests, ~1 min, rate-limit aware)
& $py tools\bili_search.py --build-index

# per date (offline catalogue, instant; falls back to web search if no strong hit)
& $py tools\bili_search.py --date 2026-10-26 --title "冒汗电台"

# batch-friendly: no network at all
& $py tools\bili_search.py --date 2020-01-03 --online never --json out.json

# library use
#   import bili_search as bs
#   c = bs.BiliClient(); bs.match_stream(c, "2020-01-03", "冒汗电台")
```

## Confidence

* Official era 2021-10 → 2026-10: **very high** (series is authoritative; 3/3 test dates rank 1).
* Douyu era 2017-10 → 2021-06: **high** (589-P compilation; 2/2 probes rank 1, though a stream
  can be split across consecutive parts).
* 2019-10 / 2021-09 and any date with no Bilibili upload: expect empty results; recommend the
  team records "not found" rather than forcing a neighbor-date match (the `pub_delta_*` reasons
  make a wrong-date guess visible).

---

## 第二轮：深挖与质检结果（2026-10-31 晚）

### A. 38 个未匹配日期的深挖结论

**找回（标题/内容可确认属于 hanser 的录播）：0 个。**

已穷举的证据链：

1. **2017-07-18 ~ 2017-10-07（共 24 个日期）→ 判定 B 站无存档。**
   東方延續的 589P 合集中最早一场是 `2017-10-24`，Rayzggz 最早是 `2017-10-25`，
   `中打码の゜` 的 hanser 斗鱼回放最早是 `2018-11-17`，`hanser的aisaka` 最早 `2019-12-27`。
   对 2017-07..2017-11 做了发布时间窗搜索（`斗鱼 hanser` / `hanser 直播回放` / `hanser 直播录制`），
   2017 年只有 Rayzggz（10 月起）与 小笼包包子铺 的 **YUKIri 主视角**录像，没有 hanser 自己的录播。
2. **2018-04-23 / 2018-04-30 / 2018-06-16 → 无 hanser 录播。**
   合集中 4-20、4-24~4-27、5-1 都在，唯独缺这些天；发布时间窗搜索只找到 2018-04-29 的
   三无×hanser 合唱片段（39 分钟，非整场）。
3. **2019 年 11 个日期（03-21/24、04-08/16/17/18、05-11、06-06、07-01/29、09-06/30）→ 无 hanser 录播。**
   合集中均为"前后场次有、这几天没有"；`Hanser直播高能精剪` 的"直播实录"从 `2019-10-21` 才开始，
   2019 年 10 月前只有精剪片段。
4. **8 个日期连同日录像都没有（更确定的"无上传"）：**
   `2017-08-08, 2017-08-12, 2017-08-30, 2017-10-03, 2018-06-16, 2019-03-21, 2019-03-24, 2019-04-18`

**⚠ 30 个日期存在"同日 YUKIri 直播录制"（小笼包包子铺 39713106，已枚举全部 1331 个视频），
但标题绝大多数只写 `YUKIri直播录制`，只有少数写 `YUKIrixHanser`。无法证明该场 hanser 在场，
按"不要硬凑"原则**未计入找回**，只作为待内容复核的线索写入
`research/bili_matches_deep.json` 的 `unverified_candidates`。其中 `joint_hint=true`
（标题含 YH/Hanser/憨）的可优先复核。

### B. 质检：12 场抽查（5 medium + 4 suspected + 3 rejected）

- **系统性 BUG（最重要）**：**131 条**匹配的 `bvid` 都是多P合集 `BV1Gb4y1k7MX`，但 `page` 为 null、
  `url` 没有 `?p=` → 打开的是 P1（错误场次）。`bili_matches_deep.json` 的 `matches` 已给出
  **131 条带正确 `?p=N` 的修正 URL**，可直接合并覆盖。
- **应降级/剔除的"假录播"3 条**：`2017-08-18`(280s)、`2017-09-14`(267s)、`2017-09-16`(260s)
  ——都是翻唱/切片（标题 `hanser——irony` 等），不是整场录播。
- **1 条是歌曲合集**：`2017-10-08` → `BV1WZ4y1y7jL` 《告白气球 14P 全合集》，非直播录像。
- **1 条是剪辑片段**：`2017-08-03` → `BV1PY4y1k7o1`（40 分钟"早期直播逗鸟鸟套套"，2022 年上传）。
- **2 条 rejected 判定正确**：标题日期与直播日期不符（2017-09-12 实为 09-09；2018-03-06 实为 02-28）。
- **medium 内容本身可用**（抽查的 `2017-11-24` Rayzggz 等自洽），问题只在多P URL。

### C. 合并建议

- `matches`（131 条 URL 修正）→ 覆盖对应日期现有记录，保留其余字段；
- `no_upload_found_anywhere` 8 个日期 + 上述 2017 结论 → 标记"B站无录播"；
- `unverified_candidates` → 单独存疑字段，建议人工抽听 1-2 条确认 hanser 是否在场后再决定是否合并。
