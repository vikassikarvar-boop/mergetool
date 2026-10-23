#!/usr/bin/env python3
"""
proxy_scout.py — proxy sessions ko pre-screen karo, best IP chuno.

Meta ki internal IP-intelligence public nahi hai, isliye koi guarantee nahi —
lekin obviously-bad IPs (datacenter, flagged proxy, galat country) ko public
DBs se chhaan kar "1 IP = 1 login attempt" protocol follow karo.

Usage:
  python proxy_scout.py --proxy-base geo.iproyal.com:12321:USER:PASS \
                        --country US --sessions 5

Output: har session ka IP, country, org, public fraud-risk.
Phir best IP wala READY command print hota hai — usse EK hi login attempt karo
(ig_login.py ke saath HTTPS_PROXY env set karke). 429 aaye to wo IP drop karo,
retry MAT karo.
"""
import argparse
import random
import re
import string
import sys

import requests


def session_proxy(base: str, sid: str) -> str:
    host, port, user, pas = base.split(":", 3)
    auth = f"{user}:{pas}_country-{args.country.lower()}_session-{sid}_lifetime-59m"
    return f"http://{auth}@{host}:{port}"


def public_risk(ip: str) -> str:
    try:
        r = requests.get(f"https://scamalytics.com/ip/{ip}", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        m = re.search(r'risk" style="background-color: #[0-9a-fA-F]+">(\w+)',
                      r.text)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


def main():
    global args
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy-base", required=True,
                    help="host:port:user:pass (bina country/session params)")
    ap.add_argument("--country", default="us")
    ap.add_argument("--sessions", type=int, default=5)
    args = ap.parse_args()

    rows = []
    for i in range(args.sessions):
        sid = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        purl = session_proxy(args.proxy_base, sid)
        prox = {"http": purl, "https": purl}
        try:
            ip = requests.get("https://api.ipify.org", proxies=prox,
                              timeout=20).text.strip()
            info = requests.get(f"https://ipinfo.io/{ip}/json",
                                timeout=15).json()
            risk = public_risk(ip)
            ok_country = (info.get("country", "") or "").lower() == args.country.lower()
            org = info.get("org", "")
            mobile = any(k in org.lower() for k in
                         ("wireless", "mobile", "t-mobile", "verizon", "at&t",
                          "cellular", "idea", "airtel", "jio"))
            rows.append((ip, info.get("country"), org, risk, ok_country, mobile, sid))
            print(f"[{i+1}] {ip:16s} {info.get('country')} | {risk:6s} | "
                  f"{'MOBILE' if mobile else 'other ':6s} | {org[:44]}")
        except Exception as e:
            print(f"[{i+1}] session {sid} fail: {e}")

    # best pick: country match + Low risk + mobile preferred
    def score(r):
        return (r[4], r[3] == "Low", r[5])
    good = [r for r in rows if r[4]]
    if not good:
        print("\nKoi session target country me nahi mila.")
        sys.exit(1)
    best = max(good, key=score)
    purl = session_proxy(args.proxy_base, best[6])
    print("\n=== BEST CANDIDATE ===")
    print(f"IP: {best[0]}  risk(public): {best[3]}  org: {best[2]}")
    print("\nReady command (EK hi attempt; 429 aaye to IP drop karo):")
    print(f'  set HTTPS_PROXY={purl}')
    print(f'  set HTTP_PROXY={purl}')
    print('  python ig_login.py --username ... --password "..." --totp-secret ...')


if __name__ == "__main__":
    main()
