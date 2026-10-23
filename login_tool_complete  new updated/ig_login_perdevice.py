#!/usr/bin/env python3
"""
ig_login_perdevice.py — ig_login.py ka copy jisme har account ke liye
ALAG device fingerprint generate hota hai (username se seed leke).

Kyun zaroori hai:
  Original ig_login.py mein templates.json ka ek hi device ID (duck account ka)
  har account ke liye use hota hai. Instagram ek device se multiple accounts
  detect kar ke ban kar deta hai.

Yeh script username ko seed maan ke deterministically generate karti hai:
  - x-ig-android-id   (unique per account)
  - x-ig-device-id    (unique UUID per account)
  - x-ig-family-device-id (unique UUID per account)
  Baaki sab (user-agent, app-id, capabilities) real app values remain karte hain.

Yeh script templates.json me stored REAL APP (Instagram 451.0.0.53.80 Android) ke
exact request formats ko replay karti hai — headers/body byte-for-byte captured
successful session se liye gaye hain, sirf dynamic fields (timestamps, uuids,
encrypted password, 2FA code) runtime par bhare jaate hain.

Flow (captured sequence):
  1. POST /api/v1/launcher/mobileconfig/
  2. POST /api/v1/attestation/create_android_keystore/   (optional, fail-safe)
  3. GET  /api/v1/qe/sync/                               (password-encryption public key)
  4. POST bloks .../bloks.caa.login.process_client_data_and_redirect/
  5. POST bloks .../reg.youthregulation.deletepregent.async/
  6. POST bloks .../caa.phone.number.prefill.async.controller/
  7. POST bloks .../caa.login.oauth.token.fetch.async/
  8. POST bloks .../bloks.caa.login.async.send_login_request/   (enc password)
  9. (agar 2FA ho) two_step_verification entrypoint/poll/verify_code
 10. Response se Bearer IGT token + Set-Cookie strings extract -> cookies.json

USAGE:
  pip install requests pycryptodome
  python ig_login.py                (username/password prompt honge)
  ya
  python ig_login.py --username X --password Y

SIRF APNE ACCOUNT KE LIYE USE KAREIN. Instagram ToS ke khilaaf ho sakta hai;
account checkpoint/ban ho sakta hai. Educational/security-research use only.
"""
import force_ipv4  # IPv6 pe Instagram app session www-backend route hoti hai (403) — IPv4 force karo
import argparse
import base64
import hashlib
import hmac
import json
import os
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

# ---------- FIX E: uTLS transport (curl_cffi) — instagrapi 3.1 parity, Oct 2026 ----------
# Problem: python-requests ka TLS ClientHello + HTTP/1.1 IG ke login endpoint pe pakda
# jata hai — symptom: send_login pe 429 with EMPTY body jabki baaki endpoints 200 dete
# hain (instagrapi issue #2852 ka pattern). instagrapi ne 19-20 Oct 2026 ko yahi fix
# merge kiya (transports.py: "strict opt-in uTLS transport" + "native HTTP/2 peer
# settings"). Yeh uska faithful port hai:
#   * HTTP/2-only ALPN — h2 negotiate na ho to ConnectionError
#   * TLS 1.3 ONLY — legacy versions ClientHello se bahar
#   * EC curves: X25519MLKEM768:X25519:P-256:P-384 (modern Android app jaisa)
#   * browser impersonation OFF; cookies/redirects/decompression requests ke paas
# Install: pip install "curl_cffi>=0.15.0"   (libcurl >= 8.10.0 bundled hona chahiye)


def create_curl_h2_adapter():
    """curl_cffi-backed requests HTTPAdapter (instagrapi transports.py port)."""
    import os as _tls_os
    import re as _tls_re
    from email.message import Message
    from io import BytesIO
    from types import SimpleNamespace
    from urllib.parse import urlsplit

    from requests import exceptions
    from requests.adapters import HTTPAdapter
    from requests.utils import select_proxy
    from urllib3._collections import HTTPHeaderDict
    from urllib3.response import HTTPResponse

    try:
        import curl_cffi
        from curl_cffi import CurlHttpVersion, CurlOpt, CurlSslVersion, ffi
        from curl_cffi import requests as curl_requests
    except ImportError as exc:
        raise RuntimeError(
            'uTLS transport ke liye install karo:  pip install "curl_cffi>=0.15.0"'
        ) from exc

    version = _tls_re.search(r"libcurl/(\d+)\.(\d+)\.(\d+)", curl_cffi.__curl_version__)
    if not version or tuple(map(int, version.groups())) < (8, 10, 0):
        raise RuntimeError(
            "uTLS transport needs libcurl >= 8.10.0 — pip install -U curl_cffi"
        )

    class _CurlH2Adapter(HTTPAdapter):
        """h2-only ALPN transport. Requests owns redirects, cookies, decompression;
        curl owns the wire. Browser impersonation disabled (app-like, not chrome)."""

        def __init__(self):
            super().__init__(max_retries=0)
            self._http2 = CurlHttpVersion.V2_0
            self._capath_option = CurlOpt.CAPATH
            self._cainfo_option = CurlOpt.CAINFO
            self._null_pointer = ffi.NULL
            self.client = curl_requests.Session(
                trust_env=False,
                default_headers=False,
                discard_cookies=True,
                http_version=CurlHttpVersion.V2_PRIOR_KNOWLEDGE,
                curl_options={
                    CurlOpt.HTTP_CONTENT_DECODING: 0,
                    CurlOpt.NOPROXY: "",
                    CurlOpt.SSLVERSION: CurlSslVersion.TLSv1_3,
                    CurlOpt.SSL_EC_CURVES: "X25519MLKEM768:X25519:P-256:P-384",
                },
            )
            self.client.verify = True

        def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
            if timeout is not None:
                values = timeout if isinstance(timeout, tuple) else (timeout,)
                if (isinstance(timeout, tuple) and len(timeout) != 2) or any(
                    not isinstance(value, (int, float)) for value in values
                ):
                    raise ValueError("curl timeout must be numeric, a pair of numeric values, or None")
            self.client.curl_options.pop(self._capath_option, None)
            self.client.curl_options.pop(self._cainfo_option, None)
            if isinstance(verify, str) and _tls_os.path.isdir(verify):
                self.client.curl_options[self._capath_option] = verify
                self.client.curl_options[self._cainfo_option] = self._null_pointer
                verify = True
            body = request.body
            if hasattr(body, "read"):
                body = body.read()
            if body is not None and not isinstance(body, (str, bytes, bytearray)):
                body = b"".join(chunk.encode() if isinstance(chunk, str) else chunk for chunk in body)
            if isinstance(body, bytearray):
                body = bytes(body)
            try:
                upstream = self.client.request(
                    request.method,
                    request.url,
                    data=body,
                    headers=list(request.headers.items()),
                    proxies={"all": select_proxy(request.url, proxies) or ""},
                    timeout=timeout,
                    verify=verify,
                    cert=cert,
                    allow_redirects=False,
                    default_headers=False,
                    accept_encoding=None,
                    discard_cookies=True,
                    quote=False,
                )
            except curl_requests.exceptions.RequestException as exc:
                # curl_cffi exceptions ko requests-compatible category me map karo
                error_class = exceptions.RequestException
                transport_errors = {
                    # partial transfer pe credential-bearing POST dobara submit NAHI hona chahiye
                    "IncompleteRead": exceptions.ConnectionError,
                    "HTTPError": exceptions.ConnectionError,
                }
                for parent in type(exc).__mro__:
                    candidate = transport_errors.get(parent.__name__, getattr(exceptions, parent.__name__, None))
                    if isinstance(candidate, type) and issubclass(candidate, exceptions.RequestException):
                        error_class = candidate
                        break
                raise error_class(f"curl uTLS transport failed ({type(exc).__name__})", request=request) from exc

            if urlsplit(request.url).scheme == "https" and upstream.http_version != self._http2:
                raise exceptions.ConnectionError("uTLS transport did not negotiate HTTP/2", request=request)

            pairs = list(upstream.headers.multi_items())
            message = Message()
            for name, value in pairs:
                message[name] = value
            raw = HTTPResponse(
                body=BytesIO(upstream.content),
                headers=HTTPHeaderDict(pairs),
                status=upstream.status_code,
                reason=upstream.reason,
                version=20,
                request_method=request.method,
                preload_content=False,
                decode_content=False,
                original_response=SimpleNamespace(msg=message, close=lambda: None, isclosed=lambda: True),
            )
            return self.build_response(request, raw)

        def close(self):
            self.client.close()
            super().close()

    return _CurlH2Adapter()


def mount_tls_transport(s, tls_choice="auto"):
    """Session `s` pe uTLS adapter mount karo. Returns 'curl' ya 'requests'.
    auto     = curl_cffi available ho to uTLS, warna classic (warning ke saath)
    curl     = force uTLS — missing/broken ho to exit(2)
    requests = classic HTTP/1.1 (purana behavior)"""
    mode = (tls_choice or "auto").strip().lower()
    if mode not in ("auto", "curl", "requests"):
        mode = "auto"
    if mode == "requests":
        print("[tls] classic requests transport (HTTP/1.1)")
        return "requests"
    try:
        adapter = create_curl_h2_adapter()
    except RuntimeError as e:
        if mode == "curl":
            print(f"[tls] --tls curl chuna, par uTLS init FAIL: {e}")
            raise SystemExit(2)
        print(f"[tls] uTLS unavailable ({e})")
        print("[tls] classic requests (HTTP/1.1) pe fallback")
        return "requests"
    s.mount("https://", adapter)
    print("[tls] uTLS transport ON — HTTP/2-only + TLS1.3-only + X25519MLKEM768 curves (app-jaisa ClientHello)")
    return "curl"


# ---------- FIX O: WEB-MID capture (old-flow parity, 23 Oct 2026) ----------
# Mobile API 'mid' cookie set nahi karta. Purana flow ek SINGLE web call
# (https://www.instagram.com/) se Set-Cookie: mid capture karta tha — wahi mid
# device ke x-mid header, machine_id payloads aur saved cookies file me jata tha.
# Naye tool me ye step missing tha: perdevice khali mid bhejta tha, ig_login to
# templates ka STATIC captured mid har account me likh raha tha (sab accounts me
# same mid = correlation signal). Fix: har run pe ek web call → fresh per-run mid.

WEB_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_WEB_MID = ""   # web call se capture hua fresh mid (per-run)


