#!/usr/bin/env python3
"""
ig_login.py — Instagram Android-API login (session/cookies nikalne ke liye)
MERGED FINAL BUILD v2 — PROXY-SAFE LEGACY PATH.

Do login paths:
  A) LEGACY (proxy-safe): /api/v1/accounts/login/ + /api/v1/accounts/two_factor_login/
     — 429 risk-gate sirf bloks endpoint par hai; legacy endpoint proxy IPs par
       bhi khula hai (empirically proven Aug 2026). PRIMARY path.
  B) BLOKS (captured app flow): fallback — real app jaisa telemetry samet;
     clean/real IPs par chalta hai.

Features:
  * force_ipv4       — IPv6 par app-session www-backend par 403 hota hai
  * auto TOTP        — --totp-secret se OTP khud (RFC 6238)
  * per-run IDs      — pigeon/waterfall constant (app jaisi continuity)
  * telemetry replay — bloks path par captured timings par
  * fresh 2SV ctx    — bloks 2FA ke liye parallel-array extraction
  * --new-device     — nayi device identity (throttled profile ki jagah)
  * --web-cookies    — OPT-IN web jar (default OFF: surface mixing = flag)
  * session_valid    — suspended/challenge/logout_reason detection

USAGE:
  pip install requests pycryptodomex
  pip install curl_cffi            # optional TLS impersonation
  python ig_login.py --username U --password "P" [--totp-secret KEY]
                     [--new-device] [--web-cookies]

SIRF APNE ACCOUNT KE LIYE. ToS ke khilaaf ho sakta hai; checkpoint/ban possible.
Educational/security-research use only.
"""
try:
    import force_ipv4  # noqa: F401  (sabse pehle — sockets patch)
except ImportError:
    print("note: force_ipv4.py nahi mila — IPv4 forcing skip")

import argparse
import base64
import hashlib
import hmac
import json
import os
import random
import re
import struct
import time
import uuid
import urllib.parse

import requests
from Cryptodome.Cipher import AES, PKCS1_v1_5
from Cryptodome.PublicKey import RSA
from Cryptodome.Random import get_random_bytes

BASE = "https://i.instagram.com"
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = json.load(open(os.path.join(HERE, "templates.json"), encoding="utf-8"))
RUN_DEVICE = {}
RUN_GEO = {}

# Geo-identity presets — jis country ka proxy use ho raha hai, wahi select karo.
# Timezone/locale/startup-country sab isse match honge (mismatch = detection signal).
GEO_PRESETS = {
    "IN": {"timezone_offset": 19800, "locale": "en_IN",
           "accept_language": "en-IN, en-US", "startup_country": "IN"},
    "GB": {"timezone_offset": 3600, "locale": "en_GB",
           "accept_language": "en-GB, en-US", "startup_country": "GB"},
    "US": {"timezone_offset": -18000, "locale": "en_US",
           "accept_language": "en-US", "startup_country": "US"},
}


def apply_geo(geo):
    """Saare templates me timezone/locale/UA/startup-country patch karo."""
    for tmpl in TEMPLATES.values():
        h = tmpl.get("headers", {})
        h["x-ig-timezone-offset"] = str(geo["timezone_offset"])
        for k in ("x-ig-app-locale", "x-ig-device-locale", "x-ig-mapped-locale"):
            if k in h:
                h[k] = geo["locale"]
        if "accept-language" in h:
            h["accept-language"] = geo["accept_language"]
        h["x-ig-app-startup-country"] = geo["startup_country"]
        if "user-agent" in h:
            h["user-agent"] = re.sub(r";\s*en_[A-Z]{2};",
                                     f"; {geo['locale']};", h["user-agent"])

# ---- capture placeholders ----
TEMPLATE_USERNAME = "duck.88424236"
TEMPLATE_WATERFALL = "c95d3023-bcb7-42b7-868a-55d0bfa6d257"
TEMPLATE_PIGEON = "UFS-498a2032-db3f-45e9-92ab-d5cdf11c19a8-0"
TEMPLATE_AAC_TS = "1787398541"
CAPTURE_TS = 1787398543

