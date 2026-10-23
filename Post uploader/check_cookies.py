#!/usr/bin/env python3
"""
check_cookies.py — session valid hai ya nahi, checkpoint to nahi?
SIRF ANDROID API SURFACE — bilkul real app jaise: templates.json wale poore
device headers + Bearer token + app cookies (web surface par mix nahi karta).

Checks (i.instagram.com):
  [1] /api/v1/users/<uid>/info/
  [2] /api/v1/news/inbox/...
  [3] /api/v1/accounts/get_presence_disabled/?signed_body=SIGNATURE.%7B%7D

Usage:  python check_cookies.py            (isi folder ka cookies.json)
        python check_cookies.py path/to/cookies.json
"""
import json
import os
import sys
import time
import uuid

import requests

ANDROID_UA = ("Instagram 400.0.0.49.68 Android (28/9; 240dpi; 1600x900; "
              "Xiaomi; 2203121C; marlin; qcom; en_US; 799297105)")
IG_APP_ID = "567067343352427"
HERE = os.path.dirname(os.path.abspath(__file__))

CHECKPOINT_MARKERS = [
    "checkpoint_required", "checkpoint_url", "challenge_context",
    "login_required", "two_factor_required", "sentry_block",
    "Please wait a few minutes", "rate_limit", "feedback_required",
]


def app_headers(auth: str) -> dict:
    """Real app jaisa full header set — templates se, dynamic fields fresh."""
    try:
        sys.path.insert(0, HERE)
        import ig_login as L
        hdr = dict(L.TEMPLATES["mobileconfig"]["headers"])
    except Exception:
        hdr = {"user-agent": ANDROID_UA, "x-ig-app-id": IG_APP_ID,
               "accept-language": "en-US"}
    hdr = {k: v for k, v in hdr.items()
           if k.lower() not in ("content-type", "content-length",
                                "accept-encoding", "authorization",
                                "ig-u-rur", "x-ig-www-claim")}
    hdr["x-pigeon-rawclienttime"] = f"{time.time():.3f}"
    hdr["x-fb-conn-uuid-client"] = uuid.uuid4().hex
    hdr["authorization"] = auth
    return hdr


def looks_like_checkpoint(status: int, text: str) -> str:
    if status in (400, 401, 403, 429):
        for m in CHECKPOINT_MARKERS:
            if m in text:
                return m
        return f"HTTP {status}"
    for m in ("checkpoint_required", "checkpoint_url", "challenge_context"):
        if m in text:
            return m
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(HERE, "cookies.json")
    data = json.load(open(path, encoding="utf-8"))
    cookies = data.get("cookies", {})
    auth = data.get("authorization")
    uid = cookies.get("ds_user_id", "")
    if not (cookies.get("sessionid") and auth):
        raise SystemExit("cookies.json me sessionid/authorization nahi hai!")

    s = requests.Session()
    s.cookies.update(cookies)
    hdr = app_headers(auth)

    checks = [
        ("Android user info",
         f"https://i.instagram.com/api/v1/users/{uid}/info/",
         lambda j: j["user"]["username"]),
        ("Activity inbox",
         "https://i.instagram.com/api/v1/news/inbox/?could_truncate_feed=true"
         "&should_skip_su=false&mark_as_seen=false&timezone_offset=19800",
         lambda j: "status:" + str(j.get("status", "?"))),
        ("Presence config",
         "https://i.instagram.com/api/v1/accounts/get_presence_disabled/"
         "?signed_body=SIGNATURE.%7B%7D",
         lambda j: "status:" + str(j.get("status", "?"))),
    ]

    print("=" * 66)
    all_ok = True
    for name, url, parse in checks:
        try:
            r = s.get(url, headers=hdr, timeout=30)
            chk = looks_like_checkpoint(r.status_code, r.text[:5000])
            ok = r.status_code == 200 and not chk
            who = ""
            if ok:
                try:
                    who = " -> " + parse(r.json())
                except Exception:
                    pass
            warn = f" !! {chk}" if chk else ""
            print(f"[{'OK ' if ok else 'FAIL'}] {name:20s} HTTP {r.status_code}"
                  f"{who}{warn}")
            all_ok = all_ok and ok
        except Exception as e:
            print(f"[FAIL] {name:20s} error: {e}")
            all_ok = False
    print("=" * 66)
    if all_ok:
        print("RESULT: SESSION VALID ✅ — Android surface par sab theek, "
              "koi checkpoint/challenge nahi.")
    else:
        print("RESULT: ISSUE HAI ❌ — upar dekhiye "
              "(checkpoint / expired / rate-limit).")

if __name__ == "__main__":
    main()
