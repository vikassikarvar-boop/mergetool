#!/usr/bin/env python3
"""
capture_mid.py — Web endpoint se mid capture karo + cookie file update karo.

SAFE approach (same as ig_login_tool's enrich_web_cookies):
  - Account ka existing sessionid + proxy use karta hai
  - Sirf www.instagram.com GET karta hai (no login, no suspicious action)
  - Response Set-Cookie se fresh mid capture karta hai
  - Cookie file me mid update karta hai

Usage:
  python capture_mid.py
  python capture_mid.py --cookie-file cookies/cookies_badger.4951992.json
"""
import argparse
import json
import os
import re
import sys
import time

import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))

# Default target: active commenting account (badger)
DEFAULT_COOKIE_FILE = os.path.join(
    HERE, "cookies", "cookies_badger.4951992.json"
)


def load_cookie_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cookie_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[saved] {path}")


def ensure_proxy_168h(data, path):
    """Proxy lifetime 59m → 168h update karo agar zaroorat ho."""
    fp = data.get("fingerprint", {}) or {}
    proxy = fp.get("proxy_url", "") or ""
    if not proxy:
        return data, False

    m = re.search(r"(_lifetime-)(\d+[a-zA-Z]+)", proxy)
    if m:
        current_lt = m.group(2)
        if current_lt != "168h":
            new_proxy = proxy[:m.start(2)] + "168h" + proxy[m.end(2):]
            data["fingerprint"]["proxy_url"] = new_proxy
            print(f"[proxy-fix] lifetime {current_lt!r} → '168h'")
            print(f"            new proxy: {new_proxy}")
            return data, True
        else:
            print(f"[proxy] lifetime already 168h — no change needed")
            return data, False
    else:
        print(f"[proxy] _lifetime param nahi mila in proxy URL — check karo manually")
        return data, False


def capture_mid_from_web(data):
    """
    www.instagram.com se mid capture karo.
    Existing proxy + sessionid use karta hai — no login, no suspicious action.
    Same as ig_login_tool's enrich_web_cookies, but WITH proxy binding.
    """
    fp = data.get("fingerprint", {}) or {}
    proxy_url = fp.get("proxy_url", "") or ""
    cookies_dict = data.get("cookies", {}) or {}
    username = data.get("username", "")

    sessionid = cookies_dict.get("sessionid", "")
    ds_user_id = cookies_dict.get("ds_user_id", "")
    current_mid = cookies_dict.get("mid", "")

    print(f"\n{'='*60}")
    print(f"Account   : {username}")
    print(f"UID       : {ds_user_id}")
    print(f"Mid (old) : {current_mid}")
    print(f"Proxy     : {proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url or 'NONE'}")
    print(f"{'='*60}\n")

    # Build web session same as enrich_web_cookies in ig_login_tool
    web = requests.Session()

    # Chrome User-Agent (same as enrich_web_cookies — safe, common web browser)
    web.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    })

    # Existing session cookies inject karo (sessionid, ds_user_id, current mid)
    for name in ("sessionid", "ds_user_id", "mid"):
        val = cookies_dict.get(name)
        if val:
            web.cookies.set(name, val, domain=".instagram.com")
            print(f"[cookie-inject] {name} = {val[:12]}...[{len(val)}]")

    # Proxy bind karo (same IP, same session)
    if proxy_url:
        web.proxies = {"http": proxy_url, "https": proxy_url}
        print(f"[proxy-bound] {proxy_url.split('@')[-1]}")
    else:
        print("[proxy] WARNING: No proxy set — using direct connection")

    # www.instagram.com GET karo (safe read-only request)
    print("\n[request] GET https://www.instagram.com/ ...")
    t0 = time.time()
    try:
        r = web.get("https://www.instagram.com/", timeout=30)
        elapsed = time.time() - t0
        print(f"[response] HTTP {r.status_code} in {elapsed:.2f}s | body: {len(r.content)} bytes")
    except Exception as e:
        print(f"[ERROR] Request failed: {e}")
        return None

    # Response cookies se mid extract karo
    jar = {c.name: c.value for c in web.cookies}
    print(f"\n[cookies received] {len(jar)} total: {list(jar.keys())}")

    new_mid = jar.get("mid", "")

    if new_mid:
        print(f"\n✅ mid CAPTURED: {new_mid}")
        if new_mid == current_mid:
            print("   (same as existing — server confirmed it, no change needed)")
        else:
            print(f"   OLD mid: {current_mid}")
            print(f"   NEW mid: {new_mid}")
        return new_mid, jar

    # FIX 12b fallback: www root ne mid nahi diya to web_profile_info
    # endpoint try karo — yeh mobile-API path www host pe serve hota hai
    # aur reliably fresh mid Set-Cookie karta hai (read-only, safe).
    print("\n[fallback] mid not in root response — trying web_profile_info ...")
    try:
        r2 = web.get(
            "https://www.instagram.com/api/v1/users/web_profile_info/?username=instagram",
            headers={"x-ig-app-id": "936619743392459"},
            timeout=30,
        )
        print(f"[fallback] HTTP {r2.status_code} | body: {len(r2.content)} bytes")
        jar2 = {c.name: c.value for c in web.cookies}
        new_mid = jar2.get("mid", "")
        if new_mid:
            print(f"\n✅ mid CAPTURED (fallback): {new_mid}")
            return new_mid, jar2
    except Exception as e:
        print(f"[fallback] failed: {e}")

    # Existing mid still valid as last resort
    print(f"\n⚠️  mid not in response cookies — server ne current mid confirm kiya")
    print(f"   Existing mid still valid: {current_mid}")
    return current_mid, jar


