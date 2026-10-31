#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bili_search.py — find the Bilibili recording (录播/直播回放) of a hanser livestream date.

Standalone (stdlib only). Never reads the main dataset; inputs are just a date
(YYYY-MM-DD) and an optional title hint.

Candidate sources, in order of reliability:
  1. Official "系列" 407852 「直播回放」 on mid 11073 (hanser).
     /x/series/archives returns hanser's own 【直播回放】 uploads. These have
     tid=174 and are NOT returned by /x/space/wbi/arc/search, nor reliably by
     the global search API, so this series is the primary source for 2021-10..now.
  2. Fan archive UP catalogs (/x/space/wbi/arc/search), cached:
       hanser的aisaka 7521963   【Hanser录播】YY-M-D       2020-01..2021-11
       Rayzggz        10501326  【hanser】YYYY-MM-DD 直播录制  2017-10..2018
       爱爱爱丽丝_     45449982  【hanser-YYYY/MM/DD直播录像】  2024
  3. Global web search (/x/web-interface/search/type) as an online fallback for
     dates that the cached index cannot cover (e.g. 2018-2019 Douyu era).

Scoring: date-in-title > pubdate proximity > author whitelist > 录播 title
keywords > title-hint overlap > plausible duration. Candidates without any
hanser evidence are pushed below the noise floor, which is what keeps generic
"直播回放 2020-01-05" channels from unrelated streamers out of the results.

Usage:
  python tools/bili_search.py --date 2020-01-03
  python tools/bili_search.py --date 2026-10-26 --title "冒汗电台"
  python tools/bili_search.py --date 2026-10-07 --json out.json
  python tools/bili_search.py --build-index            # refresh the local catalog
  python tools/bili_search.py --date 2019-05-11 --online always