# ---- per-RUN constants: real app poore session me same rakhta hai ----
RUN_WATERFALL = str(uuid.uuid4())
RUN_PIGEON = f"UFS-{uuid.uuid4()}-0"

TELEMETRY_PRE_OAUTH = ("log1", "log2", "log3")
TELEMETRY_PRE_LOGIN = ("log4", "logfb", "log5")
TELEMETRY_POST_LOGIN = ("log6",)


def now_ts():
    return int(time.time())


def now_rawclienttime():
    return f"{time.time():.3f}"


# ---------------------------------------------------------------- password v4
def password_encrypt(password: str, key_id: int, pub_key_b64: str) -> str:
    """#PWD_INSTAGRAM:4 — RSA(PKCS1v1.5) + AES-256-GCM, timestamp as AAD."""
    session_key = get_random_bytes(32)
    iv = get_random_bytes(12)
    ts = str(now_ts())
    recipient = RSA.import_key(base64.b64decode(pub_key_b64.encode()))
    rsa_enc = PKCS1_v1_5.new(recipient).encrypt(session_key)
    aes = AES.new(session_key, AES.MODE_GCM, iv)
    aes.update(ts.encode())
    enc, tag = aes.encrypt_and_digest(password.encode("utf8"))
    payload = base64.b64encode(
        b"\x01"
        + key_id.to_bytes(1, "big")
        + iv
        + len(rsa_enc).to_bytes(2, "little")
        + rsa_enc
        + tag
        + enc
    ).decode()
    return f"#PWD_INSTAGRAM:4:{ts}:{payload}"


# ------------------------------------------------------------------ helpers
def totp_code(secret: str, digits: int = 6, period: int = 30, t=None) -> str:
    """Authenticator-app jaisa TOTP code (RFC 6238, SHA1)."""
    secret = secret.replace(" ", "").upper()
    secret += "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(secret, casefold=True)
    now = int(t if t is not None else time.time())
    rem = period - now % period
    if t is None and rem < 8:
        print(f"   (OTP window khatam hone wali — {rem}s wait...)")
        time.sleep(rem)
        now = int(time.time())
    counter = now // period
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[19] & 15
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def patch_text(text: str, username: str, enc_pwd=None, code=None, ctx=None) -> str:
    """Exact-match substitutions on raw body/header text."""
    text = text.replace(TEMPLATE_USERNAME, username)
    text = text.replace(TEMPLATE_WATERFALL, RUN_WATERFALL)
    text = text.replace(TEMPLATE_PIGEON, RUN_PIGEON)
    text = text.replace(f'"aac_init_timestamp":{TEMPLATE_AAC_TS}',
                        f'"aac_init_timestamp":{now_ts()}')
    if enc_pwd is not None:
        text = re.sub(r"#PWD_INSTAGRAM:4:\d+:[A-Za-z0-9+/=]+", enc_pwd, text)
    if code is not None:
        text = re.sub(r'"code":"\d+"', f'"code":"{code}"', text)
    if ctx is not None:
        text = re.sub(r'"two_step_verification_context":"[^"]*"',
                      f'"two_step_verification_context":"{ctx}"', text)
    delta = now_ts() - CAPTURE_TS
    text = re.sub(r"\b1787398\d{6}\b",
                  lambda m: str(int(m.group(0)) + delta * 1000), text)
    text = re.sub(r"\b1787398\d{3}\b",
                  lambda m: str(int(m.group(0)) + delta), text)
    return text


def build_request(name, username, enc_pwd=None, code=None, ctx=None):
    t = TEMPLATES[name]
    headers = {}
    for k, v in t["headers"].items():
        kl = k.lower()
        if kl == "x-pigeon-rawclienttime":
            v = now_rawclienttime()
        elif kl == "x-fb-conn-uuid-client":
            v = uuid.uuid4().hex
        headers[k] = patch_text(v, username, enc_pwd, code, ctx)
    body = t["body"]
    if body and "urlencoded" in headers.get("content-type", ""):
        pairs = urllib.parse.parse_qsl(body, keep_blank_values=True)
        pairs = [(k, patch_text(v, username, enc_pwd, code, ctx)) for k, v in pairs]
        body = urllib.parse.urlencode(pairs, quote_via=urllib.parse.quote)
    else:
        body = patch_text(body, username, enc_pwd, code, ctx)
    return t["method"], f"https://{t['host']}{t['path']}", headers, body


