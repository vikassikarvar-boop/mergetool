"""Hub health worker: ek cookie file ka session check. usage: health_worker.py <matrix_dir> <cookies.json>
Output ki last line: HUB_HEALTH {json}"""
import json, os, sys

matrix_dir, cookies = sys.argv[1:3]
sys.path.insert(0, matrix_dir)
os.chdir(matrix_dir)


def out(status, detail="", http=None, extra=None):
    res = {"status": status, "detail": detail, "http": http}
    if extra:
        res.update(extra)
    print("HUB_HEALTH " + json.dumps(res, ensure_ascii=False))
    sys.exit(0)


try:
    d = json.load(open(cookies, encoding="utf-8"))
except Exception as e:
    out("BAD_FILE", f"cookie file padh nahi payi: {e}")
ck = d.get("cookies") or {}
if not ck.get("sessionid") and not (d.get("mobile_api_session") or {}).get("session_data", {}).get("Authorization"):
    out("NO_SESSION", "sessionid/Authorization file me nahi hai - dobara login karo")

try:
    import ig_actions as A
    sess = A.Session(cookies)
    r = sess.get(f"/api/v1/users/{sess.uid}/info/", "IgApi: users/info/")
    t = (r.text or "")
    low = t.lower()
    if r.status_code == 200 and sess.username in t:
        extra = {}
        try:
            info = r.json().get("user", {})
            extra["posts"] = int(info.get("media_count", 0))
            anon = bool(info.get("has_anonymous_profile_picture", False))
            extra["has_dp"] = not anon
            extra["is_private"] = bool(info.get("is_private", False))
            extra["followers"] = int(info.get("follower_count", 0))
            extra["following"] = int(info.get("following_count", 0))
        except Exception as ex:
            extra["parse_err"] = str(ex)
        out("ALIVE", "session theek hai", 200, extra)
    if "accounts/suspended" in low or "suspended" in low or ("disabled" in low and "account" in low):
        out("SUSPENDED", "account suspended/disabled", r.status_code)
    if "challenge_required" in low or "checkpoint" in low:
        out("CHALLENGE", "checkpoint/challenge - app me verify karna padega", r.status_code)
    if "login_required" in low or (r.status_code in (401, 403) and "login" in low):
        out("EXPIRED", "cookie/session expire - dobara login karo", r.status_code)
    if r.status_code == 429:
        out("THROTTLED", "rate limit (429) - baad me check karo", 429)
    out("ERROR", t[:160].replace("\n", " "), r.status_code)
except SystemExit:
    raise
except Exception as e:
    estr = str(e)
    if "402" in estr or "tunnel failed" in estr or "Proxy" in estr or "407" in estr:
        out("PROXY_ERROR", f"proxy connection/payment fail: {estr[:120]}")
    else:
        out("ERROR", f"exception: {estr[:140]}")

