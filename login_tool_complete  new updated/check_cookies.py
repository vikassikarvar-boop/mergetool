#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_cookies.py — Instagram session valid hai ya nahi check karta hai
SIRF ANDROID/MOBILE API SURFACE — exact real-app headers (templates.json se),
koi web endpoint use nahi hoga.

Key fixes vs purana version:
  - ig-intended-user-id = actual ds_user_id (0 nahi!)
  - ig-u-ds-user-id header add kiya
  - ig-u-rur header add kiya (token se ya default ODN)
  - x-ig-www-claim properly set (agar available ho)
  - session cookies properly set (requests session + header dono)
  - Unicode/emoji print issue fix (ascii fallback)

Checks (i.instagram.com — pure mobile endpoint):
  [1] GET /api/v1/users/<uid>/info/
  [2] GET /api/v1/news/inbox/
  [3] GET /api/v1/accounts/get_presence_disabled/

Usage:
  python check_cookies.py            (isi folder ka cookies.json use hoga)
  python check_cookies.py path/to/cookies.json
"""
import force_ipv4  # IPv6 pe app session 403 deta hai — IPv4 force karo
import json
import os
import re
import sys
import time
import uuid
import base64

import requests

HERE = os.path.dirname(os.path.abspath(__file__))

CHECKPOINT_MARKERS = [
    "checkpoint_required", "checkpoint_url", "challenge_context",
    "login_required", "two_factor_required", "sentry_block",
    "Please wait a few minutes", "rate_limit", "feedback_required",
    "consent_required", "challenge_required",
]

SUSPEND_MARKERS = [
    "accounts/suspended", "suspended/",
]


def decode_token(auth: str) -> dict:
    """Bearer IGT:2:<b64> se ds_user_id, sessionid, rur nikalo."""
    result = {}
    try:
        b64 = auth.split("IGT:2:", 1)[1]
        b64 += "=" * (-len(b64) % 4)
        j = json.loads(base64.b64decode(b64))
        result["ds_user_id"] = str(j.get("ds_user_id", ""))
        result["sessionid"] = j.get("sessionid", "")
        result["rur"] = j.get("rur", "")
    except Exception as e:
        print("  [warn] token decode:", e)
    return result


def build_app_headers(auth: str, uid: str, rur: str = "ODN", www_claim: str = "0", tz_offset: str = "19800", locale: str = "en_US", lang: str = "en-US") -> dict:
    """
    Real app jaisa poora header set banao — templates.json se base headers lo,
    phir authenticated fields override karo.

    Critical headers jo login ke baad ZAROOR chahiye:
      - authorization         : Bearer IGT token
      - ig-intended-user-id   : actual user id (0 nahi!)
      - ig-u-ds-user-id       : same user id
      - ig-u-rur              : rur value (token se ya default)
      - x-ig-www-claim        : post-login value (0 pre-login ke liye)
      - x-ig-timezone-offset  : geo timezone offset (e.g. 28800 for PH)
    """
    # templates.json se mobileconfig ke headers base ke roop mein lo
    try:
        sys.path.insert(0, HERE)
        import ig_login as L
        base = dict(L.TEMPLATES["mobileconfig"]["headers"])
    except Exception:
        # Fallback — agar import fail ho
        base = {
            "user-agent": (
                "Instagram 451.0.0.53.80 Android (28/9; 240dpi; 1600x900; "
                "Xiaomi; 2203121C; marlin; qcom; en_US; 385713073)"
            ),
            "x-ig-app-id": "567067343352427",
            "accept-language": lang,
            "x-ig-capabilities": "3brTv10=",
            "x-ig-connection-type": "WIFI",
            "x-ig-timezone-offset": tz_offset,
            "x-bloks-version-id": "799db3e387d7a21a19c72918b8698b6cd28a1516ade363792c100ed45a0f9f0b",
        }

    # Request-level headers hata do jo GET me nahi chahiye
    for drop in ("content-type", "content-length"):
        base.pop(drop, None)

    # Dynamic fields update karo
    base["x-pigeon-rawclienttime"] = f"{time.time():.3f}"
    base["x-fb-conn-uuid-client"] = uuid.uuid4().hex

    # ---- Authenticated headers (yahi 403 fix karte hain) ----
    base["authorization"] = auth
    base["ig-intended-user-id"] = uid          # MUST be real uid, not "0"
    base["ig-u-ds-user-id"] = uid
    base["ig-u-rur"] = rur if rur else "ODN"
    base["x-ig-www-claim"] = www_claim if www_claim and www_claim != "0" else "0"
    base["x-ig-timezone-offset"] = str(tz_offset)
    base["accept-language"] = lang
    base["x-ig-app-locale"] = locale
    base["x-ig-device-locale"] = locale
    base["x-ig-mapped-locale"] = locale

    return base


def format_proxy_url(p: str) -> str:
    if not p:
        return ""
    p = p.strip()
    if p.startswith("http://") or p.startswith("https://") or p.startswith("socks5://"):
        return p
    parts = p.split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        return f"http://{user}:{pwd}@{host}:{port}"
    elif len(parts) == 2:
        host, port = parts
        return f"http://{host}:{port}"
    return f"http://{p}"


def set_session_cookies(s: requests.Session, cookies: dict, uid: str):

    """
    Cookies ko requests session mein sahi tarike se set karo.
    Dono hosts ke liye set karo: i.instagram.com aur b.i.instagram.com
    """
    cookie_names = [
        "sessionid", "ds_user_id", "mid", "csrftoken",
        "rur", "shbid", "shbts", "ig_did", "datr",
    ]
    for name, value in cookies.items():
        if not value:
            continue
        # Dono subdomains ke liye set karo
        for domain in (".instagram.com",):
            s.cookies.set(name, value, domain=domain)


def looks_like_checkpoint(status: int, text: str) -> str:
    """403/429/401 ya text mein marker mile to reason return karo."""
    for marker in CHECKPOINT_MARKERS:
        if marker in text:
            return marker
    if status in (400, 401, 403, 429):
        return f"HTTP {status}"
    return None


def safe_print(text: str):
    """Windows cmd mein emoji crash karta hai — ASCII fallback use karo."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def main():
    # cookies.json load karo
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "cookies.json")
    if not os.path.exists(path):
        safe_print(f"ERROR: {path} nahi mila!")
        sys.exit(1)

    data = json.load(open(path, encoding="utf-8"))
    cookies = data.get("cookies", {})
    auth = (data.get("authorization") 
            or data.get("mobile_api_session", {}).get("session_data", {}).get("Authorization", ""))
    username = data.get("username", "unknown")

    # Token se uid/rur nikalo (cookie value se bhi fallback)
    token_info = decode_token(auth) if auth else {}
    uid = (token_info.get("ds_user_id")
           or cookies.get("ds_user_id", ""))
    rur = token_info.get("rur", "") or cookies.get("rur", "ODN")

    # Token se sessionid bhi merge karo agar cookies mein nahi hai
    if not cookies.get("sessionid") and token_info.get("sessionid"):
        cookies["sessionid"] = token_info["sessionid"]

    geo = data.get("geo") or data.get("fingerprint", {})
    tz_offset = str(geo.get("timezone_offset", "19800"))
    locale = geo.get("locale") or data.get("mobile_api_session", {}).get("device_info", {}).get("locale", "en_US")
    proxy = geo.get("proxy") or geo.get("proxy_url") or None
    country = data.get("country") or geo.get("proxy_country", "IN")

    safe_print(f"\nAccount  : {username}")
    safe_print(f"User ID  : {uid}")
    safe_print(f"RUR      : {rur}")
    safe_print(f"Country  : {country} (tz offset: {tz_offset}s)")
    if proxy:
        safe_print(f"Proxy    : {proxy}")
    safe_print(f"SessionID: {cookies.get('sessionid', '')[:20]}...")
    safe_print(f"Auth     : {auth[:40]}..." if auth else "Auth     : MISSING")


    if not cookies.get("sessionid") or not auth:
        safe_print("\nERROR: cookies.json mein sessionid ya authorization nahi hai!")
        safe_print("Pehle ig_login.py chalao aur cookies.json banao.")
        sys.exit(1)

    if not uid:
        safe_print("ERROR: ds_user_id nahi mila — token ya cookies me uid chahiye!")
        sys.exit(1)

    # Session banao aur cookies set karo
    s = requests.Session()
    if proxy:
        p_url = format_proxy_url(proxy)
        s.proxies = {"http": p_url, "https": p_url}
    set_session_cookies(s, cookies, uid)


    # Headers banao
    hdr = build_app_headers(auth, uid, rur, tz_offset=tz_offset, locale=locale)

    # ---- Checks define karo ----
    # SIRF i.instagram.com — real authenticated mobile endpoint
    # NOTE: b.i.instagram.com (burst CDN) strict auth validate nahi karta —
    #       isliye wahan se 200 aana reliable nahi, use skip karo.
    BASE_I = "https://i.instagram.com"

    # logout_reason codes (Instagram internal):
    #   2  = Incorrect device/platform fingerprint
    #   6  = Session inactive / timed out
    #   8  = Session replaced — naya login hua toh purana auto-invalidate
    #   11 = Account suspended
    LOGOUT_REASONS = {
        "2":  "Device/IP fingerprint mismatch",
        "6":  "Session inactive / expired",
        "7":  "Account suspended / challenge locked",
        "8":  "Session replaced (dobara login se pehla session invalidate hua)",
        "11": "Account suspended/blocked",
    }

    checks = [
        (
            "User Info",
            f"{BASE_I}/api/v1/users/{uid}/info/",
            lambda j: "@" + j.get("user", {}).get("username", "?"),
        ),
        (
            "News Inbox",
            (f"{BASE_I}/api/v1/news/inbox/"
             "?could_truncate_feed=true&should_skip_su=false"
             f"&mark_as_seen=false&timezone_offset={tz_offset}"),
            lambda j: "status:" + str(j.get("status", "?")),
        ),
        (
            "Presence Config",
            f"{BASE_I}/api/v1/accounts/get_presence_disabled/?signed_body=SIGNATURE.%7B%7D",
            lambda j: "presence_disabled:" + str(j.get("presence_disabled", "?")),
        ),
    ]



    safe_print("\n" + "=" * 66)
    all_ok = True

    for name, url, parse in checks:
        try:
            r = s.get(url, headers=hdr, timeout=30)
            chk = looks_like_checkpoint(r.status_code, r.text[:6000])
            ok = r.status_code == 200 and not chk

            detail = ""
            if ok:
                try:
                    detail = " -> " + parse(r.json())
                except Exception:
                    detail = " -> (parse error)"
            warn = f" !! {chk}" if chk else ""

            status_label = "OK  " if ok else "FAIL"
            safe_print(
                f"[{status_label}] {name:<20s} HTTP {r.status_code}{detail}{warn}"
            )

            if not ok:
                # Debug ke liye response ka kuch part dikhao + logout_reason explain karo
                snippet = r.text[:300].replace("\n", " ")
                safe_print(f"       Response: {snippet}")
                try:
                    reason_code = str(r.json().get("logout_reason", ""))
                    if reason_code and reason_code in LOGOUT_REASONS:
                        safe_print(f"       Reason: {LOGOUT_REASONS[reason_code]}")
                except Exception:
                    pass

            all_ok = all_ok and ok

        except requests.exceptions.RequestException as e:
            safe_print(f"[FAIL] {name:<20s} Network error: {e}")
            all_ok = False

    safe_print("=" * 66)

    if all_ok:
        safe_print("RESULT: SESSION VALID [OK] — Android mobile surface par sab theek.")
        safe_print("        Koi checkpoint/challenge nahi mila.")
    else:
        safe_print("RESULT: ISSUE HAI [FAIL] — upar response dekhiye.")
        safe_print("        Possible reasons: cookie expire, IP ban, checkpoint.")


if __name__ == "__main__":
    main()