def capture_web_mid(proxy_url=None, timeout=25):
    """Ek single GET https://www.instagram.com/ → Set-Cookie 'mid' capture.
    Returns (mid, status_code). Proxy diya ho to usi se jata hai (old-flow jaisa).
    Fail hone par flow NAHI rukta — khali mid = fresh-device behavior (server phir
    ig-set-x-mid response header se mid issue karta hai, jo _SERVER_MID me jata hai)."""
    global _WEB_MID
    web = requests.Session()
    if proxy_url:
        web.proxies = {"http": proxy_url, "https": proxy_url}
    try:
        r = web.get("https://www.instagram.com/",
                    headers={"User-Agent": WEB_BROWSER_UA,
                             "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                             "Accept-Language": "en-US,en;q=0.9"},
                    timeout=timeout)
        mid = ""
        try:
            mid = web.cookies.get("mid") or r.cookies.get("mid") or ""
        except Exception:
            mid = ""
        if not mid:
            m = re.search(r"\bmid=([^;]+)", r.headers.get("Set-Cookie", "") or "")
            if m:
                mid = m.group(1)
        if mid:
            _WEB_MID = mid
            print(f"[web-mid] single web call se fresh mid capture hua: {mid} (status {r.status_code})")
        else:
            print(f"[web-mid] mid cookie nahi mila (status {r.status_code}) — fresh-device mode")
        return mid, r.status_code
    except Exception as e:
        print(f"[web-mid] capture fail ({type(e).__name__}) — fresh-device mode")
        return "", 0
    finally:
        try:
            web.close()
        except Exception:
            pass


# ---------- USDID (X-Meta-Usdid) — instagrapi 3.x parity, Oct 2026 ----------
# Locally generated P-256 identity IGUSDIDRegistrationMutation (graphql_www @
# b.i.instagram.com) se register hoti hai. Registered USDID = CAA login ka
# important trust signal (instagrapi prepare() me ye REQUIRED hai).
USDID_REG_DOC_ID = "124930351917786857261002920888"
USDID_TOKEN_TTL = 3600
USDID_REFRESH_MARGIN = 300
_USDID = {"id": "", "kid": "", "key": "", "registered": False, "cache": "", "exp": 0}
_ATTEST_NONCES = ("", "")  # (challenge_nonce, key_nonce) — fresh from create_android_keystore


def _b64u(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def usdid_generate(force=False):
    from Cryptodome.PublicKey import ECC
    from Cryptodome.Random import get_random_bytes
    if _USDID["key"] and not force:
        return _USDID["id"]
    key = ECC.generate(curve="P-256")
    _USDID["key"] = key.export_key(format="PEM")
    _USDID["id"] = str(uuid.uuid4())
    _USDID["kid"] = _b64u(get_random_bytes(32))
    _USDID["registered"] = False
    _USDID["cache"] = ""
    _USDID["exp"] = 0
    return _USDID["id"]


def _usdid_sign(message):
    from Cryptodome.Hash import SHA256
    from Cryptodome.PublicKey import ECC
    from Cryptodome.Signature import DSS
    signer = DSS.new(ECC.import_key(_USDID["key"]), "fips-186-3", encoding="der")
    return signer.sign(SHA256.new(message.encode()))


def usdid_header(ttl=USDID_TOKEN_TTL):
    """App-style three-part signed X-Meta-Usdid value."""
    now = int(time.time())
    if _USDID["cache"] and _USDID["exp"] - now > USDID_REFRESH_MARGIN:
        return _USDID["cache"]
    exp = now + ttl
    signed_part = f"{_USDID['id']}.{exp}"
    val = f"{signed_part}.{_b64u(_usdid_sign(signed_part))}"
    _USDID["cache"] = val
    _USDID["exp"] = exp
    return val


def usdid_registration_token(app_id, ttl=USDID_TOKEN_TTL):
    """ES256 JWS registration token (payload+signatures, sab b64u)."""
    from Cryptodome.PublicKey import ECC
    now = int(time.time())
    pub_der = ECC.import_key(_USDID["key"]).public_key().export_key(format="DER")
    payload = _b64u(json.dumps({
        "sub": _USDID["id"], "iat": now, "aud": app_id, "exp": now + ttl,
        "pub": base64.b64encode(pub_der).decode(), "alg": "ES256",
    }, separators=(",", ":")).encode())
    protected = _b64u(json.dumps({
        "typ": "JWT", "alg": "ES256", "kid": _USDID["kid"], "aid": app_id, "ver": "1",
    }, separators=(",", ":")).encode())
    token = {"payload": payload,
             "signatures": [{"protected": protected,
                             "signature": _b64u(_usdid_sign(f"{protected}.{payload}"))}]}
    return _b64u(json.dumps(token, separators=(",", ":")).encode())


def usdid_register(s, base_headers, app_id, fdid):
    """IGUSDIDRegistrationMutation POST https://b.i.instagram.com/graphql_www"""
    usdid_generate()
    data = {
        "method": "post", "pretty": "false", "format": "json",
        "server_timestamps": "true", "locale": "user",
        "fb_api_req_friendly_name": "IGUSDIDRegistrationMutation",
        "enable_canonical_naming": "true",
        "enable_canonical_variable_overrides": "true",
        "enable_canonical_naming_ambiguous_type_prefixing": "true",
        "variables": json.dumps({"input": {
            "usdid_token": {"sensitive_string_value": usdid_registration_token(app_id)},
            "fdid": {"sensitive_string_value": fdid},
        }}, separators=(",", ":")),
        "purpose": "fetch",
        "client_doc_id": USDID_REG_DOC_ID,
    }
    headers = {k: v for k, v in base_headers.items() if k.lower() != "host"}
    headers.update({
        "host": "b.i.instagram.com",
        "x-fb-friendly-name": "IGUSDIDRegistrationMutation",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-client-doc-id": USDID_REG_DOC_ID,
        "x-root-field-name": "usdid_registration",
        "x-graphql-client-library": "pando",
    })
    try:
        r = s.post("https://b.i.instagram.com/graphql_www", data=data, headers=headers, timeout=30)
        js = r.json()
        ok = any("usdid_registration" in k and isinstance(v, dict) and v.get("success")
                 for k, v in (js.get("data") or {}).items())
        _USDID["registered"] = bool(ok)
        print(f"[usdid] registration {r.status_code} {len(r.content)}B -> {'OK' if ok else 'FAIL (aage bina X-Meta-Usdid header ke)'}")
        return ok
    except Exception as e:
        print(f"[usdid] registration skip ({type(e).__name__}: {str(e)[:60]})")
        return False


# --- App identity (version profile) ---
# DEFAULT = 449: templates.json ka bloks_versioning_id (799db3e3...) 449 ka hai,
# aur instagrapi (master, Oct 2026) + instagram-cli PR#390 dono 449.0.0.52.84
# chalate hain. 451 mode = experimental (451 UA + 449 bloks hash = inconsistent).
APP_PROFILES = {
    "449": {"version": "449.0.0.52.84", "code": "1079242191",
            "bloks": "799db3e387d7a21a19c72918b8698b6cd28a1516ade363792c100ed45a0f9f0b",
            "pixel": True},
    "451": {"version": "451.0.0.53.80", "code": "385713073", "bloks": "", "pixel": False},
    "448": {"version": "448.0.0.0.20", "code": "1065560286",
            "bloks": "0bc46a03e177bfc9bc8d611918815acf248fa9c77754d807d6a5951dc9ce9432",
            "pixel": True},
}
DEFAULT_APP_PROFILE = "449"
TEMPLATES_ONDISK_VERSION = "451.0.0.53.80"  # disk par templates 451 strings se patched hain
TEMPLATES_ONDISK_CODE = "385713073"
TEMPLATES_BLOKS_449 = "799db3e387d7a21a19c72918b8698b6cd28a1516ade363792c100ed45a0f9f0b"
# instagrapi config.py (Oct 2026) ka default device — 449 app isi par chalta hai.
# Purane Android 8/9 pool devices par 449 install hi nahi ho sakta = identity mismatch.
PIXEL_8_PRO = {"manufacturer": "Google/google", "model": "Pixel 8 Pro",
               "device_codename": "husky", "cpu": "husky",
               "android_version": "14", "api_level": "34",
               "resolution": "1344x2992", "dpi": "480dpi"}
APP_VERSION = APP_PROFILES[DEFAULT_APP_PROFILE]["version"]
APP_CODE = APP_PROFILES[DEFAULT_APP_PROFILE]["code"]


def apply_app_profile(name):
    """Chosen app identity par poora flow: templates version+bloks-hash swap ke
    saath reload; 449/448 par device pool Pixel 8 Pro (Android 14) ho jata hai."""
    global TEMPLATES, DEVICE_POOL, APP_VERSION, APP_CODE
    tgt = APP_PROFILES.get((name or "").strip()) or APP_PROFILES[DEFAULT_APP_PROFILE]
    APP_VERSION, APP_CODE = tgt["version"], tgt["code"]

    def _reload(fname):
        raw = open(os.path.join(HERE, fname), encoding="utf-8").read()
        raw = raw.replace(TEMPLATES_ONDISK_VERSION, tgt["version"])
        raw = raw.replace(TEMPLATES_ONDISK_CODE, tgt["code"])
        if tgt.get("bloks") and tgt["bloks"] != TEMPLATES_BLOKS_449:
            raw = raw.replace(TEMPLATES_BLOKS_449, tgt["bloks"])
        return json.loads(raw)

    TEMPLATES = _reload("templates.json")
    try:
        DEVICE_POOL = _reload("device_pool.json")
    except (OSError, ValueError):
        DEVICE_POOL = []
    if tgt.get("pixel"):
        for _p in DEVICE_POOL:
            _p.update(PIXEL_8_PRO)
    print(f"[profile] App identity: {tgt['version']} / code {tgt['code']}" + (" / Pixel 8 Pro (Android 14) device set" if tgt.get("pixel") else ""))



# ---- capture me dekha gaya original username (template placeholder) ----
TEMPLATE_USERNAME   = "duck.88424236"
TEMPLATE_WATERFALL  = "c95d3023-bcb7-42b7-868a-55d0bfa6d257"
TEMPLATE_PIGEON     = "UFS-498a2032-db3f-45e9-92ab-d5cdf11c19a8-0"
TEMPLATE_AAC_TS     = "1787398541"

# ---- Original template device values (duck account) ----
TEMPLATE_ANDROID_ID   = "android-6c2500024b273e42"
TEMPLATE_DEVICE_ID    = "39bb14e5-5663-4ab9-94ab-9dd8ed1bffa9"
TEMPLATE_FAMILY_ID    = "030d0d6e-a43e-4541-8302-dc38820916ce"

# ---- 2026 CAA runtime state ----
_FRESH_AAC = ""   # server-issued aac (process_client_data response se)
_SERVER_MID = ""  # server-issued machine id (ig-set-x-mid header se)


def make_device_fingerprint(username: str) -> dict:
    """
    Username se deterministic (reproducible) unique device fingerprint banao.

    Same username = same fingerprint (consistent across runs).
    Alag username = alag fingerprint (alag phone jaisa lagega Instagram ko).

    Algorithm:
      - username ko SHA-256 hash karo (seed)
      - us seed se android_id, device_uuid, family_uuid derive karo
      - Format real Android app jaisa rakho
    """
    seed = hashlib.sha256(username.lower().encode()).digest()

    # android-id: "android-" + 16 hex chars
    android_hex = seed[:8].hex()           # 16 hex chars
    android_id  = f"android-{android_hex}"

    # device-id: UUID v4 format (deterministic)
    # UUID = 8-4-4-4-12 hex format
    d = seed[8:24]   # 16 bytes
    device_id = (
        f"{d[0:4].hex()}-{d[4:6].hex()}-"
        f"{(d[6] & 0x0f | 0x40):02x}{d[7]:02x}-"
        f"{(d[8] & 0x3f | 0x80):02x}{d[9]:02x}-"
        f"{d[10:16].hex()}"
    )

    # family-device-id: UUID format (different seed offset)
    seed2 = hashlib.sha256((username.lower() + "_family").encode()).digest()
    f2 = seed2[:16]
    family_id = (
        f"{f2[0:4].hex()}-{f2[4:6].hex()}-"
        f"{(f2[6] & 0x0f | 0x40):02x}{f2[7]:02x}-"
        f"{(f2[8] & 0x3f | 0x80):02x}{f2[9]:02x}-"
        f"{f2[10:16].hex()}"
    )

    return {
        "x-ig-android-id":       android_id,
        "x-ig-device-id":        device_id,
        "x-ig-family-device-id": family_id,
    }


def parse_device_info_from_ua(ua: str) -> dict:
    """User-Agent string se structured device_info extract karo."""
    info = {
        "app_version": APP_VERSION,
        "platform": "Android",
        "android_version": "9",
        "api_level": "28",
        "dpi": "240dpi",
        "resolution": "1600x900",
        "manufacturer": "Xiaomi",
        "model": "2203121C",
        "cpu": "qcom",
        "build_number": APP_CODE
    }
    m = re.search(r"Instagram\s+([\d\.]+)\s+Android\s+\((\d+)/([^;]+);\s*([^;]+);\s*([^;]+);\s*([^;]+);\s*([^;]+);\s*([^;]+);\s*([^;]+);\s*([^;]+);\s*(\d+)\)", ua)
    if m:
        info["app_version"] = m.group(1)
        info["api_level"] = m.group(2)
        info["android_version"] = m.group(3)
        info["dpi"] = m.group(4)
        info["resolution"] = m.group(5)
        info["manufacturer"] = m.group(6)
        info["model"] = m.group(7)
        info["device_codename"] = m.group(8)
        info["cpu"] = m.group(9)
        info["locale"] = m.group(10)
        info["build_number"] = m.group(11)
    return info

DEVICE_POOL = []
pool_file = os.path.join(HERE, "device_pool.json")
if os.path.exists(pool_file):
    try:
        with open(pool_file, "r", encoding="utf-8") as f:
            DEVICE_POOL = json.load(f)
    except Exception:
        pass


def get_device_profile_for_user(username: str, locale: str = "en_US") -> dict:
    """
    Bablosoft pool se username ke hisab se consistent real device profile chuno.
    Same username = hamesha same phone model.
    Alag username = alag-alag phone models pool se distribute honge.
    """
    if DEVICE_POOL:
        idx = int(hashlib.sha256(username.lower().encode()).hexdigest(), 16) % len(DEVICE_POOL)
        p = dict(DEVICE_POOL[idx])
    else:
        p = {
            "manufacturer": "Xiaomi",
            "model": "2203121C",
            "device_codename": "marlin",
            "cpu": "qcom",
            "android_version": "9",
            "api_level": "28",
            "resolution": "1600x900",
            "dpi": "240dpi",
            "app_version": APP_VERSION,
            "build_number": APP_CODE,
        }
    p["locale"] = locale
    ua = (
        f"Instagram {p['app_version']} Android "
        f"({p['api_level']}/{p['android_version']}; {p['dpi']}; {p['resolution']}; "
        f"{p['manufacturer']}; {p['model']}; {p['device_codename']}; {p['cpu']}; {p['locale']}; {p['build_number']})"
    )
    p["user_agent"] = ua
    return p


_DEVICE = {}
_PROFILE = {}

_GEO = {
    "timezone_offset": "19800",
    "locale": "en_US",
    "lang": "en-US",
    "country": "IN",
    "proxy": None,
}


COUNTRY_PRESETS = {
    "PH": {
        "timezone_offset": "28800",
        "locale": "en_PH",
        "lang": "en-PH,en;q=0.9",
        "country_name": "Philippines (UTC+8)",
    },
    "US": {
        "timezone_offset": "-25200",
        "locale": "en_US",
        "lang": "en-US,en;q=0.9",
        "country_name": "United States (UTC-7/UTC-5)",
    },
    "US_EST": {
        "timezone_offset": "-18000",
        "locale": "en_US",
        "lang": "en-US,en;q=0.9",
        "country_name": "United States EST (UTC-5)",
    },
    "US_PST": {
        "timezone_offset": "-28800",
        "locale": "en_US",
        "lang": "en-US,en;q=0.9",
        "country_name": "United States PST (UTC-8)",
    },
    "UK": {
        "timezone_offset": "0",
        "locale": "en_GB",
        "lang": "en-GB,en;q=0.9",
        "country_name": "United Kingdom (UTC+0)",
    },
    "IN": {
        "timezone_offset": "19800",
        "locale": "en_US",
        "lang": "en-US",
        "country_name": "India (UTC+5:30)",
    },
}




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
    """Authenticator-app jaisa TOTP code (RFC 6238, SHA1).
    Agar current window khatam hone wali ho to naye code ka wait karta hai."""
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
    """Exact-match substitutions on raw body/header text.
    Per-device version: device IDs bhi replace karta hai.
    """
    text = text.replace(TEMPLATE_USERNAME, username)
    text = text.replace(TEMPLATE_WATERFALL, str(uuid.uuid4()))
    text = text.replace(TEMPLATE_PIGEON, f"UFS-{uuid.uuid4()}-0")
    text = text.replace(f'"aac_init_timestamp":{TEMPLATE_AAC_TS}',
                        f'"aac_init_timestamp":{now_ts()}')
    # 2026 CAA: static template aac ko server-issued fresh aac se override karo
    if _FRESH_AAC:
        text = re.sub(
            r'\{\\?"aac_init_timestamp\\?":\d+,\\?"aacjid\\?":\\?"[^"\\]+\\?",\\?"aaccs\\?":\\?"[^"\\]+\\?"\}',
            lambda m: _FRESH_AAC, text)
    # --- Device fingerprint replace karo (original duck values -> account-specific) ---
    if _DEVICE:
        text = text.replace(TEMPLATE_ANDROID_ID, _DEVICE["x-ig-android-id"])
        text = text.replace(TEMPLATE_DEVICE_ID,  _DEVICE["x-ig-device-id"])
        text = text.replace(TEMPLATE_FAMILY_ID,  _DEVICE["x-ig-family-device-id"])
        tmpl_mid_val = TEMPLATES.get("mobileconfig", {}).get("headers", {}).get("x-mid", "")
        if tmpl_mid_val and _DEVICE.get("x-mid"):
            text = text.replace(tmpl_mid_val, _DEVICE["x-mid"])
    if _GEO and _GEO.get("timezone_offset"):
        tz = str(_GEO["timezone_offset"])
        text = text.replace('"timezone_offset":"19800"', f'"timezone_offset":"{tz}"')
        text = text.replace('"timezone_offset":19800', f'"timezone_offset":{tz}')
        text = text.replace('timezone_offset=19800', f'timezone_offset={tz}')
    if enc_pwd is not None:
        text = re.sub(r"#PWD_INSTAGRAM:4:\d+:[A-Za-z0-9+/=]+", enc_pwd, text)
    if code is not None:
        text = re.sub(r'"code":"\d+"', f'"code":"{code}"', text)
    if ctx is not None:
        text = re.sub(r'"two_step_verification_context":"[^"]*"',
                      f'"two_step_verification_context":"{ctx}"', text)
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
        # --- Per-account device header override ---
        elif kl in ("x-ig-android-id", "x-ig-device-id", "x-ig-family-device-id") and _DEVICE:
            v = _DEVICE[kl]
        elif kl == "x-mid":
            v = _DEVICE.get("x-mid", "")
        # --- Timezone & Geo header override ---
        elif kl == "x-ig-timezone-offset" and _GEO.get("timezone_offset"):
            v = str(_GEO["timezone_offset"])
        elif kl in ("x-ig-app-locale", "x-ig-device-locale", "x-ig-mapped-locale") and _GEO.get("locale"):
            v = _GEO["locale"]
        elif kl == "accept-language" and _GEO.get("lang"):
            v = _GEO["lang"]
        # --- Real Device Pool User-Agent override ---
        elif kl == "user-agent" and _PROFILE.get("user_agent"):
            v = _PROFILE["user_agent"]
        headers[k] = patch_text(v, username, enc_pwd, code, ctx)




    body = t["body"]
    if body and "urlencoded" in headers.get("content-type", ""):
        # pehle decode karo, har form-field par patch lagao, phir re-encode
        pairs = urllib.parse.parse_qsl(body, keep_blank_values=True)
        pairs = [(k, patch_text(v, username, enc_pwd, code, ctx)) for k, v in pairs]
        body = urllib.parse.urlencode(pairs, quote_via=urllib.parse.quote)
    else:
        body = patch_text(body, username, enc_pwd, code, ctx)
    return t["method"], f"https://{t['host']}{t['path']}", headers, body


def find_key(obj, name):
    """Recursively JSON me key dhundo; escaped strings ke andar bhi."""
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
    """send_login response se fresh two_step_verification_context nikalo.
    Response bloks format me hota hai — keys ek array me, values dusre array me
    (parallel arrays), aur multi-layer escaped."""
    try:
        ctx = find_key(json.loads(text), "two_step_verification_context")
        if ctx:
            return ctx
    except Exception:
        pass
    cand = text
    for _ in range(6):
        cand = cand.replace("\\\\", "\\").replace('\\"', '"').replace("\\/", "/")
        # bloks parallel-array layout: keys-array ke baad values-array
        m = re.search(r'two_step_verification_context.{0,400}?'
                      r'bk\.action\.array\.Make,\s*"([A-Za-z0-9+/=_\-]{200,})',
                      cand, re.S)
        if m:
            return m.group(1)
        # fallback: plain key:value JSON layout
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
    """sessionid se www.instagram.com hit karke poori web cookie jar lao
    (csrftoken, rur, datr, ig_did, mid...)."""
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


# ============================================================
# 2026 CAA helpers — AP 2FA flow + response diagnostics
# (instagrapi ki working implementation se port, is tool ke
#  template/device system par adapt kiya gaya)
# ============================================================

AP_2SV_ENTRYPOINT       = "com.bloks.www.ap.two_step_verification.entrypoint_async"
AP_2SV_CODE_ENTRY       = "com.bloks.www.ap.two_step_verification.code_entry"
AP_2SV_CODE_ENTRY_ASYNC = "com.bloks.www.ap.two_step_verification.code_entry_async"
AP_2SV_CHALLENGE_PICKER = "com.bloks.www.ap.two_step_verification.challenge_picker"

_m_bv = re.search(r'bloks_versioning_id=([a-f0-9]{64})',
                  TEMPLATES.get("send_login", {}).get("body", ""))
BLOKS_VER = _m_bv.group(1) if _m_bv else "799db3e387d7a21a19c72918b8698b6cd28a1516ade363792c100ed45a0f9f0b"


def bloks_collect_strings(value, out):
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for c in value.values():
            bloks_collect_strings(c, out)
    elif isinstance(value, list):
        for c in value:
            bloks_collect_strings(c, out)


def bloks_paren_expr(value, start):
    """Ek balanced bloks expression nikalo (quoted strings respect karte hue)."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(value)):
        ch = value[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return value[start:i + 1]
    return ""


def bloks_expr_items(value):
    """Direct operands padho (nested expressions flatten mat karo)."""
    if not (value.startswith("(") and value.endswith(")")):
        return []
    items = []
    dec = json.JSONDecoder()
    i = 1
    while i < len(value) - 1:
        if value[i].isspace():
            i += 1
            continue
        if value[i] == "(":
            it = bloks_paren_expr(value, i)
            if not it:
                return []
        elif value[i] == '"':
            try:
                _, consumed = dec.raw_decode(value[i:])
            except ValueError:
                return []
            it = value[i:i + consumed]
        else:
            m = re.match(r'[^()\s"]+', value[i:])
            if not m:
                return []
            it = m.group()
        items.append(it)
        i += len(it)
    return items


def bloks_extract_context(result, app_id, context_key="context_data"):
    """Bloks response me app_id ke static params map se context literal nikalo.
    2026 format: (f4i (dkc "context_data" ...) (dkc "Q-...." ...)) parallel arrays."""
    try:
        strings = []
        bloks_collect_strings(result, strings)
        anchor = re.compile(re.escape(json.dumps(app_id)))
        app_ref = re.compile(r"(?<![_a-zA-Z0-9])com\.bloks\.[_a-zA-Z0-9.]+")
        for text in strings:
            for found in anchor.finditer(text):
                map_start = text.find("(f4i", found.end())
                if map_start < 0:
                    continue
                nxt = app_ref.search(text, found.end())
                if nxt and nxt.start() < map_start:
                    continue
                expr = bloks_paren_expr(text, map_start)
                if not expr:
                    continue
                while expr:
                    items = bloks_expr_items(expr)
                    if len(items) != 3 or items[0] != "f4i":
                        break
                    keys = bloks_expr_items(items[1])
                    vals = bloks_expr_items(items[2])
                    if keys[:1] != ["dkc"] or vals[:1] != ["dkc"] or len(keys) != len(vals):
                        break
                    expr = ""
                    for k, v in zip(keys[1:], vals[1:]):
                        if not k.startswith('"'):
                            continue
                        name = json.loads(k)
                        if name == context_key:
                            return json.loads(v) if v.startswith('"') else ""
                        if name == "server_params":
                            expr = v
    except Exception:
        pass
    return ""


def bloks_extract_aac(result):
    """process_client_data response se server-issued CAA account-access-context (aac) nikalo."""
    try:
        data = result.get("layout", {}).get("bloks_payload", {}).get("data", [])
        if not isinstance(data, list):
            return ""
        for node in data:
            p = node.get("data") if isinstance(node, dict) else None
            if not isinstance(p, dict) or p.get("key") != "CAA_ACCOUNT_ACCESS_CONTEXT:aac":
                continue
            init = p.get("initial")
            if isinstance(init, str) and init.strip():
                return init.strip()
            lispy = p.get("initial_lispy")
            if isinstance(lispy, str) and lispy:
                qi = lispy.find('"')
                if qi >= 0:
                    try:
                        val, _ = json.JSONDecoder().raw_decode(lispy[qi:])
                        if isinstance(val, str) and val.strip():
                            return val.strip()
                    except ValueError:
                        pass
    except Exception:
        pass
    return ""


def bloks_extract_login_response(result):
    """2FA ke final bloks response me embedded login_response (auth header + cookies) nikalo."""
    try:
        action = result.get("layout", {}).get("bloks_payload", {}).get("action", "")
        if not isinstance(action, str):
            return {}
        from http.cookies import SimpleCookie
        dec = json.JSONDecoder()
        i = 0
        while i < len(action):
            if action[i] != '"':
                i += 1
                continue
            try:
                val, end = dec.raw_decode(action[i:])
            except ValueError:
                i += 1
                continue
            i += max(end, 1)
            if not isinstance(val, str) or "login_response" not in val:
                continue
            try:
                raw = json.loads(val)
                login_response = json.loads(raw["login_response"])
                headers = json.loads(raw.get("headers") or "{}")
            except (KeyError, TypeError, ValueError):
                continue
            raw_cookies = raw.get("cookies") or ""
            ck = SimpleCookie()
            ck.load(raw_cookies.replace("Set-Cookie: ", ""))
            return {
                "login_response": login_response,
                "headers": headers,
                "cookies": {n: m.value for n, m in ck.items()},
            }
    except Exception:
        pass
    return {}


# ---------- Per-account COOLDOWN LOCK (risk-escalation prevention) ----------
# GENERIC_ERROR/FALLBACK/429 ke baad account automatic lock ho jata hai:
# beech me retry karne se IG ka risk-flag strong hota hai (2026-10-22 lesson:
# subah 2FA challenge -> repeated attempts -> shaam ko GENERIC_ERROR block).
COOLDOWN_FILE = os.path.join(HERE, "cooldowns.json")
COOLDOWN_HOURS = {"GENERIC_ERROR": 12, "FALLBACK": 1, "THROTTLED": 0.75}

def cooldown_load():
    try:
        with open(COOLDOWN_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def cooldown_save(data):
    try:
        with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        print("cooldowns.json save fail:", e)
        return False

def cooldown_set(username, reason):
    hrs = COOLDOWN_HOURS.get(reason)
    if not hrs:
        return
    data = cooldown_load()
    data[username.lower()] = {"reason": reason,
                              "until": time.time() + hrs * 3600,
                              "set_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if cooldown_save(data):
        print(f">> COOLDOWN LOCK: '{username}' ab {hrs:g} ghante locked ({reason}).")
        print("   Isse pehle retry kiya to IG ka risk-flag aur strong hoga.")

def cooldown_clear(username):
    data = cooldown_load()
    if username.lower() in data:
        del data[username.lower()]
        cooldown_save(data)

def cooldown_check(username, force=False):
    ent = cooldown_load().get(username.lower())
    if not ent:
        return
    left = ent.get("until", 0) - time.time()
    if left <= 0:
        cooldown_clear(username)
        return
    mins = int(left // 60) + 1
    print(f"\n>> COOLDOWN ACTIVE: '{username}' ko pichhli run me {ent.get('reason', '?')} mila tha.")
    print(f"   Lock khatam hone me ~{mins} minute baaki hain. Beech me retry = risk-flag refresh.")
    if force:
        print("   --force mila hai -> lock IGNORE (recommended NAHI; sirf ek attempt karna).")
        return
    print("   Zaroori ho to --force lagao (panel me Force checkbox) — warna wait karo.")
    raise SystemExit(3)


def diagnose_login_response(text):
    """send_login response ka sahi matlab batao (2026 CAA format).
    Order important hai: disabled-account response me bhi challenge_picker
    screen leftover hoti hai — isliye DISABLED sabse pehle check hota hai."""
    tl = text.lower()
    if "no longer connected to an account" in tl or ("recover your account" in tl and "account_recovery" in tl):
        return "DISABLED"
    if "can't find an account with" in tl or "can\\'t find an account" in tl:
        return "NOT_FOUND"
    if ("the password you entered is incorrect" in tl
            or "incorrect password" in tl
            or "first_password_failure" in tl):
        return "WRONG_PASSWORD"
    if "checkpoint" in tl and "challenge" in tl:
        return "CHALLENGE"
    if AP_2SV_ENTRYPOINT in text:
        return "2FA_AP"
    if AP_2SV_CHALLENGE_PICKER in text:
        return "2FA_AP"
    if ("two_step_verification_context" in tl
            or "two_step_verification.entrypoint" in text
            or "error_2fa_bloks" in tl):
        return "2FA_OLD"
    # IG ka explicit generic error dialog ("Unable to log in / An unexpected
    # error occurred") = server-side RISK rejection. has_identification_error:
    # false is response me prove karta hai ki password galat nahi hai.
    if ("error_generic" in tl or "generic_error_dialog" in tl
            or "an unexpected error occurred" in tl):
        return "GENERIC_ERROR"
    # FALLBACK sirf tab real hai jab gs flag actually true set ho — ye key
    # lagbhag HAR CAA response me state-variable (initial:false) ke roop me
    # hoti hai, isliye substring match false-positive deta tha.
    if re.search(r'fallback_triggered"[^}]*?"initial"\s*:\s*true', text):
        return "FALLBACK"
    return "UNKNOWN"

def bloks_post(s, kind, name, params, username):
    """bloks/apps/ ya bloks/async_action/ request — 2026 CAA payload format,
    tool ke process_client_data template headers ke saath (device/geo patched)."""
    _, _, headers, _ = build_request("process_client_data", username)
    headers = dict(headers)
    for k in list(headers):
        if k.lower() in ("x-fb-friendly-name", "content-length"):
            del headers[k]
    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    if kind == "async_action":
        headers["X-FB-Friendly-Name"] = f"IgApi: bloks/async_action/{name}/"
    body = {
        "params": json.dumps(params, separators=(",", ":")),
        "_uuid": _DEVICE["x-ig-device-id"],
        "bk_client_context": json.dumps({"bloks_version": BLOKS_VER, "styles_id": "instagram"}),
        "bloks_versioning_id": BLOKS_VER,
    }
    url = f"{BASE}/api/v1/bloks/{kind}/{name}/"
    r = s.post(url, headers=headers, data=body, timeout=30)
    print(f"[2fa {name.split('.')[-1][:24]:24s}] {r.status_code} {len(r.content)}B")
    if r.headers.get("ig-set-x-mid"):
        global _SERVER_MID
        _SERVER_MID = r.headers["ig-set-x-mid"]
        if _DEVICE:
            _DEVICE["x-mid"] = _SERVER_MID   # header/payload consistency
    return r


def ap_2fa_resolve(s, resp_text, username, totp_secret):
    """2026 CAA AP-2FA flow: entrypoint_async -> code_entry -> code_entry_async (TOTP).
    Final response me embedded login_response (IG-Set-Authorization + cookies) hota hai."""
    try:
        j = json.loads(resp_text)
    except ValueError:
        return None
    ctx = bloks_extract_context(j, AP_2SV_ENTRYPOINT)
    if not ctx:
        ctx = bloks_extract_context(j, AP_2SV_CHALLENGE_PICKER)
    if not ctx:
        print("AP-2FA: context_data nahi mila — flow aage nahi badh sakta")
        return None
    print(f"AP-2FA: context_data mila ({len(ctx)} chars)")
    dev_android = _DEVICE["x-ig-android-id"]
    dev_uuid = _DEVICE["x-ig-device-id"]
    dev_family = _DEVICE["x-ig-family-device-id"]
    mid = _SERVER_MID or _DEVICE.get("x-mid", "")
    aac = _FRESH_AAC or ""

    # 1) entrypoint_async — challenge kholo
    r1 = bloks_post(s, "async_action", AP_2SV_ENTRYPOINT, {
        "client_input_params": {
            "auth_secure_device_id": "",
            "accounts_list": [],
            "has_whatsapp_installed": 0,
            "family_device_id": dev_family,
            "machine_id": mid,
        },
        "server_params": {
            "use_open_instead_of_push": 0,
            "context_data": ctx,
            "INTERNAL__latency_qpl_marker_id": 36707139,
            "INTERNAL__latency_qpl_instance_id": int(time.time() * 1000),
            "device_id": dev_uuid,
            "use_close_instead_of_back": 0,
        },
    }, username)
    try:
        j1 = r1.json()
    except ValueError:
        return None
    ctx2 = bloks_extract_context(j1, AP_2SV_CODE_ENTRY)
    if not ctx2:
        print("AP-2FA: code_entry context nahi mila (entrypoint response se)")
        return None

    # 2) code_entry — code input screen kholo
    r2 = bloks_post(s, "apps", AP_2SV_CODE_ENTRY, {
        "client_input_params": {"aac": aac},
        "server_params": {
            "context_data": ctx2,
            "show_close_button": 0,
            "device_id": dev_uuid,
            "INTERNAL_INFRA_screen_id": "generic_code_entry",
            "is_dismissable": 1,
        },
    }, username)
    try:
        j2 = r2.json()
    except ValueError:
        return None
    ctx3 = bloks_extract_context(j2, AP_2SV_CODE_ENTRY_ASYNC)
    if not ctx3:
        print("AP-2FA: code_entry_async context nahi mila (code_entry response se)")
        return None

    # 3) TOTP code submit karo
    if totp_secret:
        code = totp_code(totp_secret)
        print(f">> Auto TOTP code: {code}")
    else:
        code = input("2FA code (authenticator app se): ").strip()
    r3 = bloks_post(s, "async_action", AP_2SV_CODE_ENTRY_ASYNC, {
        "client_input_params": {
            "auth_secure_device_id": "",
            "aac": aac,
            "code": str(code),
            "family_device_id": dev_family,
            "device_id": dev_android,
            "machine_id": mid,
        },
        "server_params": {
            "context_data": ctx3,
            "INTERNAL__latency_qpl_marker_id": 36707139,
            "INTERNAL__latency_qpl_instance_id": int(time.time() * 1000),
            "device_id": dev_uuid,
        },
    }, username)
    return r3


def bloks_2fa_method_select(s, ctx, username):
    """Non-AP bloks 2FA: method_picker kholo + 'totp' select karo (2026 flow).
    instagrapi 3.1 me verified: entrypoint ke baad ye 2 steps zaroori hain,
    warna verify_code bina method-selection ke fail hota hai."""
    dev_android = _DEVICE["x-ig-android-id"]
    r1 = bloks_post(s, "apps", "com.bloks.www.two_step_verification.method_picker", {
        "client_input_params": {"is_whatsapp_installed": 0},
        "server_params": {
            "should_fallback_to_sms": 0,
            "device_id": dev_android,
            "two_step_verification_context": ctx,
            "flow_source": "two_factor_login",
        },
    }, username)
    r2 = bloks_post(s, "async_action",
                    "com.bloks.www.two_step_verification.method_picker.navigation.async", {
        "client_input_params": {
            "selected_method": "totp",
            "cloud_trust_token": None,
            "network_bssid": None,
        },
        "server_params": {
            "should_fallback_to_sms": 0,
            "device_id": dev_android,
            "spectra_reg_login_data": None,
            "two_step_verification_context": ctx,
            "flow_source": "two_factor_login",
        },
    }, username)
    return r2


def extract_2sv_context_v2(text):
    """2026 format: two_step_verification_context structured parse se nikalo.
    Cascade: (1) plain JSON recursive search, (2) bloks parallel-array parse
    har two_step_verification app-anchor ke liye, (3) purana regex fallback."""
    try:
        j = json.loads(text)
    except ValueError:
        j = None
    if j is not None:
        v = find_key(j, "two_step_verification_context")
        if v and len(v) > 20:
            return v
        anchors = sorted(set(re.findall(
            r'com\.bloks\.www\.(?:ap\.)?two_step_verification\.[A-Za-z0-9_.]+', text)))
        anchors.sort(key=lambda a: 0 if "entrypoint" in a else 1)
        for app in anchors:
            for key in ("two_step_verification_context", "context_data"):
                v = bloks_extract_context(j, app, key)
                if v and len(v) > 20:
                    return v
    return extract_2sv_context(text)


def bloks_2fa_old_resolve(s, ctx, username, totp_secret):
    """2026 non-AP bloks 2FA flow (instagrapi 3.1 verified sequence):
    entrypoint -> method_picker -> select_method(totp) -> verify_code.async.
    Final response me embedded login_response (auth + cookies) hota hai."""
    dev_android = _DEVICE["x-ig-android-id"]
    dev_family = _DEVICE["x-ig-family-device-id"]
    mid = _SERVER_MID or _DEVICE.get("x-mid", "")

    bloks_post(s, "apps", "com.bloks.www.two_step_verification.entrypoint", {
        "client_input_params": {
            "device_id": dev_android,
            "is_whatsapp_installed": 0,
            "machine_id": mid,
        },
        "server_params": {
            "should_fallback_to_sms": 0,
            "family_device_id": dev_family,
            "device_id": dev_android,
            "two_step_verification_context": ctx,
            "flow_source": "two_factor_login",
        },
    }, username)

    bloks_post(s, "apps", "com.bloks.www.two_step_verification.method_picker", {
        "client_input_params": {"is_whatsapp_installed": 0},
        "server_params": {
            "should_fallback_to_sms": 0,
            "device_id": dev_android,
            "two_step_verification_context": ctx,
            "flow_source": "two_factor_login",
        },
    }, username)

    bloks_post(s, "async_action",
               "com.bloks.www.two_step_verification.method_picker.navigation.async", {
        "client_input_params": {
            "selected_method": "totp",
            "cloud_trust_token": None,
            "network_bssid": None,
        },
        "server_params": {
            "should_fallback_to_sms": 0,
            "device_id": dev_android,
            "spectra_reg_login_data": None,
            "two_step_verification_context": ctx,
            "flow_source": "two_factor_login",
        },
    }, username)

    if totp_secret:
        code = totp_code(totp_secret)
        print(f">> Auto TOTP code: {code}")
    else:
        code = input("2FA code (authenticator app se): ").strip()

    r4 = bloks_post(s, "async_action",
                    "com.bloks.www.two_step_verification.verify_code.async", {
        "client_input_params": {
            "auth_secure_device_id": "",
            "block_store_machine_id": "",
            "code": str(code),
            "should_trust_device": 1,
            "family_device_id": dev_family,
            "device_id": dev_android,
            "cloud_trust_token": None,
            "network_bssid": None,
            "machine_id": mid,
        },
        "server_params": {
            "should_fallback_to_sms": 0,
            "device_id": dev_android,
            "spectra_reg_login_data": None,
            "challenge": "totp",
            "two_step_verification_context": ctx,
            "flow_source": "two_factor_login",
        },
    }, username)
    return r4


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


def detect_country_from_proxy(proxy):
    """Proxy URL se exit country parse karo — IPRoyal (_country-XX, old
    actionapp tool wala gateway) aur DataImpulse (cr.xx) dono formats.
    Timezone/locale ko proxy exit se match rakhna risk-signal bachata hai."""
    if not proxy:
        return None
    m = re.search(r"_country-([a-zA-Z]{2})", proxy)
    if not m:
        m = re.search(r"[.;_]cr\.([a-zA-Z]{2})", proxy)
    return m.group(1).upper() if m else None

COUNTRY_ALIASES = {"GB": "UK", "US": "US_EST"}



# ---------------------------------------------------------------- legacy login
def legacy_login(username: str, password: str, totp_secret: str = None) -> dict:
    """
    PATH A — Instagram legacy login endpoint (proxy-safe).

    CRITICAL: uses plain requests.Session (NO curl_cffi / TLS impersonation).
    Impersonated TLS fingerprints get 429 on legacy endpoints too;
    plain Python TLS succeeds. A/B tested and confirmed Aug 2026.

    NOTE: Use a FRESH proxy exit IP for each login attempt.
    Proxy IPs burn quickly after repeated attempts; max 1 login per session.

    Returns dict with 'authorization' + 'cookies' on success, or empty dict on failure.
    """
    # Plain requests.Session — intentionally not curl_cffi
    leg = requests.Session()
    if _GEO.get("proxy"):
        leg.proxies = {
            "http":  _GEO["proxy"],
            "https": _GEO["proxy"],
        }

    # --- Build base Android headers (same values used by mobileconfig template) ---
    tmpl_hdrs = dict(TEMPLATES["mobileconfig"]["headers"])
    base_hdrs = {}
    for k, v in tmpl_hdrs.items():
        kl = k.lower()
        if kl in ("x-ig-android-id", "x-ig-device-id", "x-ig-family-device-id") and _DEVICE:
            v = _DEVICE[kl]
        elif kl == "x-mid":
            v = _DEVICE.get("x-mid", "")
        elif kl == "x-ig-timezone-offset" and _GEO.get("timezone_offset"):
            v = str(_GEO["timezone_offset"])
        elif kl in ("x-ig-app-locale", "x-ig-device-locale", "x-ig-mapped-locale") and _GEO.get("locale"):
            v = _GEO["locale"]
        elif kl == "accept-language" and _GEO.get("lang"):
            v = _GEO["lang"]
        elif kl == "user-agent" and _PROFILE.get("user_agent"):
            v = _PROFILE["user_agent"]
        elif kl == "x-pigeon-rawclienttime":
            v = now_rawclienttime()
        elif kl == "x-fb-conn-uuid-client":
            v = uuid.uuid4().hex
        base_hdrs[k] = v
    # Remove request-body specific headers for GET calls
    get_hdrs = {k: v for k, v in base_hdrs.items()
                if k.lower() not in ("content-type", "content-length")}

    # --- Step 1: GET qe/sync to fetch encryption key ---
    try:
        r_sync = leg.get(
            f"{BASE}/api/v1/qe/sync/",
            headers=get_hdrs,
            timeout=30
        )
        key_id = int(r_sync.headers.get("ig-set-password-encryption-key-id", "0") or "0")
        pub_key = r_sync.headers.get("ig-set-password-encryption-pub-key", "")
        print(f"[legacy qe/sync           ] {r_sync.status_code} key_id={key_id}")
    except Exception as e:
        print(f"[legacy qe/sync           ] ERROR: {e}")
        return {}

    if not pub_key:
        print("[legacy] qe/sync se encryption key nahi mili — legacy path abort.")
        return {}

    # --- Step 2: Encrypt password (#PWD_INSTAGRAM:4) ---
    enc_pwd = password_encrypt(password, key_id, pub_key)

    # --- Step 3: POST /api/v1/accounts/login/ ---
    # jazoest = "2" + sum of ord() of each char in username
    jazoest = "2" + str(sum(ord(c) for c in username))
    phone_id = str(uuid.uuid4())
    adid     = str(uuid.uuid4())
    mid      = _DEVICE.get("x-mid", "") or tmpl_hdrs.get("x-mid", "") or tmpl_hdrs.get("X-MID", "")
    android_id = _DEVICE.get("x-ig-android-id", TEMPLATE_ANDROID_ID)

    login_payload = {
        "jazoest":       jazoest,
        "phone_id":      phone_id,
        "enc_password":  enc_pwd,
        "username":      username,
        "adid":          adid,
        "device_id":     android_id,
        "google_tokens": "[]",
        "login_attempt_count": "1",
        "country_codes": '[{"country_code":"1","source":["default"]}]',
        "machine_id":    mid,
    }

    # signed_body = "SIGNATURE." + URL-encoded compact JSON
    payload_json = json.dumps(login_payload, separators=(",", ":"))
    signed_body  = "SIGNATURE." + urllib.parse.quote(payload_json, safe="")

    post_hdrs = dict(base_hdrs)
    post_hdrs["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8"

    try:
        r_login = leg.post(
            f"{BASE}/api/v1/accounts/login/",
            data=f"signed_body={signed_body}",
            headers=post_hdrs,
            timeout=30
        )
        print(f"[legacy login             ] {r_login.status_code} {len(r_login.content)}B")
    except Exception as e:
        print(f"[legacy login             ] ERROR: {e}")
        return {}

    # --- Step 4: Handle response ---
    login_text = r_login.text
    try:
        login_json = r_login.json()
    except Exception:
        login_json = {}

    auth_token = None
    result_cookies = {}

    # SUCCESS: logged_in_user present
    if r_login.status_code == 200 and login_json.get("logged_in_user"):
        auth_token = r_login.headers.get("ig-set-authorization") or r_login.headers.get("Authorization")
        creds = extract_credentials(login_text)
        auth_token = auth_token or creds.get("authorization")
        result_cookies = creds.get("cookies", {})

    # 2FA required
    elif r_login.status_code == 400 and login_json.get("two_factor_required"):
        print("\n>> 2FA (two-step verification) required!")
        tf_info = login_json.get("two_factor_info", {})
        two_factor_identifier = tf_info.get("two_factor_identifier", "")
        if not two_factor_identifier:
            print("[legacy] two_factor_identifier nahi mila — abort.")
            return {}

        # TOTP code generate karo
        secret = totp_secret or os.environ.get("IG_TOTP_SECRET")
        if secret:
            code = totp_code(secret)
            print(f">> Auto TOTP code: {code}")
        else:
            code = input("2FA code (authenticator app se): ").strip()

        # POST /api/v1/accounts/two_factor_login/
        tf_payload = {
            "username":             username,
            "verification_code":    code,
            "two_factor_identifier": two_factor_identifier,
            "trust_this_device":    "1",
            "verification_method":  "3",
            "device_id":            android_id,
        }
        tf_json_str  = json.dumps(tf_payload, separators=(",", ":"))
        tf_signed    = "SIGNATURE." + urllib.parse.quote(tf_json_str, safe="")

        try:
            r_2fa = leg.post(
                f"{BASE}/api/v1/accounts/two_factor_login/",
                data=f"signed_body={tf_signed}",
                headers=post_hdrs,
                timeout=30
            )
            print(f"[legacy two_factor_login  ] {r_2fa.status_code} {len(r_2fa.content)}B")
        except Exception as e:
            print(f"[legacy two_factor_login  ] ERROR: {e}")
            return {}

        try:
            tf_resp_json = r_2fa.json()
        except Exception:
            tf_resp_json = {}

        if r_2fa.status_code == 200 and tf_resp_json.get("logged_in_user"):
            auth_token = r_2fa.headers.get("ig-set-authorization") or r_2fa.headers.get("Authorization")
            creds2 = extract_credentials(r_2fa.text)
            auth_token = auth_token or creds2.get("authorization")
            result_cookies = creds2.get("cookies", {})
            # Overwrite r_login ref so Step 5 rur extraction works correctly
            login_text = r_2fa.text
            r_login    = r_2fa
        else:
            print("[legacy] 2FA verification failed.")
            print(r_2fa.text[:500])
            return {}
    else:
        # e.g. 429 or other failure
        print(f"[legacy] Login failed — status {r_login.status_code}")
        if r_login.status_code != 429:
            print(login_text[:500])
        if "needs_upgrade" in login_text:
            print("[legacy note] Legacy /accounts/login/ endpoint deprecated hai — har app")
            print("              version par needs_upgrade deta hai. PATH B (bloks CAA) hi kaam karta hai.")
        return {}

    if not auth_token:
        print("[legacy] Authorization token nahi mila — abort.")
        return {}

    # --- Step 5: Derive cookies from Bearer token + rur ---
    derived = derive_cookies_from_token(auth_token)
    for k, v in derived.items():
        result_cookies.setdefault(k, v)
    # Server-issued mid extraction from Set-Cookie / session cookies
    server_mid = (
        r_login.cookies.get("mid")
        or leg.cookies.get("mid")
        or result_cookies.get("mid")
    )
    if server_mid:
        result_cookies["mid"] = server_mid

    server_rur = (r_login.headers.get("ig-set-ig-u-rur")
                  or r_login.headers.get("ig-set-rur")
                  or derived.get("rur") or "ODN")
    result_cookies["rur"] = server_rur

    return {
        "authorization": auth_token,
        "cookies":       result_cookies,
        "rur":           server_rur,
        "session":       leg,          # reuse same session for verify call
    }


# --------------------------------------------------------------------- main
def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--username")
    ap.add_argument("--password")
    ap.add_argument("--totp-secret",
                    help="2FA authenticator ki base32 secret key — OTP khud banega")
    ap.add_argument("--country", default=None,
                    help="Country preset (e.g. PH for Philippines UTC+8, US_EST, US_PST, UK, IN)")
    ap.add_argument("--proxy",
                    help="Proxy URL (e.g. http://user:pass@host:port or socks5://host:port)")
    ap.add_argument("--timezone-offset",
                    help="Custom timezone offset in seconds (e.g. 28800 for Philippines UTC+8)")
    ap.add_argument("--output",
                    help="Custom JSON filename for saving cookies")
    ap.add_argument("--web-cookies", action="store_true",
                    help="OPT-IN: www.instagram.com se web cookie jar (csrftoken "
                         "wagera) bhi lao. Default OFF — app session ko web surface "
                         "par mix karne se account flag ho sakta hai.")
    ap.add_argument("--force", action="store_true",
                    help="cooldown lock ignore karo (recommended nahi)")
    ap.add_argument("--try-legacy", action="store_true",
                    help="PATH A legacy /accounts/login/ try karo (DEFAULT OFF — endpoint "
                         "deprecated hai, har version pe needs_upgrade deta hai; 2 extra "
                         "requests IG pe jaati hain)")
    ap.add_argument("--tls", choices=["auto", "curl", "requests"], default="auto",
                    help="TLS engine: auto = curl_cffi installed ho to uTLS (HTTP/2 + "
                         "TLS1.3, recommended); curl = force uTLS; requests = classic HTTP/1.1")
    ap.add_argument("--app-profile", choices=["449", "451", "448"], default=None,
                    help="app identity: 449=DEFAULT (consistent — templates ka bloks "
                         "hash 449 ka, instagrapi/instagram-cli Oct 2026 bhi 449, "
                         "Pixel 8 Pro device auto), 451=experimental, 448=purana")
    args = ap.parse_args()
    username = args.username or input("Username: ").strip()
    cooldown_check(username, args.force)
    apply_app_profile(args.app_profile)
    password = args.password or input("Password: ").strip()

    # --- Per-account unique device fingerprint generate karo ---
    global _DEVICE, _GEO, _PROFILE, _FRESH_AAC, _SERVER_MID
    _DEVICE = make_device_fingerprint(username)


    country_key = (args.country or "").upper()
    if country_key in ("", "AUTO"):
        _pc = detect_country_from_proxy(args.proxy)
        if _pc:
            country_key = _pc
            print(f"[geo] proxy URL se exit country detect hui: {_pc}")
        else:
            country_key = "IN"
    country_key = COUNTRY_ALIASES.get(country_key, country_key)
    if country_key in COUNTRY_PRESETS:
        _GEO.update(COUNTRY_PRESETS[country_key])
    if args.timezone_offset:
        _GEO["timezone_offset"] = str(args.timezone_offset)
    if args.proxy:
        _GEO["proxy"] = format_proxy_url(args.proxy)


    _PROFILE = get_device_profile_for_user(username, _GEO["locale"])

    print(f"\n[device] model        : {_PROFILE['manufacturer']} {_PROFILE['model']} (Android {_PROFILE['android_version']})")
    print(f"[device] screen/dpi   : {_PROFILE['resolution']} @ {_PROFILE['dpi']} (CPU: {_PROFILE['cpu']})")
    print(f"[device] android-id   : {_DEVICE['x-ig-android-id']}")
    print(f"[device] device-id    : {_DEVICE['x-ig-device-id']}")
    print(f"[device] family-id    : {_DEVICE['x-ig-family-device-id']}")
    # --- FIX O: ek single web call se fresh mid (old-flow parity) ---
    _wm, _wst = capture_web_mid(_GEO.get("proxy"))
    if _wm:
        _DEVICE["x-mid"] = _wm
    print(f"[device] machine-id (mid): {_DEVICE.get('x-mid', 'N/A')}")
    print(f"[geo] country         : {_GEO.get('country_name', country_key)}")
    print(f"[geo] timezone offset : {_GEO['timezone_offset']}s")
    print(f"[geo] locale / lang   : {_GEO['locale']} / {_GEO['lang']}")
    if _GEO.get("proxy"):
        print(f"[geo] proxy           : {_GEO['proxy']}")
    print()


    # =========================================================
    # PATH A: Legacy login (proxy-safe, plain TLS)
    # Ye endpoint bloks ke 429 proxy-gate se bahar hai.
    # Plain requests.Session use karo — curl_cffi se 429 milta hai yahan bhi.
    # NOTE: FRESH proxy session/exit IP use karo; burn hoti hain quickly.
    # =========================================================
    # FIX P: PATH A DEFAULT OFF — legacy /accounts/login/ endpoint deprecated hai
    # (har app version pe needs_upgrade). Pehle har attempt pe 2 faaltu requests
    # (legacy qe/sync + legacy login) IG pe jaati thi. Ab seedha PATH B (bloks CAA)
    # — instagrapi/aiograpi bhi legacy try nahi karte. Wapas chahiye: --try-legacy
    if args.try_legacy:
        print("[PATH A] Legacy login try kar rahe hain... (--try-legacy flag on)")
        leg_result = legacy_login(username, password, args.totp_secret)
    else:
        leg_result = {}
        print("[PATH B] Direct bloks CAA flow — legacy endpoint deprecated hai")
        print("         (needs_upgrade har version pe); PATH A ki 2 extra API calls SKIP.")

    if leg_result.get("authorization"):
        # Legacy path successful
        print("[PATH A] SUCCESS — legacy login kaam kiya.")
        creds = {
            "authorization": leg_result["authorization"],
            "cookies":       leg_result["cookies"],
        }
        # Use the same session that legacy_login() built (already has proxy set)
        s = leg_result["session"]
        # r is needed later for rur extraction — create a dummy object with headers
        class _FakeResp:
            headers = {}
            status_code = 200
        r = _FakeResp()
        r.headers["ig-set-ig-u-rur"] = leg_result.get("rur", "ODN")

    else:
        # =========================================================
        # PATH B: Existing bloks flow (FALLBACK — clean IPs only)
        # Keep this path exactly as it was — do NOT modify.
        # =========================================================
        if args.try_legacy:
            print("[PATH A] Legacy login failed. [PATH B] Bloks flow fallback...")

        s = requests.Session()
        if _GEO.get("proxy"):
            s.proxies = {
                "http": _GEO["proxy"],
                "https": _GEO["proxy"],
            }
        mount_tls_transport(s, args.tls)

        def send(name, enc_pwd=None, code=None, ctx=None):
            method, url, headers, body = build_request(name, username, enc_pwd, code, ctx)
            if _USDID["registered"]:
                headers["x-meta-usdid"] = usdid_header()
            if name == "send_login":
                if _ATTEST_NONCES[0]:
                    headers["x-ig-attest-params"] = json.dumps(
                        {"attestation": [{"version": 2, "type": "keystore", "errors": [-1013],
                                          "challenge_nonce": _ATTEST_NONCES[0],
                                          "signed_nonce": "", "key_hash": ""}]},
                        separators=(",", ":"))
                elif "x-ig-attest-params" in headers:
                    headers.pop("x-ig-attest-params")
                    print("[attest] fresh nonce nahi mila — STALE attest header hata diya")
            r = s.request(method, url, headers=headers, data=body.encode() if body else None,
                          timeout=60 if name == "send_login" else 30)
            print(f"[{name:22s}] {r.status_code} {len(r.content)}B")
            time.sleep(1.0 + (int(time.time() * 1000) % 1200) / 1000.0)  # pacing — edge 429 se bachne ke liye
            return r

        # 1) mobileconfig
        send("mobileconfig")
        # 1.5) USDID registration — instagrapi 3.x isko CAA preflight se PEHLE karta hai
        try:
            _, _u_url, _u_hdrs, _ = build_request("mobileconfig", username)
            usdid_register(s, _u_hdrs, _u_hdrs.get("x-ig-app-id", "567067343352427"),
                           _DEVICE.get("x-ig-family-device-id", ""))
        except Exception as e:
            print("[usdid] skip:", e)
        # 2) attestation — FRESH challenge_nonce capture karo (stale September
        #    nonce template me tha = bada trust-flag; ab fresh hi jayega)
        _ATTEST_NONCES = ("", "")
        try:
            r_att = send("attestation")
            try:
                _aj = r_att.json()
                _cn = str(_aj.get("challenge_nonce") or "")
                if _cn:
                    _ATTEST_NONCES = (_cn, str(_aj.get("key_nonce") or ""))
                    print(f"[attest] fresh challenge_nonce captured ({len(_cn)} chars)")
            except ValueError:
                pass
        except Exception as e:
            print("attestation skip:", e)
        # 3) public key for password encryption
        _, url, headers, _ = build_request("mobileconfig", username)
        r = s.get(f"{BASE}/api/v1/qe/sync/", headers=headers, timeout=30)
        key_id = int(r.headers.get("ig-set-password-encryption-key-id", "0"))
        pub_key = r.headers.get("ig-set-password-encryption-pub-key", "")
        if not pub_key:
            raise SystemExit("qe/sync se public key nahi mili — network/IP issue?")
        enc_pwd = password_encrypt(password, key_id, pub_key)

        # 4-7) pre-login bloks sequence
        r_pcd = send("process_client_data")
        try:
            _FRESH_AAC = bloks_extract_aac(r_pcd.json())
        except ValueError:
            _FRESH_AAC = ""
        if _FRESH_AAC:
            print(f"[aac] fresh server-issued aac captured ({len(_FRESH_AAC)} chars)")
        send("youthreg")
        send("phone_prefill")
        send("oauth_token_fetch")

        # 8) actual login
        try:
            r = send("send_login", enc_pwd=enc_pwd)
        except requests.exceptions.RequestException as e:
            print(f"\n>> send_login complete nahi hua: {type(e).__name__}")
            print("   IG is account par temporary cooldown laga raha hai (request")
            print("   stall/drop hui). Aaj is username par bahut attempts ho chuke —")
            print("   har retry cooldown reset/lamba karti hai.")
            print("   => 45-60 minute bilkul wait karo, phir SIRF EK baar chalao.")
            raise SystemExit(3)
        if r.status_code == 429:
            print("\n>> send_login par 429 (rate-limit) — ye proxy exit IP abhi IG se")
            print("   throttled hai (credentials evaluate bhi nahi hue). Naya STICKY")
            print("   session banao: DataImpulse me ';sessid.<random>' username me")
            print("   add karne se fresh IP milti hai, phir dobara chalao.")
            cooldown_set(username, "THROTTLED")
            raise SystemExit(3)
        _SERVER_MID = r.headers.get("ig-set-x-mid") or _SERVER_MID
        if _SERVER_MID:
            _DEVICE["x-mid"] = _SERVER_MID   # header/payload consistency
        text = r.text
        creds = extract_credentials(text)

        # 9) response diagnosis + 2FA handling (2026 CAA format)
        if not creds["authorization"]:
            diag = diagnose_login_response(text)
            if diag == "DISABLED":
                print("\n" + "=" * 64)
                print("ACCOUNT RECOVERY SCREEN (disabled/deleted YA IP-escalation)")
                print("Instagram ka jawab: 'It looks like that login info is no")
                print("longer connected to an account' + account-recovery funnel.")
                print("=> Ya to account band/delete ho chuka hai, YA is proxy IP se")
                print("   repeated login failures ki wajah se recovery funnel escalate")
                print("   hua hai. Kisi DOOSRE fresh STICKY proxy se ek baar retry")
                print("   karo — wahan 'Incorrect password' ya 2FA dikhe to account")
                print("   zinda hai (password/2FA issue hai, account band nahi).")
                print("=" * 64)
                raise SystemExit(2)
            if diag == "NOT_FOUND":
                print("\n" + "=" * 64)
                print("USERNAME NOT FOUND")
                print("Instagram: 'We can't find an account with ...' + signup funnel.")
                print("=> Username typo check karo, ya account rename ho chuka hai.")
                print("=" * 64)
                raise SystemExit(2)
            if diag == "WRONG_PASSWORD":
                print("\nWRONG PASSWORD — username sahi hai, password galat.")
                raise SystemExit(2)
            if diag == "CHALLENGE":
                print("\nCHECKPOINT/CHALLENGE — account ko manual verification chahiye")
                print("(browser me www.instagram.com/challenge khol kar checkpoint complete karo).")
                raise SystemExit(2)

            if diag == "2FA_AP":
                print("\n>> 2FA required (2026 CAA AP flow: entrypoint_async -> code_entry -> submit)")
                secret = args.totp_secret or os.environ.get("IG_TOTP_SECRET")
                r3 = ap_2fa_resolve(s, text, username, secret)
                if r3 is not None:
                    r = r3
                    text = r3.text
                    embedded = {}
                    try:
                        embedded = bloks_extract_login_response(r3.json())
                    except ValueError:
                        pass
                    hdrs = embedded.get("headers") or {}
                    auth = (hdrs.get("IG-Set-Authorization")
                            or hdrs.get("ig-set-authorization"))
                    if auth or (embedded.get("cookies") or {}).get("sessionid"):
                        creds = {"authorization": auth,
                                 "cookies": dict(embedded.get("cookies") or {})}
                    else:
                        creds = extract_credentials(text)
                    if not creds["authorization"] and not creds["cookies"]:
                        d2 = diagnose_login_response(text)
                        print(f"\n2FA ke baad credentials nahi mile (diag={d2}).")
                        print("Response snippet:", text[:800])
                        raise SystemExit(1)

            elif diag == "2FA_OLD" or (diag == "UNKNOWN" and "two_step_verification" in text):
                # 2026 non-AP bloks 2FA flow (instagrapi 3.1 verified):
                # entrypoint -> method_picker -> select_method(totp) -> verify_code.async
                print("\n>> 2FA (two-step verification) required! [2026 bloks 2SV flow]")
                ctx = extract_2sv_context_v2(text)
                if not ctx:
                    print("WARN: 2SV context is response format me nahi mila.")
                    try:
                        with open("debug_2fa_response.json", "w", encoding="utf-8") as df:
                            df.write(text)
                        print("      Poora send_login response 'debug_2fa_response.json' me")
                        print("      save ho gaya — uska content share karo, extraction fix hogi.")
                    except OSError as e:
                        print("      debug dump fail:", e)
                    raise SystemExit(1)
                print(f">> 2SV context mila ({len(ctx)} chars)")
                secret = args.totp_secret or os.environ.get("IG_TOTP_SECRET")
                r3 = None
                try:
                    r3 = bloks_2fa_old_resolve(s, ctx, username, secret)
                except requests.exceptions.RequestException as e:
                    print("bloks 2FA flow network error:", str(e)[:150])
                if r3 is None:
                    # Last resort: purane September-captured templates
                    print(">> fresh bloks flow fail — purane templates try kar rahe hain")
                    send("twostep_entry", ctx=ctx)
                    send("twostep_poll", ctx=ctx)
                    code = totp_code(secret) if secret else input("2FA code: ").strip()
                    r3 = send("twostep_verify", code=code, ctx=ctx)
                r = r3
                text = r3.text
                embedded = {}
                try:
                    embedded = bloks_extract_login_response(r3.json())
                except ValueError:
                    pass
                hdrs = embedded.get("headers") or {}
                auth = (hdrs.get("IG-Set-Authorization")
                        or hdrs.get("ig-set-authorization"))
                if auth or (embedded.get("cookies") or {}).get("sessionid"):
                    creds = {"authorization": auth,
                             "cookies": dict(embedded.get("cookies") or {})}
                else:
                    creds = extract_credentials(text)
                if not creds["authorization"] and not creds["cookies"]:
                    d2 = diagnose_login_response(text)
                    print(f"\n2FA ke baad credentials nahi mile (diag={d2}).")
                    print("Response snippet:", text[:800])
                    try:
                        with open("debug_2fa_final.json", "w", encoding="utf-8") as df:
                            df.write(text)
                        print("(poora response debug_2fa_final.json me save hai)")
                    except OSError:
                        pass
                    raise SystemExit(1)

            elif diag == "GENERIC_ERROR":
                print("\n>> GENERIC_ERROR — IG ka explicit generic error dialog:")
                print('   Response me "Unable to log in — An unexpected error occurred." aaya.')
                print("   has_identification_error=false → username/password SAHI hain, 2FA bhi nahi mangi.")
                print("   Ye server-side RISK rejection hai: IG ke trust system (pre_mt_behavior flow)")
                print("   ne credentials evaluate hi nahi kiye — attempt ko suspicious maan kar error diya.")
                print("   => AAJ aur attempts BAND karo (har naya attempt flag ko refresh karta hai).")
                print("   => Pehle phone ke asli Instagram app se is account me login karke dekho (home IP):")
                print("      app me login ho gaya = account healthy, trust state reset ho jayega.")
                print("   => Overnight (12+ ghante) baad SIRF EK retry — bina proxy, home IN IP se.")
                cooldown_set(username, "GENERIC_ERROR")

            elif diag == "FALLBACK":
                print("\n>> CAA_LOGIN_FALLBACK — IG ka soft-refusal:")
                print("   IG ne na session di, na 2FA, na koi error dialog — bas dead legacy")
                print("   endpoint par bhej diya (jo har version par needs_upgrade deta hai).")
                print("   Aam karan: is account/IP par aaj bahut attempts ho chuke hain,")
                print("   ya IG ko client trust nahi mila.")
                print("   => 45-60 minute WAIT karo, phir SIRF EK baar retry karo")
                print("      (Indian account = bina proxy, apni home IP se).")
                cooldown_set(username, "FALLBACK")

        if not creds["authorization"] and not creds["cookies"]:
            print("\nLOGIN FAILED — response ka relevant hissa:")
            print(text[:1500])
            try:
                with open(os.path.join(HERE, "debug_login_response.json"), "w", encoding="utf-8") as df:
                    df.write(text)
                print("\n(poora send_login response 'debug_login_response.json' me save ho gaya —")
                print(" debug karne ke liye uska content share karo)")
            except OSError as e:
                print("debug dump fail:", e)
            raise SystemExit(1)

    # token se authoritative sessionid/ds_user_id merge karo
    # (web enrich DEFAULT OFF — app session ko web surface par mix mat karo)
    if creds["authorization"]:
        creds["cookies"].update(
            derive_cookies_from_token(creds["authorization"]))
        # Server-issued mid extraction from Set-Cookie / session cookies
        server_mid = (
            creds["cookies"].get("mid")
            or (getattr(s, "cookies", None) and s.cookies.get("mid"))
            or (getattr(r, "cookies", None) and r.cookies.get("mid"))
            or _DEVICE.get("x-mid", "")
            or _SERVER_MID
        )
        if server_mid:
            creds["cookies"]["mid"] = server_mid
        if args.web_cookies:
            creds["cookies"] = enrich_web_cookies(creds["cookies"])
        elif not creds["cookies"].get("csrftoken"):
            print("note: csrftoken nahi mila (sirf app-surface cookies). "
                  "Web use chahiye to --web-cookies flag samajh kar lagayein.")

    # 10) session verify + account status check
    # NOTE: Instagram authentication aur authorization alag hain:
    #   - Authentication (password check) = send_login = 200 + token mila
    #   - Authorization (account active?) = verify call = yahan actual status pata chalta hai
    # Isliye suspended account ka bhi token milta hai — password sahi hota hai
    # lekin account lock hone se actual API calls fail hoti hain.
    token_data = derive_cookies_from_token(creds["authorization"]) if creds["authorization"] else {}
    server_rur = r.headers.get("ig-set-ig-u-rur") or r.headers.get("ig-set-rur") or token_data.get("rur") or "ODN"
    creds["cookies"]["rur"] = server_rur

    uid = creds["cookies"].get("ds_user_id", "")
    hdr_verify = dict(TEMPLATES["mobileconfig"]["headers"])
    hdr_verify.pop("content-type", None)
    if creds["authorization"]:
        hdr_verify["authorization"] = creds["authorization"]
        hdr_verify["ig-intended-user-id"] = uid
        hdr_verify["ig-u-ds-user-id"] = uid
        hdr_verify["ig-u-rur"] = server_rur

    if _GEO and _GEO.get("timezone_offset"):
        hdr_verify["x-ig-timezone-offset"] = str(_GEO["timezone_offset"])
    if _GEO and _GEO.get("lang"):
        hdr_verify["accept-language"] = _GEO["lang"]
    if _GEO and _GEO.get("locale"):
        hdr_verify["x-ig-app-locale"] = _GEO["locale"]

    rv = s.get(
        f"{BASE}/api/v1/users/{uid}/info/",
        headers=hdr_verify, timeout=30
    )
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
        reasons = {"2": "Device/IP mismatch ya account restricted", "7": "Account suspended", "8": "Session replaced", "6": "Session expired"}
        print(f"*** SESSION INVALID — {reasons.get(lr, 'logout_reason=' + lr)} ***")
        account_ok = False

    dev_info = {
        "app_version": _PROFILE.get("app_version", APP_VERSION),
        "platform": "Android",
        "android_version": _PROFILE.get("android_version", "12"),
        "api_level": _PROFILE.get("api_level", "32"),
        "dpi": _PROFILE.get("dpi", "420dpi"),
        "resolution": _PROFILE.get("resolution", "1080x2400"),
        "manufacturer": _PROFILE.get("manufacturer", "Xiaomi"),
        "model": _PROFILE.get("model", "2203121C"),
        "cpu": _PROFILE.get("cpu", "qcom"),
        "build_number": _PROFILE.get("build_number", APP_CODE),
        "device_codename": _PROFILE.get("device_codename", ""),
        "locale": _GEO.get("locale", "en_US")
    }


    status_str = "active" if account_ok else "restricted"
    totp_val = args.totp_secret or os.environ.get("IG_TOTP_SECRET", "")

    account_info = {}
    if account_ok:
        try:
            user_data = rv.json().get("user", {})
            account_info = {
                "pk": user_data.get("pk") or uid,
                "full_name": user_data.get("full_name", ""),
                "is_private": user_data.get("is_private", False),
                "is_verified": user_data.get("is_verified", False),
                "follower_count": user_data.get("follower_count", 0),
                "following_count": user_data.get("following_count", 0),
                "media_count": user_data.get("media_count", 0),
            }
        except Exception:
            pass

    out = {
        "username": username,
        "password": password,
        "totp_secret": totp_val,
        "country": country_key,
        "is_mobile": True,
        "status": status_str,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cookies": creds["cookies"],
        "mobile_api_session": {
            "identifiers": {
                "android_id": _DEVICE.get("x-ig-android-id", ""),
                "uuids": [
                    _DEVICE.get("x-ig-device-id", ""),
                    _DEVICE.get("x-ig-family-device-id", "")
                ]
            },
            "device_info": dev_info,
            "session_data": {
                "Authorization": creds["authorization"]
            }
        },
        "fingerprint": {
            "proxy_url": _GEO.get("proxy") or "",
            "proxy_country": country_key,
            "timezone_offset": int(_GEO.get("timezone_offset", "19800")),
            "is_mobile": True
        }
    }
    if account_info:
        out["account_info"] = account_info
    
    out_file = args.output if args.output else os.path.join(HERE, f"cookies_{username}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    with open(os.path.join(HERE, "cookies.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


    print("\n=== COOKIES / SESSION ===")
    for k, v in creds["cookies"].items():
        print(f"  {k} = {v[:12]}...[{len(v)}]")
    if creds["authorization"]:
        print(f"  Authorization = {creds['authorization'][:30]}...[{len(creds['authorization'])}]")
    if account_ok:
        print(f"\nSaved -> {os.path.basename(out_file)} & cookies.json  [SESSION VALID]")
        cooldown_clear(username)
    else:
        print(f"\nSaved -> {os.path.basename(out_file)} & cookies.json  [WARNING: Account restricted/suspended — session use nahi hogi!]")



if __name__ == "__main__":
    main()