def find_key(obj, name):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == name and isinstance(v, str):
                return v
            r = find_key(v, name)
            if r:
                return r
    elif isinstance(obj, list):
        for it in obj:
            r = find_key(it, name)
            if r:
                return r
    elif isinstance(obj, str) and name in obj:
        m = re.search(re.escape(name) + r'["\\\s]*:[\\\s"]*([^"\\]+)', obj)
        if m:
            return m.group(1)
    return None


def extract_2sv_context(text: str):
    """send_login response se fresh two_step_verification_context (bloks)."""
    try:
        ctx = find_key(json.loads(text), "two_step_verification_context")
        if ctx:
            return ctx
    except Exception:
        pass
    cand = text
    for _ in range(6):
        cand = cand.replace("\\\\", "\\").replace('\\"', '"').replace("\\/", "/")
        m = re.search(r'two_step_verification_context.{0,400}?'
                      r'bk\.action\.array\.Make,\s*"([A-Za-z0-9+/=_\-]{200,})',
                      cand, re.S)
        if m:
            return m.group(1)
        m = re.search(r'two_step_verification_context["\\\s]*:[\\\s"]*'
                      r'([A-Za-z0-9+/=_\-]{200,})', cand)
        if m:
            return m.group(1)
    return None


def unescape(s: str) -> str:
    for _ in range(4):
        s = (s.replace("\\u0025", "%").replace("\\/", "/")
              .replace('\\"', '"').replace("\\\\", "\\"))
    return urllib.parse.unquote(s)


def derive_cookies_from_token(auth: str):
    """Bearer IGT:2:<base64-json> me sessionid/ds_user_id embedded hota hai."""
    cookies = {}
    try:
        b64 = auth.split("IGT:2:", 1)[1]
        b64 += "=" * (-len(b64) % 4)
        j = json.loads(base64.b64decode(b64))
        sid = urllib.parse.unquote(j.get("sessionid", ""))
        if sid:
            cookies["sessionid"] = sid
        if j.get("ds_user_id"):
            cookies["ds_user_id"] = str(j["ds_user_id"])
    except Exception as e:
        print("token decode warn:", e)
    return cookies


def enrich_web_cookies(cookies: dict):
    """OPT-IN: sessionid se www.instagram.com hit karke web jar lao."""
    web = requests.Session()
    web.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    for name in ("sessionid", "ds_user_id", "mid"):
        if cookies.get(name):
            web.cookies.set(name, cookies[name], domain=".instagram.com")
    try:
        web.get("https://www.instagram.com/", timeout=30,
                headers={"Accept": "text/html"})
        jar = {c.name: c.value for c in web.cookies}
        for k, v in jar.items():
            cookies.setdefault(k, v)
        print(f"[web jar] {len(jar)} cookies mile")
    except Exception as e:
        print("web jar warn:", e)
    return cookies


def extract_credentials(text: str):
    creds = {"cookies": {}, "authorization": None}
    m = re.search(r"Bearer IGT:2:[A-Za-z0-9_\-.]+", text)
    if m:
        creds["authorization"] = m.group(0)
    for m in re.finditer(r"[Ss]et-[Cc]ookie:\s*([a-z0-9_]+)=((?:[^;\\\"]|\\.)*)",
                         text):
        val = unescape(m.group(2).strip())
        if val:
            creds["cookies"][m.group(1)] = val
    return creds


def make_session():
    """TLS fingerprint: curl_cffi se Android-Chrome impersonate (optional)."""
    try:
        from curl_cffi import requests as cffi_requests
        for imp in ("chrome99_android", "chrome110", "chrome120", "chrome99"):
            try:
                sess = cffi_requests.Session(impersonate=imp)
                sess.get("https://example.com", timeout=10)
                print(f">> TLS impersonation: {imp}")
                return sess
            except Exception:
                continue
    except ImportError:
        pass
    print("note: curl_cffi nahi mila — default requests TLS")
    return requests.Session()


