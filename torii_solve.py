#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Solve Server Torii (ALTCHA v3) proof-of-work challenge for song.2550505.com.

Flow (from altcha v3.0.4 lib):
  1. GET page -> 503 CAPTCHA page, sets cookie __torii_session_id
  2. GET /torii/captcha/challenge -> {parameters:{algorithm,nonce,salt,cost,keyLength,keyPrefix,...},signature}
  3. solve: for counter 0..: PBKDF2(password = nonce_bytes + uint32_be(counter),
                                    salt = bytes.fromhex(salt), iterations=cost,
                                    hash per algorithm, dklen=keyLength)
            until hex(dk) starts with keyPrefix
  4. payload = base64(JSON({challenge:{parameters,signature}, solution:{counter,derivedKey,time}}))
  5. POST /torii/captcha  body: altcha=<urlencoded payload>  -> "good"
Used by crawler to obtain a verified session cookie.
Python 3.6 compatible.
"""
import base64, hashlib, json, time, urllib.parse, urllib.request, http.cookiejar

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
BASE = "https://song.2550505.com"

DIGESTS = {"PBKDF2/SHA-512": "sha512", "PBKDF2/SHA-384": "sha384", "PBKDF2/SHA-256": "sha256"}

class ToriiSession:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [
            ("User-Agent", UA),
            ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
            ("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
        ]

    def _open(self, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            r = self.opener.open(req, timeout=40)
            return r.getcode(), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def solve(self, probe_path="/livestreams?date=2026-10-26", max_counter=200000, verbose=True):
        code, body = self._open(BASE + probe_path)
        if verbose:
            print("[torii] probe status", code, "len", len(body))
        if code == 200 and "CAPTCHA" not in body[:2000]:
            return True  # already verified / not challenged
        if "Server Torii" not in body:
            print("[torii] not a challenge page; status", code)
            return code == 200
        # 2) get challenge
        ccode, cbody = self._open(BASE + "/torii/captcha/challenge",
                                  headers={"Accept": "application/json",
                                           "Referer": BASE + probe_path})
        if verbose:
            print("[torii] challenge status", ccode)
        ch = json.loads(cbody)
        p = ch["parameters"]
        alg = DIGESTS.get(p.get("algorithm"), "sha512")
        cost = int(p.get("cost") or 10000)
        klen = int(p.get("keyLength") or 32)
        prefix = p.get("keyPrefix") or ""
        nonce = bytes.fromhex(p["nonce"])
        salt = bytes.fromhex(p["salt"]) if p.get("salt") else b""
        t0 = time.time()
        counter = 0
        while counter <= max_counter:
            pw = nonce + counter.to_bytes(4, "big")
            dk = hashlib.pbkdf2_hmac(alg, pw, salt, cost, dklen=klen)
            hexdk = dk.hex()
            if hexdk.startswith(prefix):
                break
            counter += 1
        else:
            raise RuntimeError("no solution within %d" % max_counter)
        took_ms = int((time.time() - t0) * 1000)
        if verbose:
            print("[torii] solved counter=%d took=%dms" % (counter, took_ms))
        payload_obj = {
            "challenge": {"parameters": p, "signature": ch.get("signature")},
            "solution": {"counter": counter, "derivedKey": hexdk, "time": took_ms},
        }
        payload = base64.b64encode(json.dumps(payload_obj, separators=(",", ":")).encode()).decode()
        data = urllib.parse.urlencode({"altcha": payload}).encode()
        pcode, pbody = self._open(BASE + "/torii/captcha", data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Origin": BASE,
            "Referer": BASE + probe_path,
        })
        if verbose:
            print("[torii] verify status", pcode, "body", pbody[:120])
        if pbody.strip() == "good":
            return True
        return False

    def get(self, path):
        return self._open(BASE + path)


if __name__ == "__main__":
    s = ToriiSession()
    ok = s.solve()
    print("verified:", ok)
    code, body = s.get("/livestreams?date=2020-01-03")
    print("page status", code, "len", len(body), "next_data", "__NEXT_DATA__" in body)
    if code == 200:
        import re
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', body, re.S)
        if m:
            pp = json.loads(m.group(1))["props"]["pageProps"]
            print("date", pp.get("date"), "songs keys", list((pp.get("songs") or {}).keys())[:3],
                  "record link", (pp.get("record") or {}).get("link_pure"))
