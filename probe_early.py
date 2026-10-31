import json, re, sys
sys.path.insert(0, ".")
from torii_solve import ToriiSession

s = ToriiSession()
print("solve", s.solve(verbose=False))
out = {}
for d in ["2017-07-01", "2017-06-01", "2016-12-01", "2017-08-15", "2017-09-01"]:
    code, body = s.get("/livestreams?date=" + d)
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', body, re.S)
    pp = json.loads(m.group(1))["props"]["pageProps"] if m else {}
    out[d] = {"code": code, "days": pp.get("days"), "info": pp.get("info")}
open("inspect4.json", "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
print("done")
