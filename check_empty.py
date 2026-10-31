import json, sys
sys.path.insert(0, ".")
from torii_solve import ToriiSession

s = ToriiSession()
print("solve", s.solve(verbose=False))

def api(path):
    code, body = s._open("https://2550505.com/song" + path,
                         headers={"Accept": "application/json",
                                  "Referer": "https://song.2550505.com/"})
    try:
        return code, json.loads(body)
    except Exception:
        return code, body[:200]

for d in ["2024-05-20", "2024-06-10", "2024-03-19", "2022-04-23", "2018-03-06"]:
    c1, songs = api("/lives/getbydate?date=" + d)
    c2, rec = api("/livecontents/getbydate?date=" + d)
    c3, info = api("/lives/getinfo?date=" + d)
    print(d, "songs", c1, len(songs.get("list") or []) if isinstance(songs, dict) else songs)
    print("   rec", c2, json.dumps(rec, ensure_ascii=False)[:200] if isinstance(rec, dict) else rec)
    print("   info", c3, json.dumps(info, ensure_ascii=False)[:150] if isinstance(info, dict) else info)