Notes:
  * A buvid3 cookie is mandatory; without it the search API answers HTTP 412.
    It is bootstrapped from https://www.bilibili.com/ (no login required) and
    cached in tools/.bili_cookies.json.
  * Space/series endpoints are rate-limit sensitive (HTTP 412, code -352
    "风控校验失败"). Default pacing is 1.5 s with exponential backoff, cookie
    refresh once per risk streak.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import http.cookiejar
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(TOOL_DIR, ".cache")
COOKIE_FILE = os.path.join(TOOL_DIR, ".bili_cookies.json")
INDEX_FILE = os.path.join(TOOL_DIR, ".cache", "bili_index.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

# mid -> (label, weight).  Only accounts that genuinely archive hanser streams.
ARCHIVE_UPS = {
    11073:    ("hanser (official)", 26),
    7521963:  ("hanser的aisaka", 24),
    24076741: ("東方延續·HANSER直播合集", 22),
    10501326: ("Rayzggz", 20),
    45449982: ("爱爱爱丽丝_", 18),
    45471875: ("中打码の゜", 16),
}

# Multi-part (分P) archive videos: one BV per stream, every P is one stream.
# (mid, bvid, label) — the by-far best source for the 2017-10..2021-06 Douyu era.
ARCHIVE_MULTIPART = [
    (24076741, "BV1Gb4y1k7MX", "東方延續·HANSER直播合集"),   # 589 P, 2017-10-24..2021-06-23
]

# (mid, series_id, label) — series/合集 that hold 直播回放 uploads (tid=174).
ARCHIVE_SERIES = [
    (11073, 407852, "hanser官方·直播回放"),
]

# mid -> pages to walk when building the index (30-50 items/page)
INDEX_SPACE_PAGES = {
    7521963: 8,
    10501326: 4,
    45449982: 2,
    45471875: 2,
}

HANSER_HINTS = ["hanser", "憨色", "冒汗电台", "花生与葱花", "小缘", "憨八嘎", "hanser直播"]
RETRYABLE_CODES = {-352, -412, -503, -799}


# --------------------------------------------------------------------------- #
# helpers: titles, dates, durations
# --------------------------------------------------------------------------- #
_EM_TAG = re.compile(r"</?em[^>]*>")


def clean_title(s: str) -> str:
    """Strip <em class="keyword"> markup and unescape entities."""
    return html.unescape(_EM_TAG.sub("", s or "")).replace("\xa0", " ").strip()


def pubdate_iso(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def parse_duration(d) -> int:
    """'MM:SS' / 'HH:MM:SS' / int -> seconds."""
    if isinstance(d, (int, float)):
        return int(d)
    if not d:
        return 0
    d = str(d).strip()
    if re.fullmatch(r"\d+", d):
        return int(d)
    secs, mult = 0, 1
    for part in reversed(d.split(":")):
        try:
            secs += int(part) * mult
        except ValueError:
            return 0
        mult *= 60
    return secs


_DATE_FULL = re.compile(r"(20\d{2})\s*[-年./]\s*(\d{1,2})\s*[-月./]\s*(\d{1,2})\s*[日号]?")
_DATE_COMPACT = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_DATE_SHORT = re.compile(r"(?<!\d)(\d{2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})(?!\d)")
_DATE_MD = re.compile(r"(?<!\d)(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*[日号]?(?!\d)")


def title_dates(text: str) -> list[tuple[str | None, int, int]]:
    """Extract (year|None, month, day) candidates from a title/description."""
    out: list[tuple[str | None, int, int]] = []
    t = text or ""

    def add(y, m, d):
        try:
            m, d = int(m), int(d)
        except Exception:
            return
        if 1 <= m <= 12 and 1 <= d <= 31:
            out.append((y, m, d))

    for m in _DATE_FULL.finditer(t):
        add(m.group(1), m.group(2), m.group(3))
    for m in _DATE_COMPACT.finditer(t):
        add(m.group(1), m.group(2), m.group(3))
    for m in _DATE_SHORT.finditer(t):
        add("20" + m.group(1), m.group(2), m.group(3))
    if not any(y for y, _, _ in out):
        for m in _DATE_MD.finditer(t):
            add(None, m.group(1), m.group(2))
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _date_match_score(iso_date: str, cand_text: str) -> tuple[int, list[str]]:
    """0..60 — how explicitly cand_text names iso_date."""
    try:
        target = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except ValueError:
        return 0, []
    best, why = 0, []
    for y, m, d in title_dates(cand_text):
        try:
            got = datetime(2000 if y is None else int(y), m, d).date()
        except ValueError:
            continue
        if got == target:
            if y is not None:
                return 60, ["title-date-exact"]
            best, why = max(best, 48), ["title-monthday"]
    return best, why


def _pubdate_score(iso_date: str, pub_ts) -> tuple[int, str]:
    try:
        target = datetime.strptime(iso_date, "%Y-%m-%d")
        pub = datetime.fromtimestamp(int(pub_ts), CST).replace(tzinfo=None)
    except Exception:
        return 0, ""
    delta = abs((pub.date() - target.date()).days)
    score = {0: 30, 1: 22, 2: 16, 3: 10, 4: 6, 5: 4, 6: 3, 7: 2}.get(delta, 0)
    return score, (f"pub_delta_{delta}d" if score else "")


_TITLE_KW = [
    ("直播回放", 10), ("直播录像", 9), ("录播", 8), ("回放", 6), ("直播录制", 8),
    ("纯净版", 5), ("完整版", 4), ("录屏", 5), ("全场", 3), ("双视角", 2),
]
_TITLE_BAD = [
    ("剪辑", -14), ("切片", -14), ("混剪", -16), ("高能", -10), ("名场面", -10),
    ("合集", -4), ("盘点", -10), ("合集向", -12),
]


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #
class BiliClient:
    def __init__(self, cookie: str | None = None, cookie_file: str | None = None,
                 min_interval: float = 1.5, retries: int = 3, verbose: bool = False,
                 cache_ttl: int = 86400):
        self.min_interval = float(min_interval)
        self.retries = int(retries)
        self.verbose = verbose
        self.cache_ttl = int(cache_ttl)
        self._last_req = 0.0
        self._wbi_key: str | None = None
        self._wbi_ts = 0.0
        self._last_bootstrap = 0.0
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self._extra_cookie = cookie or ""
        self.cookie_file = cookie_file or COOKIE_FILE
        self._load_cookies()
        self._bootstrap()

    # -- cookie handling --------------------------------------------------- #
    def _load_cookies(self):
        if self._extra_cookie:
            return
        try:
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in (data.get("cookies") or {}).items():
                self.cj.set_cookie(http.cookiejar.Cookie(
                    0, k, v, None, False, ".bilibili.com", False, False, "/",
                    True, False, None, False, None, None, {}))
        except Exception:
            pass

    def _save_cookies(self):
        try:
            os.makedirs(os.path.dirname(self.cookie_file), exist_ok=True)
            cookies = {c.name: c.value for c in self.cj}
            if cookies:
                with open(self.cookie_file, "w", encoding="utf-8") as f:
                    json.dump({"saved_at": int(time.time()), "cookies": cookies},
                              f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _bootstrap(self):
        """Fetch homepage (+finger/spi) to obtain buvid3; no login needed."""
        if any(c.name == "buvid3" and c.value for c in self.cj):
            return
        for url in ("https://www.bilibili.com/",
                    "https://api.bilibili.com/x/frontend/finger/spi"):
            try:
                self._raw_get(url, referer="https://www.bilibili.com/")
            except Exception as e:
                self._log("bootstrap failed", url, e)
        self._last_bootstrap = time.time()
        self._save_cookies()

    def cookie_header(self) -> str:
        parts = [f"{c.name}={c.value}" for c in self.cj]
        if self._extra_cookie:
            parts.append(self._extra_cookie.strip().rstrip(";"))
        return "; ".join(p for p in parts if p)

    # -- transport --------------------------------------------------------- #
    def _log(self, *a):
        if self.verbose:
            print("[bili]", *a, file=sys.stderr)

    def _raw_get(self, url: str, referer: str, timeout: int = 25) -> bytes:
        hdrs = dict(BASE_HEADERS)
        hdrs["Referer"] = referer
        ch = self.cookie_header()
        if ch:
            hdrs["Cookie"] = ch
        req = urllib.request.Request(url, headers=hdrs)
        with self.opener.open(req, timeout=timeout) as r:
            return r.read()

    def _throttle(self):
        wait = self.min_interval - (time.time() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.time()

    def _risk_backoff(self, attempt: int):
        """Risk control (412 / -352): refresh identity once, then slow way down."""
        delay = min(30.0, 6.0 * (attempt + 1)) + random.random() * 2
        self._log(f"risk-control backoff {delay:.1f}s")
        time.sleep(delay)
        if attempt >= 1 and time.time() - self._last_bootstrap > 120:
            self.cj.clear()
            self._bootstrap()

    def _request(self, url: str, referer: str) -> dict:
        last = None
        for attempt in range(self.retries):
            self._throttle()
            try:
                raw = self._raw_get(url, referer)
                d = json.loads(raw.decode("utf-8", "replace"))
                if d.get("code") in RETRYABLE_CODES:
                    last = d
                    self._log("retryable code", d.get("code"), d.get("message"))
                    self._risk_backoff(attempt)
                    continue
                return d
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (412, 429, 500, 502, 503):
                    self._risk_backoff(attempt)
                    continue
                raise
            except Exception as e:
                last = e
                self._log("ERR", type(e).__name__, e)
                time.sleep((2 ** attempt) + random.random())
        if isinstance(last, dict):
            return last
        raise RuntimeError(f"request failed: {url[:120]} ({last})")

    # -- WBI signing ------------------------------------------------------- #
    def _wbi(self) -> str:
        if self._wbi_key and time.time() - self._wbi_ts < 600:
            return self._wbi_key
        d = self._request("https://api.bilibili.com/x/web-interface/nav",
                          "https://www.bilibili.com/")
        wi = (d.get("data") or {}).get("wbi_img") or {}
        img = wi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
        sub = wi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
        if not img or not sub:
            raise RuntimeError("cannot obtain WBI keys from /nav")
        self._wbi_key = "".join((img + sub)[i] for i in MIXIN_KEY_ENC_TAB)[:32]
        self._wbi_ts = time.time()
        return self._wbi_key

    def _sign(self, params: dict) -> dict:
        dm = {
            "dm_img_list": "[]",
            "dm_img_str": "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ",
            "dm_cover_img_str": "QU5HTEUgKE5WSURJQSwgTlZJRElBIEdlRm9yY2UgR1RYIDEwNjAgNkdCIERpcmVjdDNEMTEgdnNfNV8wIHBzXzVfMCwgRDNEMTEpR29vZ2xlIEluYy4gKE5WSURJQS",
            "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
        }
        p = dict(params)
        p.update(dm)
        p["wts"] = int(time.time())
        q = urllib.parse.urlencode(sorted(p.items()), quote_via=urllib.parse.quote)
        p["w_rid"] = hashlib.md5((q + self._wbi()).encode()).hexdigest()
        return p

    def api(self, path: str, params: dict, referer: str = "https://www.bilibili.com/",
            wbi: bool = False) -> dict:
        if wbi:
            params = self._sign(params)
        url = "https://api.bilibili.com" + path + "?" + urllib.parse.urlencode(
            params, quote_via=urllib.parse.quote)
        return self._request(url, referer)

    # -- disk cache -------------------------------------------------------- #
    def cached_json(self, key: str, loader):
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")
        try:
            if os.path.exists(path) and time.time() - os.path.getmtime(path) < self.cache_ttl:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        data = loader()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass
        return data


# --------------------------------------------------------------------------- #
# data sources
# --------------------------------------------------------------------------- #
def _norm(v: dict, source: str, mid: int | None = None) -> dict:
    created = v.get("pubdate") or v.get("created") or v.get("senddate") or v.get("ctime")
    if source == "space":
        dur = parse_duration(v.get("length"))
        author = re.sub(r"\s*\(.*?\)\s*$", "", ARCHIVE_UPS.get(mid, ("", 0))[0])
    elif source == "series":
        dur = parse_duration(v.get("duration"))
        author = re.sub(r"\s*\(.*?\)\s*$", "", ARCHIVE_UPS.get(mid, ("", 0))[0])
    else:
        dur = parse_duration(v.get("duration"))
        author = v.get("author") or v.get("uname") or ""
    return {
        "bvid": v.get("bvid"),
        "title": clean_title(v.get("title", "")),
        "author": author,
        "mid": mid if mid is not None else (v.get("mid") or v.get("uid")),
        "pubdate": created,
        "pubdate_iso": pubdate_iso(created),
        "duration": dur,
        "description": clean_title(v.get("description") or v.get("desc") or "")[:300],
        "url": f"https://www.bilibili.com/video/{v.get('bvid')}",
        "source": source,
    }


def search(client: BiliClient, keyword: str, page: int = 1) -> list[dict]:
    """Global video search (20 items/page). Returns [] on non-zero code."""
    d = client.cached_json(
        f"search_{keyword}_p{page}",
        lambda: client.api("/x/web-interface/search/type",
                           {"search_type": "video", "keyword": keyword, "page": page},
                           referer="https://search.bilibili.com/"))
    if d.get("code") != 0:
        return []
    res = (d.get("data") or {}).get("result") or []
    return [_norm(v, "search") for v in res if v.get("bvid")]


def search_users(client: BiliClient, keyword: str, page: int = 1) -> list[dict]:
    """User search. Needs from_source/search_source or it returns empty."""
    d = client.cached_json(
        f"users_{keyword}_p{page}",
        lambda: client.api("/x/web-interface/search/type",
                           {"search_type": "bili_user", "keyword": keyword, "page": page,
                            "from_source": "webtop_search", "search_source": "5"},
                           referer="https://search.bilibili.com/"))
    if d.get("code") != 0:
        return []
    return (d.get("data") or {}).get("result") or []


def user_videos(client: BiliClient, mid: int, pages: int = 8, order: str = "pubdate",
                page_size: int = 50) -> list[dict]:
    """Enumerate a UP's 投稿 videos (WBI-signed space endpoint). Excludes 直播回放."""
    def load():
        out, seen = [], set()
        for pn in range(1, pages + 1):
            try:
                d = client.api("/x/space/wbi/arc/search",
                               {"mid": mid, "ps": page_size, "pn": pn, "order": order,
                                "platform": "web", "web_location": "1550101"},
                               referer=f"https://space.bilibili.com/{mid}/video", wbi=True)
            except Exception as e:
                client._log("space", mid, "pn", pn, "failed", e)
                break
            if d.get("code") != 0:
                client._log("space", mid, "code", d.get("code"), d.get("message"))
                break
            data = d.get("data") or {}
            vlist = ((data.get("list") or {}).get("vlist") or [])
            if not vlist:
                break
            for v in vlist:
                bv = v.get("bvid")
                if bv and bv not in seen:
                    seen.add(bv)
                    out.append(_norm(v, "space", mid))
            total = (data.get("page") or {}).get("count") or 0
            if total and pn * page_size >= total:
                break
        return out

    return client.cached_json(f"space_{mid}_{order}_{pages}", load)


def series_archives(client: BiliClient, mid: int, series_id: int, pages: int = 20,
                    page_size: int = 30) -> list[dict]:
    """Enumerate a 系列/合集 — the only route to hanser's own 【直播回放】 uploads."""
    def load():
        out, seen = [], set()
        for pn in range(1, pages + 1):
            try:
                d = client.api("/x/series/archives",
                               {"mid": mid, "series_id": series_id,
                                "only_normal": "true", "sort": "desc",
                                "pn": pn, "ps": page_size},
                               referer=f"https://space.bilibili.com/{mid}")
            except Exception as e:
                client._log("series", series_id, "pn", pn, "failed", e)
                break
            if d.get("code") != 0:
                client._log("series", series_id, "code", d.get("code"), d.get("message"))
                break
            data = d.get("data") or {}
            archives = data.get("archives") or []
            if not archives:
                break
            for a in archives:
                bv = a.get("bvid")
                if bv and bv not in seen:
                    seen.add(bv)
                    out.append(_norm(a, "series", mid))
            pg = data.get("page") or {}
            total = pg.get("total") or pg.get("count") or 0
            if total and pn * page_size >= total:
                break
        return out

    return client.cached_json(f"series_{mid}_{series_id}_{pages}", load)


def video_parts(client: BiliClient, bvid: str, mid: int | None = None) -> list[dict]:
    """Expand a multi-part (分P) archive video into one candidate per part.

    Each part is one livestream; its title usually carries the date, e.g.
    '【2017.10.24】'. URL becomes https://www.bilibili.com/video/<bv>?p=N.
    The parent video's pubdate is meaningless for dating parts, so it is None.
    """
    def load():
        d = client.api("/x/player/pagelist", {"bvid": bvid})
        pages = d.get("data") or []
        out = []
        for p in pages:
            title = clean_title(p.get("part") or "")
            pg = p.get("page")
            out.append({
                "key": f"{bvid}#p{pg}",
                "bvid": bvid,
                "part": pg,
                "title": title,
                "author": re.sub(r"\s*\(.*?\)\s*$", "",
                                 ARCHIVE_UPS.get(mid, ("", 0))[0]) if mid else "",
                "mid": mid,
                "pubdate": None,
                "pubdate_iso": "",
                "duration": parse_duration(p.get("duration")),
                "description": "",
                "url": f"https://www.bilibili.com/video/{bvid}?p={pg}",
                "source": "multipart",
            })
        return out

    return client.cached_json(f"parts_{bvid}", load)


def video_info(client: BiliClient, bvid: str) -> dict:
    d = client.cached_json(f"view_{bvid}",
                           lambda: client.api("/x/web-interface/view", {"bvid": bvid}))
    if d.get("code") != 0:
        return {}
    v = d.get("data") or {}
    return {
        "bvid": v.get("bvid"),
        "title": clean_title(v.get("title", "")),
        "author": (v.get("owner") or {}).get("name", ""),
        "mid": (v.get("owner") or {}).get("mid"),
        "pubdate": v.get("pubdate"),
        "pubdate_iso": pubdate_iso(v.get("pubdate")),
        "duration": parse_duration(v.get("duration")),
        "description": v.get("desc", ""),
        "url": f"https://www.bilibili.com/video/{v.get('bvid')}",
        "source": "view",
    }


# --------------------------------------------------------------------------- #
# local catalog (index)
# --------------------------------------------------------------------------- #
def build_index(client: BiliClient, verbose: bool = False) -> dict:
    """Walk all known archive sources once; persist to tools/.cache/bili_index.json."""
    items: dict[str, dict] = {}
    for mid, sid, label in ARCHIVE_SERIES:
        try:
            for v in series_archives(client, mid, sid, pages=20):
                items.setdefault(v["bvid"], v)
        except Exception as e:
            client._log("series failed", sid, e)
    for mid, pages in INDEX_SPACE_PAGES.items():
        try:
            for v in user_videos(client, mid, pages=pages):
                items.setdefault(v["bvid"], v)
        except Exception as e:
            client._log("space failed", mid, e)
    for mid, bvid, label in ARCHIVE_MULTIPART:
        try:
            for v in video_parts(client, bvid, mid):
                items.setdefault(v["key"], v)
        except Exception as e:
            client._log("multipart failed", bvid, e)
    index = {
        "built_at": int(time.time()),
        "built_at_iso": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "sources": {
            "series": [{"mid": m, "series_id": s, "label": l} for m, s, l in ARCHIVE_SERIES],
            "space_pages": INDEX_SPACE_PAGES,
        },
        "items": list(items.values()),
    }
    # older cache entries may predate author naming; fill from the whitelist
    for it in index["items"]:
        if not it.get("author") and it.get("mid") in ARCHIVE_UPS:
            it["author"] = re.sub(r"\s*\(.*?\)\s*$", "", ARCHIVE_UPS[it["mid"]][0])
    os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    if verbose:
        print(f"[index] {len(items)} items -> {INDEX_FILE}", file=sys.stderr)
    return index


def load_index(client: BiliClient, rebuild: bool = False, ttl: int = 7 * 86400) -> dict:
    if not rebuild:
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                idx = json.load(f)
            if time.time() - idx.get("built_at", 0) < ttl and idx.get("items"):
                return idx
        except Exception:
            pass
    return build_index(client, verbose=client.verbose)


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def _has_hanser_evidence(cand: dict) -> bool:
    if cand.get("mid") in ARCHIVE_UPS:
        return True
    low = f"{cand.get('title','')} {cand.get('description','')}".lower()
    return any(h in low for h in HANSER_HINTS)


def score_candidate(cand: dict, date_str: str, title_hint: str = "",
                    extra_keywords: list[str] | None = None) -> tuple[int, list[str]]:
    score, why = 0, []
    text = f"{cand.get('title', '')} {cand.get('description', '')}"

    ds, dw = _date_match_score(date_str, text)
    score += ds
    why += dw

    ps, pw = _pubdate_score(date_str, cand.get("pubdate"))
    score += ps
    if pw:
        why.append(pw)

    mid = cand.get("mid")
    if mid in ARCHIVE_UPS:
        label, w = ARCHIVE_UPS[mid]
        score += w
        why.append(f"up:{label}")

    if not _has_hanser_evidence(cand):
        score -= 60                      # generic date-only channel -> noise floor
        why.append("bad:no_hanser_evidence")

    title = cand.get("title", "")
    for kw, kw_score in _TITLE_KW:
        if kw in title:
            score += kw_score
            why.append(f"kw:{kw}")
            break
    for kw, kw_score in _TITLE_BAD:
        if kw in title:
            score += kw_score
            why.append(f"bad:{kw}")
            break

    if title_hint:
        hint = re.sub(r"\s+", "", title_hint).lower()
        tt = re.sub(r"\s+", "", title).lower()
        if hint and hint in tt:
            score += 15
            why.append("title_hint")
        else:
            toks = [t for t in re.split(r"[\s/【】\[\]()（）,，!！?？~～·\-]+", title_hint) if len(t) >= 2]
            hit = sum(1 for t in toks if t.lower() in tt)
            if hit:
                score += min(10, 5 * hit)
                why.append("title_hint_partial")

    for kw in (extra_keywords or []):
        if kw and kw in text:
            score += 5
            why.append(f"extra:{kw}")

    dur = cand.get("duration") or 0
    if 1200 <= dur <= 32400:
        score += 6
        why.append("dur_plausible")
    elif 0 < dur < 180:
        score -= 20
        why.append("dur_too_short")

    if cand.get("source") in ("space", "series", "multipart"):
        score += 3
        why.append(f"catalog:{cand['source']}")
    return score, why


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #
def _search_queries(date_str: str, title_hint: str = "") -> list[str]:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    y, m, day = d.year, d.month, d.day
    forms = [f"{y}-{m:02d}-{day:02d}", f"{y}年{m}月{day}日",
             f"{y}.{m}.{day}", f"{str(y)[2:]}-{m}-{day}", f"{str(y)[2:]}-{m:02d}-{day:02d}"]
    qs: list[str] = []
    if title_hint:
        qs += [f"hanser {title_hint} {forms[1]}", f"hanser {title_hint} {forms[0]} 录播"]
    qs += [
        f"hanser 录播 {forms[0]}",
        f"hanser 直播录制 {forms[0]}",
        f"hanser 直播录像 {forms[0]}",
        f"hanser 录播 {forms[1]}",
        f"hanser 直播回放 {forms[3]}",
        f"hanser {forms[4]} 直播录制",
    ]
    seen, out = set(), []
    for q in qs:
        q = re.sub(r"\s+", " ", q).strip()
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def match_stream(client: BiliClient, date_str: str, title_hint: str = "",
                 extra_keywords: list[str] | None = None,
                 online: str = "auto", search_pages: int = 1,
                 use_index: bool = True, rebuild_index: bool = False,
                 top: int = 10, verify: bool = False) -> list[dict]:
    """Rank recording candidates for one livestream date.

    online: "auto" (search only when the catalog has no strong hit),
            "always" (always add search results), "never" (catalog only).
    """
    pool: dict[str, dict] = {}
    if use_index:
        for c in load_index(client, rebuild=rebuild_index).get("items", []):
            pool.setdefault(c.get("key") or c["bvid"], c)

    def rescore() -> list[dict]:
        ranked = []
        for cand in pool.values():
            # hard relevance gate: a recording of *this* hanser stream must
            # either come from a known archive UP or mention hanser somewhere.
            if not _has_hanser_evidence(cand):
                continue
            s, why = score_candidate(cand, date_str, title_hint, extra_keywords)
            if s <= 0:
                continue
            # Require *some* date signal: a date in the title, or an upload
            # within a week of the stream. Otherwise the item cannot be this
            # livestream and would only be whitelist noise.
            date_hit = any(r.startswith(("title-date", "title-monthday", "pub_delta"))
                           for r in why)
            if not date_hit:
                continue
            item = dict(cand)
            item["score"] = s
            item["reasons"] = why
            ranked.append(item)
        ranked.sort(key=lambda x: (x["score"], x.get("pubdate") or 0), reverse=True)
        return ranked

    ranked = rescore()
    best = ranked[0]["score"] if ranked else -999
    need_online = online == "always" or (online == "auto" and best < 70)
    if need_online:
        for q in _search_queries(date_str, title_hint):
            for page in range(1, search_pages + 1):
                try:
                    for v in search(client, q, page=page):
                        pool.setdefault(v["bvid"], v)
                except Exception as e:
                    client._log("search failed", q, page, e)
        ranked = rescore()

    ranked = ranked[: max(top, 1)]
    if verify:
        for c in ranked[:3]:
            info = video_info(client, c["bvid"])
            if info:
                c["verified"] = info
                c["title"] = info.get("title") or c["title"]
                c["author"] = info.get("author") or c["author"]
                c["mid"] = info.get("mid") or c["mid"]
    return ranked


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Find Bilibili recording (录播) candidates for a hanser livestream date")
    ap.add_argument("--date", help="livestream date, YYYY-MM-DD (omit with --build-index)")
    ap.add_argument("--title", default="", help="title hint, e.g. 冒汗电台")
    ap.add_argument("--extra", action="append", default=[],
                    help="extra keyword that should appear (repeatable)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--online", choices=["auto", "always", "never"], default="auto",
                    help="'never' = offline catalog only (fast, batch mode)")
    ap.add_argument("--search-pages", type=int, default=1)
    ap.add_argument("--no-index", action="store_true", help="ignore local catalog")
    ap.add_argument("--rebuild-index", action="store_true")
    ap.add_argument("--build-index", action="store_true",
                    help="refresh the local catalog and exit")
    ap.add_argument("--verify", action="store_true",
                    help="re-fetch top-3 via /x/web-interface/view for clean metadata")
    ap.add_argument("--json", dest="json_out", default="", help="write full JSON result to file")
    ap.add_argument("--cookie-file", default="",
                    help="JSON {cookies:{name:value}} or a raw cookie string")
    ap.add_argument("--min-interval", type=float, default=1.5)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.time()
    client = BiliClient(min_interval=args.min_interval, verbose=args.verbose)
    if args.cookie_file:
        if os.path.exists(args.cookie_file):
            try:
                with open(args.cookie_file, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                data = json.loads(raw)
                client._extra_cookie = "; ".join(
                    f"{k}={v}" for k, v in (data.get("cookies") or data).items())
            except Exception:
                client._extra_cookie = raw
        else:
            client._extra_cookie = args.cookie_file

    if args.build_index:
        idx = build_index(client, verbose=True)
        print(json.dumps({"index": INDEX_FILE, "items": len(idx["items"]),
                          "built_at": idx["built_at_iso"]}, ensure_ascii=False))
        return 0

    if not args.date:
        ap.error("--date is required (or use --build-index)")
    datetime.strptime(args.date, "%Y-%m-%d")

    ranked = match_stream(client, args.date, args.title, args.extra,
                          online=args.online, search_pages=args.search_pages,
                          use_index=not args.no_index, rebuild_index=args.rebuild_index,
                          top=args.top, verify=args.verify)

    for c in ranked:
        if len(c.get("description", "")) > 200:
            c["description"] = c["description"][:200]
    result = {
        "date": args.date,
        "title_hint": args.title,
        "extra_keywords": args.extra,
        "online_mode": args.online,
        "elapsed_sec": round(time.time() - t0, 1),
        "candidates": ranked,
    }
    out = json.dumps(result, ensure_ascii=False, indent=1)
    print(out)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[wrote] {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