# ------------------------------------------------- PATH A: legacy (proxy-safe)
def legacy_login(username, password, totp_secret=None):
    """Purana non-bloks login — 429-gate se bahar (proxy par proven).
    ZARURI: plain Python TLS — curl_cffi impersonation ko legacy endpoint
    429 karta hai (empirical, Aug 2026). Returns (authorization, cookies)."""
    s = requests.Session()  # deliberately plain requests, no impersonation
    _, _, hdrs, _ = build_request("mobileconfig", username)
    hdrs = dict(hdrs)
    r = s.get(f"{BASE}/api/v1/qe/sync/", headers=hdrs, timeout=30)
    key_id = int(r.headers.get("ig-set-password-encryption-key-id", "0"))
    pub = r.headers.get("ig-set-password-encryption-pub-key", "")
    if not pub:
        return None, {}
    mc = TEMPLATES["mobileconfig"]["headers"]
    enc = password_encrypt(password, key_id, pub)
    body = {
        "jazoest": "2" + str(sum(ord(c) for c in username)),
        "phone_id": str(uuid.uuid4()), "enc_password": enc,
        "username": username, "adid": str(uuid.uuid4()),
        "device_id": mc.get("x-ig-android-id", ""),
        "google_tokens": "[]", "login_attempt_count": "1",
        "country_codes": json.dumps([{"country_code": "1",
                                      "source": ["default"]}]),
        "machine_id": mc.get("x-mid", ""),
    }
    data = urllib.parse.urlencode(
        {"signed_body": "SIGNATURE." + json.dumps(body, separators=(",", ":"))})
    hdrs["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    r = s.post(f"{BASE}/api/v1/accounts/login/", headers=hdrs, data=data,
               timeout=30)
    print(f"[legacy login            ] {r.status_code}")
    try:
        j = r.json()
    except Exception:
        j = {}
    if j.get("two_factor_required"):
        tid = (j.get("two_factor_info") or {}).get("two_factor_identifier", "")
        secret = totp_secret or os.environ.get("IG_TOTP_SECRET")
        if secret:
            code = totp_code(secret)
            print(f">> Auto TOTP code: {code}")
        else:
            code = input("2FA code (authenticator app se): ").strip()
        body2 = {"username": username, "verification_code": code,
                 "two_factor_identifier": tid, "trust_this_device": "1",
                 "verification_method": "3",
                 "device_id": mc.get("x-ig-android-id", "")}
        data2 = urllib.parse.urlencode(
            {"signed_body": "SIGNATURE." + json.dumps(body2, separators=(",", ":"))})
        r = s.post(f"{BASE}/api/v1/accounts/two_factor_login/", headers=hdrs,
                   data=data2, timeout=30)
        print(f"[legacy two_factor_login ] {r.status_code}")
        try:
            j = r.json()
        except Exception:
            j = {}
    if r.status_code != 200 or not j.get("logged_in_user"):
        return None, {}
    return r.headers.get("ig-set-authorization"), {c.name: c.value for c in r.cookies}


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--username")
    ap.add_argument("--password")
    ap.add_argument("--totp-secret",
                    help="2FA authenticator ki base32 secret key — OTP khud banega")
    ap.add_argument("--web-cookies", action="store_true",
                    help="OPT-IN: www.instagram.com se web jar. Default OFF.")
    ap.add_argument("--new-device", action="store_true",
                    help="Nayi device identity — throttled profile ki jagah")
    ap.add_argument("--country", default="IN",
                    help="Proxy ka country (IN/GB/US) — timezone/locale isi se "
                         "match honge. Ya explicit JSON: "
                         "'{\"timezone_offset\":3600,\"locale\":\"en_GB\"}'")
    args = ap.parse_args()

    global TEMPLATES, RUN_DEVICE, RUN_GEO
    RUN_DEVICE = {}

    # ---- GEO identity: proxy ke country se match karo ----
    try:
        g = json.loads(args.country) if args.country.strip().startswith("{") else None
    except Exception:
        g = None
    if g:
        base = dict(GEO_PRESETS.get((g.get("preset") or "IN").upper(), GEO_PRESETS["IN"]))
        base.update({k: v for k, v in g.items() if k != "preset"})
        RUN_GEO = base
    else:
        RUN_GEO = dict(GEO_PRESETS.get(args.country.upper(), GEO_PRESETS["IN"]))
    apply_geo(RUN_GEO)
    print(f">> GEO identity: {args.country.upper()} -> tz={RUN_GEO['timezone_offset']}, "
          f"locale={RUN_GEO['locale']}")
    if args.new_device:
        new_mid = base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("=")
        repl = {
            "android-6c2500024b273e42": "android-" + os.urandom(8).hex(),
            "39bb14e5-5663-4ab9-94ab-9dd8ed1bffa9": str(uuid.uuid4()),
            "030d0d6e-a43e-4541-8302-dc38820916ce": str(uuid.uuid4()),
            "aomDBgABAAEprcPvkiF-ntXL6_nV": new_mid,
        }
        blob = json.dumps(TEMPLATES)
        for old, new in repl.items():
            blob = blob.replace(old, new)
        TEMPLATES = json.loads(blob)
        RUN_DEVICE = {"android_id": repl["android-6c2500024b273e42"],
                      "device_uuid": repl["39bb14e5-5663-4ab9-94ab-9dd8ed1bffa9"],
                      "family_uuid": repl["030d0d6e-a43e-4541-8302-dc38820916ce"]}
        print(">> New device profile:")
        for v in repl.values():
            print("   ", v)

    username = args.username or input("Username: ").strip()
    password = args.password or input("Password: ").strip()

    s = make_session()
    creds = {"cookies": {}, "authorization": None}

    # ---------- PATH A: legacy endpoint (proxy-safe, primary) ----------
    try:
        auth, lcookies = legacy_login(username, password, args.totp_secret)
        if auth:
            creds["authorization"] = auth
            creds["cookies"].update(lcookies)
            print(">> PATH A (legacy endpoint) se login SUCCESS")
    except Exception as e:
        print("legacy login warn:", e)

    # ---------- PATH B: bloks captured flow (fallback) ----------
    if not creds["authorization"]:
        def send(name, enc_pwd=None, code=None, ctx=None, quiet=False):
            if name not in TEMPLATES:
                return None
            if not quiet:
                time.sleep(random.uniform(0.7, 1.9))  # real-app jaisa step gap
            method, url, headers, body = build_request(
                name, username, enc_pwd, code, ctx)
            r = s.request(method, url, headers=headers,
                          data=body.encode() if body else None, timeout=30)
            if not quiet:
                print(f"[{name:22s}] {r.status_code} {len(r.content)}B")
            return r

        def telemetry(names):
            for n in names:
                try:
                    send(n, quiet=True)
                except Exception:
                    pass

        print(">> PATH B (bloks captured flow) try...")
        send("mobileconfig")
        try:
            send("attestation")
        except Exception as e:
            print("attestation skip:", e)
        _, url, headers, _ = build_request("mobileconfig", username)
        r = s.get(f"{BASE}/api/v1/qe/sync/", headers=headers, timeout=30)
        key_id = int(r.headers.get("ig-set-password-encryption-key-id", "0"))
        pub_key = r.headers.get("ig-set-password-encryption-pub-key", "")
        if not pub_key:
            raise SystemExit("qe/sync se public key nahi mili — network/IP issue?")
        enc_pwd = password_encrypt(password, key_id, pub_key)

        send("process_client_data")
        send("youthreg")
        send("phone_prefill")
        telemetry(TELEMETRY_PRE_OAUTH)
        send("oauth_token_fetch")
        telemetry(TELEMETRY_PRE_LOGIN)

        r = send("send_login", enc_pwd=enc_pwd)
        if r is None or r.status_code == 429:
            print("\nLOGIN BLOCKED (429) on bloks path. Legacy path bhi fail tha — "
                  "real IP se try karo ya thoda wait karo.")
            raise SystemExit(2)
        text = r.text
        creds = extract_credentials(text)
        telemetry(TELEMETRY_POST_LOGIN)

        if not creds["authorization"] and "two_step_verification" in text:
            print("\n>> 2FA (bloks two-step verification) required!")
            ctx = extract_2sv_context(text)
            if not ctx:
                print("WARN: 2SV context nahi mila")
            send("twostep_entry", ctx=ctx)
            secret = args.totp_secret or os.environ.get("IG_TOTP_SECRET")
            if secret:
                code = totp_code(secret)
                print(f">> Auto TOTP code: {code}")
            else:
                code = input("2FA code (authenticator app se): ").strip()
            send("twostep_poll", ctx=ctx)
            r = send("twostep_verify", code=code, ctx=ctx)
            text = r.text
            creds = extract_credentials(text)

        if not creds["authorization"] and not creds["cookies"]:
            print("\nLOGIN FAILED — response ka relevant hissa:")
            print(text[:1500])
            raise SystemExit(1)

    # ---------- merge + enrich ----------
    if creds["authorization"]:
        creds["cookies"].update(
            derive_cookies_from_token(creds["authorization"]))
        mid = TEMPLATES["mobileconfig"]["headers"].get("x-mid", "")
        if mid:
            creds["cookies"].setdefault("mid", mid)
        if args.web_cookies:
            creds["cookies"] = enrich_web_cookies(creds["cookies"])
        elif not creds["cookies"].get("csrftoken"):
            print("note: csrftoken nahi mila (sirf app-surface cookies). "
                  "Web use chahiye to --web-cookies flag samajh kar lagayein.")

    # ---------- verify: authentication vs authorization ----------
    uid = creds["cookies"].get("ds_user_id", "")
    hdr_verify = dict(TEMPLATES["mobileconfig"]["headers"])
    hdr_verify.pop("content-type", None)
    if creds["authorization"]:
        hdr_verify["authorization"] = creds["authorization"]
        hdr_verify["ig-intended-user-id"] = uid
        hdr_verify["ig-u-ds-user-id"] = uid
        hdr_verify["ig-u-rur"] = "ODN"
    rv = s.get(f"{BASE}/api/v1/users/{uid}/info/",
               headers=hdr_verify, timeout=30)
    print(f"[verify session]           {rv.status_code}")
    rv_text = rv.text
    account_ok = rv.status_code == 200
    if "accounts/suspended" in rv_text or "suspended/" in rv_text:
        print("*** ACCOUNT SUSPENDED — token mila lekin session use nahi ho sakta ***")
        print("    Appeal: https://www.instagram.com/accounts/suspended/")
        account_ok = False
    elif "challenge_required" in rv_text:
        print("*** CHALLENGE REQUIRED — account pe lock/challenge hai ***")
        account_ok = False
    elif "login_required" in rv_text:
        try:
            lr = str(rv.json().get("logout_reason", ""))
        except Exception:
            lr = ""
        reasons = {"2": "Device/IP mismatch ya account restricted",
                   "6": "Session expired", "7": "Account suspended",
                   "8": "Session replaced"}
        print(f"*** SESSION INVALID — {reasons.get(lr, 'logout_reason=' + lr)} ***")
        account_ok = False

    out = {
        "username": username,
        "authorization": creds["authorization"],
        "cookies": creds["cookies"],
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "session_valid": account_ok,
    }
    if RUN_DEVICE:
        out["device"] = RUN_DEVICE  # per-account device identity (multi-account)
    if RUN_GEO:
        out["geo"] = RUN_GEO  # timezone/locale — proxy country se match
    with open(os.path.join(HERE, "cookies.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("\n=== COOKIES / SESSION ===")
    for k, v in creds["cookies"].items():
        print(f"  {k} = {v[:12]}...[{len(v)}]")
    if creds["authorization"]:
        print(f"  Authorization = {creds['authorization'][:30]}..."
              f"[{len(creds['authorization'])}]")
    if account_ok:
        print("\nSaved -> cookies.json  [SESSION VALID]")
    else:
        print("\nSaved -> cookies.json  [WARNING: account restricted/suspended — "
              "session use nahi hogi!]")


if __name__ == "__main__":
    main()