def update_cookie_file(path, data, new_mid, extra_web_cookies=None):
    """Cookie file me mid update karo aur optionally extra web cookies bhi."""
    changed = False

    # mid update
    old_mid = data["cookies"].get("mid", "")
    if new_mid and new_mid != old_mid:
        data["cookies"]["mid"] = new_mid
        print(f"\n[update] cookies.mid: {old_mid!r} → {new_mid!r}")
        changed = True
    else:
        print(f"\n[update] mid unchanged: {old_mid!r}")

    # Timestamp update
    data["mid_captured_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    changed = True  # always save to update timestamp

    save_cookie_file(path, data)
    print(f"[done] Cookie file updated!")
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--cookie-file",
        default=DEFAULT_COOKIE_FILE,
        help="Cookie JSON file path (default: cookies/cookies_badger.4951992.json)"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Sirf print karo, file save mat karo"
    )
    args = ap.parse_args()

    cookie_path = os.path.abspath(args.cookie_file)
    if not os.path.exists(cookie_path):
        print(f"[ERROR] Cookie file not found: {cookie_path}")
        sys.exit(1)

    print(f"[loading] {cookie_path}")
    data = load_cookie_file(cookie_path)

    # Step 1: Proxy lifetime check + fix (59m → 168h agar zaroorat ho)
    data, proxy_changed = ensure_proxy_168h(data, cookie_path)

    # Step 2: mid capture from web
    result = capture_mid_from_web(data)
    if result is None:
        print("[ABORT] Could not capture mid — network error")
        sys.exit(1)

    new_mid, web_jar = result

    # Step 3: Update cookie file
    if not args.dry_run:
        update_cookie_file(cookie_path, data, new_mid)
        print(f"\n{'='*60}")
        print(f"✅ DONE! Account {data.get('username')} ki mid cookie updated.")
        print(f"   mid: {new_mid}")
        print(f"   File: {cookie_path}")
        print(f"{'='*60}")
    else:
        print("\n[dry-run] File save skip kiya")
        print(f"   Would set mid → {new_mid}")


if __name__ == "__main__":
    main()
