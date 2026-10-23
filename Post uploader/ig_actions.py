#!/usr/bin/env python3
"""
ig_actions.py — Story VIEW + LIKE + COMMENT, real-app capture formats.
Session: cookies.json (ig_login.py output: authorization + cookies).

v3: per-account device identity (multi-account research support).

Formats 100% apne real captures se liye gaye hain:
  - /api/v2/media/seen/  : 3-part reel key + [taken_at_seen_at] value, gzip body
  - /api/v1/media/<id>/like/    : capture wala signed_body + d=0
  - /api/v1/media/<id>/comment/ : idempotence_token wala format

USAGE:
  python ig_actions.py --cookies cookies.json --action verify
  python ig_actions.py --cookies cookies.json --action all --comment-text "nice post"
  python ig_actions.py --cookies cookies.json --action seen|like|comment
  python ig_actions.py --cookies cookies.json --action upload-story|upload-photo

SIRF apne/dummy accounts par. ToS risk: action_block/challenge possible.
"""
import argparse
import base64
import gzip
import io
import json
import os
import random
import re
import sys
import time
import urllib.parse
import uuid
import zlib

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://i.instagram.com"
TEMPLATES = json.load(open(os.path.join(HERE, "templates.json"), encoding="utf-8"))

SUPPORTED_CAPS = json.dumps([
    {"name": "SUPPORTED_SDK_VERSIONS",
     "value": ",".join(f"{v}.0" for v in range(149, 203))},
    {"name": "SUPPORTED_BETA_SDK_VERSIONS",
     "value": ",".join(f"{v}.0-beta" for v in range(182, 203))},
    {"name": "FACE_TRACKER_VERSION", "value": "14"},
    {"name": "segmentation", "value": "segmentation_enabled"},
    {"name": "COMPRESSION", "value": "ETC2_COMPRESSION"},
    {"name": "world_tracker", "value": "world_tracker_enabled"},
    {"name": "gyroscope", "value": "gyroscope_enabled"},
], separators=(",", ":"))

RUN_CONN_UUID = uuid.uuid4().hex

# Geo-identity presets — account jis country ke proxy se chalta hai,
# timezone/locale/startup-country usi se MATCH hona chahiye (warna mismatch signal).
# Note: GB summer(BST)=3600 / winter(GMT)=0; US region ke hisaab se badalta hai.
GEO_PRESETS = {
    "IN": {"timezone_offset": 19800, "locale": "en_IN",
           "accept_language": "en-IN, en-US", "startup_country": "IN"},
    "GB": {"timezone_offset": 3600, "locale": "en_GB",
           "accept_language": "en-GB, en-US", "startup_country": "GB"},
    "US": {"timezone_offset": -18000, "locale": "en_US",
           "accept_language": "en-US", "startup_country": "US"},
}


def resolve_geo(geo):
    """'GB' (preset name) ya explicit dict -> full geo dict."""
    if not geo:
        geo = "IN"
    if isinstance(geo, str):
        return dict(GEO_PRESETS.get(geo.upper(), GEO_PRESETS["IN"]))
    base = dict(GEO_PRESETS.get((geo.get("preset") or "IN").upper(), GEO_PRESETS["IN"]))
    base.update({k: v for k, v in geo.items() if k != "preset"})
    return base


class Session:
    def __init__(self, path, geo=None):
        d = json.load(open(path, encoding="utf-8"))
        self.username = d.get("username")
        self.user_agent = None      # None = template UA; set = file-captured UA
        self.dev_info = None        # device block for configure()
        self.rur_code = "ODN"       # ig-u-rur header
        proxy_url = None

        if "mobile_api_session" in d:
            # ============ NEW FORMAT (device-capture based) ============
            ma = d["mobile_api_session"]
            self.auth = ma["session_data"]["Authorization"]
            self.cookies = d.get("cookies", {})
            ids = ma.get("identifiers", {})
            di = ma.get("device_info", {})
            fp = d.get("fingerprint", {})
            self.uid = self.cookies.get("ds_user_id") or str(d.get("account_info", {}).get("pk", ""))
            self.mid = self.cookies.get("mid", "")
            rur = self.cookies.get("rur", "")
            if rur:
                self.rur_code = rur.split(",")[0]     # "CLN,uid,..." -> "CLN"
            self.android_id = ids.get("android_id", "")
            uuids = ids.get("uuids", [])
            self.device_uuid = uuids[0] if len(uuids) > 0 else str(uuid.uuid4())
            self.family_uuid = uuids[1] if len(uuids) > 1 else str(uuid.uuid4())
            # UA: capture ke device se EXACT build (mismatch = suspicion)
            self.user_agent = (
                f"Instagram {di.get('app_version')} Android "
                f"({di.get('api_level')}/{di.get('android_version')}; "
                f"{di.get('dpi')}; {di.get('resolution')}; "
                f"{di.get('manufacturer')}; {di.get('model')}; "
                f"{di.get('device_codename')}; {di.get('cpu')}; "
                f"{di.get('locale')}; {di.get('build_number')})")
            self.dev_info = {"manufacturer": di.get("manufacturer"),
                             "model": di.get("model"),
                             "android_version": int(di.get("api_level") or 28),
                             "android_release": di.get("android_version")}
            # GEO: file ke values authoritative (timezone_offset explicit hai)
            country = (fp.get("proxy_country") or d.get("country") or "IN").upper()
            country = "GB" if country == "UK" else country
            file_geo = {"timezone_offset": fp.get("timezone_offset", 19800),
                        "locale": di.get("locale", "en_GB"),
                        "accept_language": di.get("locale", "en_GB").replace("_", "-") + ", en-US",
                        "startup_country": country}
            self.geo = resolve_geo(geo or file_geo)
            proxy_url = fp.get("proxy_url")
        else:
            # ============ LEGACY FORMAT (ig_login.py output) ============
            self.auth = d.get("authorization")
            self.cookies = d.get("cookies", {})
            self.uid = self.cookies.get("ds_user_id", "")
            self.mid = self.cookies.get("mid", "")
            self.geo = resolve_geo(geo or d.get("geo") or "IN")
            dev = d.get("device") or {}
            tmpl = TEMPLATES["mobileconfig"]["headers"]
            self.android_id = dev.get("android_id") or tmpl.get("x-ig-android-id", "")
            self.device_uuid = dev.get("device_uuid") or tmpl.get("x-ig-device-id", str(uuid.uuid4()))
            self.family_uuid = dev.get("family_uuid") or tmpl.get("x-ig-family-device-id", str(uuid.uuid4()))
        self.tz = self.geo["timezone_offset"]
        self.locale = self.geo["locale"]
        if not self.auth or not self.uid:
            sys.exit(f"{path} me authorization/ds_user_id nahi mila")
        self.s = requests.Session()
        # Proxy: new-format cookies file me embedded hai — automatic apply
        if proxy_url:
            self.s.proxies = {"http": proxy_url, "https": proxy_url}
            self.s.trust_env = False   # env/system proxy interfere na kare
        # App-style cookie jar (domain ke saath) — session fidelity ke liye
        for k in ("sessionid", "ds_user_id", "mid", "rur"):
            if self.cookies.get(k):
                self.s.cookies.set(k, self.cookies[k], domain=".instagram.com")
        self.nav = []
        self.pigeon = f"UFS-{uuid.uuid4()}-0"
        self._cold_start_ts = time.time()   # session shuru = app cold_start reference
        self.proxy_configured = bool(proxy_url)
        if not proxy_url:
            print("⚠️  cookies file me proxy nahi — requests DIRECT IP se jayengi.")
            print(f"   Geo={self.locale}/tz={self.tz} vs IP mismatch flag signal ho sakta hai")
            print("   (ignore karo agar caller proxy baad me set karta hai)")
        # FCM push token (per-session stable, realistic format)
        self.fcm_token = (base64.urlsafe_b64encode(os.urandom(8)).rstrip(b"=").decode()
                          + ":APA91b"
                          + base64.urlsafe_b64encode(os.urandom(112)).rstrip(b"=").decode())

    # ------------------------------------------------------------ headers
    def base_headers(self, friendly, endpoint_hint=None):
        h = dict(TEMPLATES["mobileconfig"]["headers"])
        h.pop("content-type", None)
        h["authorization"] = self.auth
        h["ig-intended-user-id"] = self.uid
        h["ig-u-ds-user-id"] = self.uid
        h["ig-u-rur"] = self.rur_code
        h["accept-encoding"] = "gzip"
        h["accept"] = "*/*"
        h["priority"] = "u=3"
        h["x-mid"] = self.mid
        h["x-ig-android-id"] = self.android_id
        h["x-ig-device-id"] = self.device_uuid
        h["x-ig-family-device-id"] = self.family_uuid
        # GEO consistency — IP ke country se timezone/locale match
        h["x-ig-timezone-offset"] = str(self.tz)
        h["x-ig-app-locale"] = self.locale
        h["x-ig-device-locale"] = self.locale
        h["x-ig-mapped-locale"] = self.locale
        h["accept-language"] = self.geo["accept_language"]
        h["x-ig-app-startup-country"] = self.geo["startup_country"]
        if self.user_agent:  # NEW format: file-captured device ka EXACT UA
            h["user-agent"] = self.user_agent
        elif "user-agent" in h:  # legacy: UA ke andar ka locale match karo
            h["user-agent"] = re.sub(r";\s*en_[A-Z]{2};", f"; {self.locale};",
                                     h["user-agent"])
        h["x-fb-http-engine"] = "Tigon/MNS/TCP"
        h["x-fb-conn-uuid-client"] = RUN_CONN_UUID
        h["x-fb-client-ip"] = "True"
        h["x-fb-server-cluster"] = "True"
        h["x-fb-connection-type"] = "WIFI"
        h["x-fb-friendly-name"] = friendly
        h["x-fb-request-analytics-tags"] = json.dumps(
            {"network_tags": {"product": "567067343352427", "surface": "undefined",
                              "request_category": "api", "purpose": "fetch",
                              "retry_attempt": "0"}}, separators=(",", ":"))
        h["x-pigeon-session-id"] = self.pigeon
        h["x-pigeon-rawclienttime"] = f"{time.time():.3f}"
        h["x-tigon-is-retry"] = "False"
        nav = ",".join(self.nav[-8:]) if self.nav else ""
        if nav:
            h["x-ig-nav-chain"] = nav
        if endpoint_hint:
            h["x-ig-client-endpoint"] = endpoint_hint
        return h

    def push_nav(self, frag, surface):
        self.nav.append(f"{frag}:{surface}:{len(self.nav)+1}:user_action:{time.time():.3f}::")

    # ------------------------------------------------------------ helpers
    def signed_body(self, obj):
        return "SIGNATURE." + json.dumps(obj, separators=(",", ":"))

    def post_form(self, path, obj, friendly, extra_form=None, gzip_body=False,
                  extra_headers=None):
        h = self.base_headers(friendly)
        h["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        form = {"signed_body": self.signed_body(obj)}
        if extra_form:
            form.update(extra_form)
        body = urllib.parse.urlencode(form, quote_via=urllib.parse.quote).encode()
        if gzip_body:
            body = gzip.compress(body)
            h["content-encoding"] = "gzip"
        if extra_headers:
            h.update(extra_headers)
        r = self.s.post(BASE + path, headers=h, data=body, timeout=30)
        return r

    def get(self, path, friendly, params=None):
        h = self.base_headers(friendly)
        return self.s.get(BASE + path, headers=h, params=params, timeout=30)

    def post_plain(self, path, form, friendly):
        """UNSIGNED plain form POST (capture me kuch endpoints signed_body use
        nahi karte — e.g. update_profile_name, change_profile_picture)."""
        h = self.base_headers(friendly)
        h["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        body = urllib.parse.urlencode(form).encode()
        return self.s.post(BASE + path, headers=h, data=body, timeout=30)


# ================================================================= ACTIONS
def verify(sess, label=""):
    r = sess.get(f"/api/v1/users/{sess.uid}/info/", "IgApi: users/info/")
    ok = r.status_code == 200 and sess.username in r.text
    flag = ""
    for pat, msg in (("challenge_required", "CHALLENGE!"),
                     ("accounts/suspended", "SUSPENDED!"),
                     ("login_required", "SESSION EXPIRED")):
        if pat in r.text:
            flag = " *** " + msg
    print(f"[verify {label:6s}] HTTP {r.status_code} -> "
          f"{'OK ✅' if ok else 'FAIL ❌'}{flag}")
    return ok and not flag


# ============================================================= COLD START
def cold_start(sess, verbose=True):
    """Real app-open sequence — fullaction.mitm cold start (0-15s window) se.
    Har session ki shuruaat par call karo: insaan app kholta hai, ye sab
    fire hota hai, TAB jaake wo like/comment/seen karta hai.
    Skipped by design: check_consistency (767KB device-cache blob),
    logging_client_events (telemetry — low signal)."""
    calls = oks = 0
    t_start = time.time()

    def step(method, path, friendly, obj=None, form=None, params=None):
        nonlocal calls, oks
        time.sleep(random.uniform(0.2, 1.1))  # capture me 0.2-1.5s bursts
        try:
            if method == "GET":
                r = sess.get(path, friendly, params=params)
            elif obj is not None:
                r = sess.post_form(path, obj, friendly)
            else:
                h = sess.base_headers(friendly)
                h["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8"
                body = urllib.parse.urlencode(form, quote_via=urllib.parse.quote).encode()
                r = sess.s.post(BASE + path, headers=h, data=body, timeout=30)
            calls += 1
            ok = r.status_code == 200
            oks += ok
            if verbose:
                print(f"   cold {r.status_code} {path}")
        except Exception as e:
            if verbose:
                print(f"   cold ERR {path}: {e}")

    uid, duuid, fduuid = sess.uid, sess.device_uuid, sess.family_uuid

    # 1. android ML modules check
    step("POST", "/api/v1/android_modules/download/", "IgApi: android_modules/download/",
         obj={"_uid": uid, "_uuid": duuid,
              "hashes": ["0c63422693eec3941bf5b6ae23aabe38c62928c656d7da081dca668910df00be"]})
    # 2. config GETs (capture order)
    step("GET", "/api/v1/live/pre_live_tools/", "IgApi: live/pre_live_tools/")
    step("GET", "/api/v1/creatives/get_unlockable_sticker_nux/", "IgApi: creatives/get_unlockable_sticker_nux/")
    step("GET", "/api/v1/clips/user/share_to_fb_config/", "IgApi: clips/user/share_to_fb_config/")
    step("GET", "/api/v1/users/reel_settings/", "IgApi: users/reel_settings/")
    step("GET", "/api/v1/upcoming_events/add_event_list/", "IgApi: upcoming_events/add_event_list/",
         params={"event_category": "broadcast"})
    step("GET", "/api/v1/notifications/get_notification_settings/", "IgApi: notifications/get_notification_settings/",
         params={"content_type": "post_and_comments"})
    step("GET", "/api/v1/direct_v2/async_get_pending_requests_preview/",
         "IgApi: direct_v2/async_get_pending_requests_preview/",
         params={"pending_inbox_filters": "[]"})
    # 3. launcher mobileconfig — 2 variants (sessionless + logged-in)
    step("POST", "/api/v1/launcher/mobileconfig/", "IgApi: launcher/mobileconfig/",
         obj={"bool_opt_policy": "0", "mobileconfigsessionless": "", "api_version": "10",
              "client_context": "[\"opt,value_hash\"]", "unit_type": "1",
              "use_case": "STANDARD",
              "query_hash": "597390b5cb4ce1dabe98df56106be3b4f174cc774a4711a1455b5e9adc44f968",
              "ts": str(int(time.time())), "device_id": duuid,
              "fetch_mode": "CONFIG_SYNC_ONLY", "fetch_type": "SYNC_FULL",
              "family_device_id": fduuid.upper()})
    step("POST", "/api/v1/launcher/mobileconfig/", "IgApi: launcher/mobileconfig/",
         obj={"bool_opt_policy": "0", "mobileconfig": "", "api_version": "10",
              "client_context": "[\"opt,p64v\"]", "unit_type": "2",
              "use_case": "STANDARD",
              "query_hash": "686e6697d0c77b742beb4dbd302376f72082a1b734e99017c5f1408e510dbb69",
              "ts": str(int(time.time())), "_uid": uid, "device_id": duuid,
              "_uuid": duuid, "fetch_mode": "CONFIG_SYNC_ONLY", "fetch_type": "SYNC_FULL",
              "request_data_query_hash": "686e6697d0c77b742beb4dbd302376f72082a1b734e99017c5f1408e510dbb69"})
    # 4. account family + ranking bootstrap + loom
    step("GET", "/api/v1/multiple_accounts/get_account_family/",
         "IgApi: multiple_accounts/get_account_family/",
         params={"request_source": "startup_manager"})
    step("GET", "/api/v1/scores/bootstrap/users/", "IgApi: scores/bootstrap/users/",
         params={"surfaces": json.dumps(["autocomplete_user_list",
                                         "coefficient_besties_list_ranking",
                                         "coefficient_rank_recipient_user_suggestion"])})
    step("GET", "/api/v1/loom/fetch_config/", "IgApi: loom/fetch_config/")
    # 5. notifications badge + push register
    step("POST", "/api/v1/notifications/badge/", "IgApi: notifications/badge/",
         form={"phone_id": fduuid, "trigger": "UNTRACKED", "user_ids": uid,
               "device_id": duuid, "_uuid": duuid})
    step("POST", "/api/v1/push/register/", "IgApi: push/register/",
         form={"device_type": "android_fcm",
               "os_settings": "{\"notificationEnabled\":true}",
               "hpke_pubkey": "BCkcS8F6CyKiVwQJmuLtKk1SLM2iOrvMEqfaa1ZeDe2sTVOWutzSKI+yHsSAnV7e3PQU2dtiP7AQDp95fkV8BAA=",
               "device_sub_type": "0", "hpke_ciphersuite": "1001000010000",
               "device_token": sess.fcm_token,
               "guid": duuid, "request_id": str(uuid.uuid4()), "_uuid": duuid,
               "users": uid, "family_device_id": fduuid,
               "hpke_keystore_id": str(int(time.time() * 1000))})
    # 6. feed surfaces — reels tray (stories) + timeline
    step("POST", "/api/v1/feed/reels_tray/", "IgApi: feed/reels_tray/",
         form={"reason": "cold_start", "timezone_offset": sess.tz,
               "tray_session_id": str(uuid.uuid4()),
               "request_id": str(uuid.uuid4()), "_uuid": duuid, "page_size": 50})
    step("POST", "/api/v1/feed/timeline/", "IgApi: feed/timeline/",
         form={"reason": "cold_start", "count": 8, "timezone_offset": sess.tz,
               "_uuid": duuid, "device_id": sess.android_id,
               "phone_id": fduuid, "is_pull_to_refresh": 0,
               "feed_view_info": "[]"})
    sess.push_nav("MainFeedFragment", "feed_timeline")
    dur = time.time() - t_start
    print(f"[cold start       ] {oks}/{calls} ok in {dur:.1f}s")
    return oks == calls and calls > 0


def upload_image(sess, img_bytes, w, h, kind="post"):
    """kind: 'post' | 'story' | 'dp' — allactioninonefile.mitm capture-exact rparams."""
    upload_id = str(int(time.time() * 1000))
    rand = random.randint(10**8, 10**9 - 1)
    if kind == "dp":
        rand = -rand  # capture me dp entity name me NEGATIVE random tha
    entity = f"{upload_id}_0_{rand}"
    retry_ctx = json.dumps({"num_reupload": 0, "num_step_manual_retry": 0,
                            "num_step_auto_retry": 0}, separators=(",", ":"))
    if kind == "dp":
        rparams = {"image_compression": json.dumps(
                       {"lib_name": "moz", "lib_version": "3.1.m", "quality": "70"},
                       separators=(",", ":")),
                   "upload_id": upload_id, "media_type": "1"}
    elif kind == "story":
        rparams = {"upload_id": upload_id, "session_id": upload_id, "media_type": "1",
                   "upload_engine_config_enum": "0", "share_type": "stories",
                   "is_optimistic_upload": "false",
                   "image_compression": json.dumps(
                       {"lib_name": "libwebp", "lib_version": "28", "quality": "85",
                        "original_width": w, "original_height": h}, separators=(",", ":")),
                   "xsharing_user_ids": "[]", "retry_context": retry_ctx}
    else:  # post
        rparams = {"upload_id": upload_id, "session_id": upload_id, "media_type": "1",
                   "upload_engine_config_enum": "0", "share_type": "feed",
                   "is_optimistic_upload": "false",
                   "image_compression": json.dumps(
                       {"lib_name": "libwebp", "lib_version": "28", "quality": "88",
                        "original_width": w, "original_height": h}, separators=(",", ":")),
                   "xsharing_user_ids": "[]", "retry_context": retry_ctx}
    hdr = sess.base_headers("undefined:media-upload")
    hdr.update({
        "content-type": "application/octet-stream",
        "offset": "0",
        "x-entity-length": str(len(img_bytes)),
        "x-entity-name": entity,
        "x-entity-type": "image/jpeg" if kind == "dp" else "image/webp",
        "x-instagram-rupload-params": json.dumps(rparams, separators=(",", ":")),
        "x_fb_photo_waterfall_id": str(uuid.uuid4()),
        "priority": "u=6, i",
    })
    if kind == "dp":
        # capture: DP upload se pehle ek GET resume-check jaata hai
        sess.s.get(f"{BASE}/rupload_igphoto/{entity}",
                   headers={k: v for k, v in hdr.items() if k != "content-type"},
                   timeout=30)
    r = sess.s.post(f"{BASE}/rupload_igphoto/{entity}", headers=hdr,
                    data=img_bytes, timeout=60)
    print(f"[rupload {kind:5s}   ] {r.status_code} {r.text[:80]}")
    if r.status_code != 200 or '"ok"' not in r.text:
        return None
    return upload_id


def _nav_chain_upload(sess):
    """Real app jaisa gallery-picker nav chain (capture-exact pattern)."""
    t = time.time()
    start = getattr(sess, "_cold_start_ts", t - random.uniform(300, 900))
    frags = [
        f"MainFeedFragment:feed_timeline:1:cold_start:{start:.3f}::",
        f"GalleryPickerFragment:gallery_picker:{random.randint(55,70)}:camera_tab_bar:{t-8:.3f}::",
        f"PhotoFilterFragment:photo_filter:{random.randint(60,72)}:button:{t-5:.3f}::",
        f"FollowersShareFragment:media_broadcast_share:{random.randint(64,78)}:next:{t-2:.3f}::",
    ]
    return ",".join(frags)


def configure(sess, upload_id, w, h, is_story, caption=""):
    """allactioninonefile.mitm capture-exact configure bodies."""
    dev = getattr(sess, "dev_info", None) or {
        "manufacturer": "Xiaomi", "model": "2203121C",
        "android_version": 28, "android_release": "9"}
    now = int(time.time())
    cam_session = str(uuid.uuid4())
    extra_hdr = {"x-ig-client-endpoint": "feed_timeline",
                 "retry_context": json.dumps(
                     {"num_reupload": 0, "num_step_manual_retry": 0,
                      "num_step_auto_retry": 0}, separators=(",", ":"))}
    if is_story:
        obj = {
            "supported_capabilities_new": SUPPORTED_CAPS,
            "has_camera_metadata": "0", "camera_entry_point": "11",
            "original_media_type": "1", "camera_session_id": cam_session,
            "original_height": str(h),
            "include_e2ee_mentioned_user_list": "1",
            "hide_from_profile_grid": "false", "scene_capture_type": "",
            "timezone_offset": str(sess.tz),
            "client_shared_at": str(now - 4),
            "media_folder": "Instagram", "configure_mode": "1",
            "source_type": "4", "camera_position": "unknown",
            "_uid": sess.uid, "device_id": sess.android_id,
            "composition_id": str(uuid.uuid4()), "_uuid": sess.device_uuid,
            "creation_tool_info": "[]", "creation_surface": "camera",
            "nav_chain": getattr(sess, "_nav_cold", "") or (
                f"MainFeedFragment:feed_timeline:1:cold_start:"
                f"{getattr(sess, '_cold_start_ts', time.time()-600):.3f}::"),
            "imported_taken_at": str(int(upload_id) // 1000),
            "capture_type": "normal", "audience": "default",
            "upload_id": upload_id, "client_timestamp": str(now),
            "bottom_camera_dial_selected": "2", "publish_id": "1",
            "original_width": str(w),
            "media_transformation_info": json.dumps(
                {"width": str(w), "height": str(h), "x_transform": "0",
                 "y_transform": "0", "zoom": "1.0", "rotation": "0.0",
                 "background_coverage": 100}, separators=(",", ":")),
            "edits": {"filter_type": 0, "filter_strength": 0.5,
                      "crop_original_size": [float(w), float(h)]},
            "extra": {"source_width": w, "source_height": h},
            "device": dev,
        }
        path, friendly = "/api/v1/media/configure_to_story/", "IgApi: media/configure_to_story/"
    else:
        obj = {
            "app_attribution_android_namespace": "",
            "camera_entry_point": "360", "camera_session_id": cam_session,
            "original_height": str(h),
            "include_e2ee_mentioned_user_list": "1",
            "hide_from_profile_grid": "false", "scene_capture_type": "",
            "timezone_offset": str(sess.tz), "source_type": "4",
            "_uid": sess.uid, "device_id": sess.android_id,
            "_uuid": sess.device_uuid, "creation_tool_info": "[]",
            "creation_logger_session_id": cam_session,
            "nav_chain": _nav_chain_upload(sess),
            "caption": caption, "audience": "default",
            "upload_id": upload_id,
            "bottom_camera_dial_selected": "11", "publish_id": "1",
            "original_width": str(w),
            "edits": {"filter_type": 0, "filter_strength": 1.0,
                      "crop_original_size": [float(w), float(h)],
                      "crop_center": [0.0, -0.0], "crop_zoom": 1.0},
            "extra": {"source_width": w, "source_height": h},
            "device": dev, "overlay_data": [],
        }
        path, friendly = "/api/v1/media/configure/", "IgApi: media/configure/"
    # NOTE: check_offensive_multi_text endpoint SERVER-SIDE DEAD hai
    # (har input par 400, real app ko bhi) — isliye call nahi bhejte.
    # Real app capture me bhi feed-post ke liye ye call gaya hi nahi tha.
    time.sleep(random.uniform(1.5, 3.5))
    r = sess.post_form(path, obj, friendly, gzip_body=True, extra_headers=extra_hdr)
    if r.status_code != 200:
        print(f"   !! configure error body: {r.text[:400]}")
    try:
        j = r.json()
    except Exception:
        j = {}
    media = j.get("media") or {}
    pk, taken = str(media.get("pk", "")), int(media.get("taken_at", now))
    print(f"[configure {'story' if is_story else 'photo':5s}] {r.status_code} "
          f"pk={pk} taken_at={taken}")
    if r.status_code == 200:
        # COMPANION: real app configure ke BAAD pdq-hash + analytics bhejta hai
        time.sleep(random.uniform(1.0, 2.5))
        update_pdq_hash_info(sess, upload_id)
        send_client_events(sess, module="feed_timeline" if not is_story else "story_composer",
                           n_events=2)
    return pk, taken, r.status_code


# ------------------------------------------------------- COMPANION / TELEMETRY
# fullaction.mitm audit: real app har upload ke saath ye saathi calls bhejta hai.
# Inke bina client "bilkul chup" dikhta hai — ye gap close karne ke liye.

GRAPH_LOG_URL = "https://graph.instagram.com/logging_client_events"
GRAPH_APP_TOKEN = "567067343352427|f249176f09e26ce54212b472dbab8fa8"


def check_offensive_text(sess, texts, request_type="caption"):
    """CURRENTLY UNUSED — endpoint server-side dead hai (har input par 400,
    real app ko bhi). Function future ke liye reserved: agar IG endpoint
    wapas laye to configure() se call wapas add kar dena."""
    if not any(t.strip() for t in texts):
        return True   # empty text: call skip (real app bhi 400 hi paati)
    obj = {
        "text_list": json.dumps(texts, separators=(",", ":")),
        "_uid": sess.uid,
        "_uuid": sess.device_uuid,
        "request_type": request_type,
    }
    r = sess.post_form("/api/v1/warning/check_offensive_multi_text/", obj,
                       "IgApi: warning/check_offensive_multi_text/")
    if r.status_code != 200:
        print(f"   [offensive-check] {r.status_code} (endpoint deprecated server-side — ignored)")
    return r.status_code == 200


def update_pdq_hash_info(sess, upload_id):
    """Capture-exact: story configure ke BAAD PDQ hash follow-up."""
    obj = {
        "pdq_hash_info": json.dumps(
            [{"pdq_hash": "0" * 64 + ":0", "frame_time": 0}],
            separators=(",", ":")),
        "_uid": sess.uid,
        "_uuid": sess.device_uuid,
        "upload_id": upload_id,
    }
    r = sess.post_form("/api/v1/media/update_media_with_pdq_hash_info/", obj,
                       "IgApi: media/update_media_with_pdq_hash_info/")
    return r.status_code == 200


def _ua_field(sess):
    """UA se fields: (ver, api, os, model, build) — 'Instagram V Android (a/b; ...; M; ...; BUILD)'"""
    ua = sess.user_agent or ""
    m = re.search(r"Instagram (\S+) Android \((\d+)/(\d+);[^;]*;[^;]*;[^;]*; ([^;]+);[^;]*;[^;]*;[^;]*; (\d+)\)", ua)
    if not m:
        return ("400.0.0.49.68", "28", "9", "2203121C", "799297105")
    return m.group(1), m.group(2), m.group(3), m.group(4).strip(), m.group(5)


def build_client_events_message(sess, module="feed_timeline", n_events=1):
    """Capture-exact logging_client_events message structure (claims field
    OMITTED — wo server-issued HMAC hai, fabricate nahi karte)."""
    ver, api, os_ver, model, build = _ua_field(sess)
    now_ms = int(time.time() * 1000)
    data = []
    for i in range(n_events):
        data.append({
            "extra": {
                "pigeon_reserved_keyword_module": module,
                "activity_time": now_ms - i * 1000,
                "pk": sess.uid,
                "release_channel": "prod",
                "radio_type": "WIFI-UNKNOWN",
                "pigeon_reserved_keyword_log_type": "client_event",
                "pigeon_reserved_keyword_bg": "false",
            },
            "log_type": "client_event",
            "bg": "false",
            "time": (now_ms - i * 1000) / 1000,
            "module": module,
            "name": "immediate_active_seconds",
            "sampling_rate": 1,
            "tags": 8388608,
        })
    msg = {
        "time": now_ms,
        "app_id": "567067343352427",
        "app_ver": ver,
        "build_num": int(build),
        "consent_state": 0,
        "device": model,
        "os_ver": os_ver,
        "device_id": sess.device_uuid,
        "family_device_id": sess.family_uuid,
        "session_id": sess.pigeon,
        "seq": getattr(sess, "_evt_seq", 0) + n_events,
        "app_uid": sess.uid,
        "data": data,
        "tier": "micro_batch",
        "sent_time": now_ms / 1000,
    }
    sess._evt_seq = msg["seq"]
    return msg


def send_client_events(sess, module="feed_timeline", n_events=1, verbose=True):
    """graph.instagram.com par analytics fire karo (compressed message)."""
    msg = build_client_events_message(sess, module, n_events)
    blob = base64.b64encode(zlib.compress(json.dumps(
        msg, separators=(",", ":")).encode())).decode()
    form = urllib.parse.urlencode({
        "access_token": GRAPH_APP_TOKEN,
        "format": "json", "ffdb_token": "", "compressed": "1",
        "sent_time": f"{time.time():.3f}", "message": blob,
    }).encode()
    h = {"user-agent": sess.user_agent or "",
         "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
         "x-fb-friendly-name": "undefined:analytics",
         "accept-encoding": "gzip"}
    try:
        r = sess.s.post(GRAPH_LOG_URL, headers=h, data=form, timeout=20)
        if verbose:
            print(f"[telemetry      ] {r.status_code} ({n_events} events)")
        return r.status_code == 200
    except Exception as e:
        if verbose:
            print(f"[telemetry      ] err {e}")
        return False


def story_seen(sess, media_pk, owner, taken_at, module="feed_timeline_item_header"):
    """CAPTURE-exact format: 3-part key, [taken_seen] value, gzip body."""
    obj = {
        "_uid": sess.uid,
        "_uuid": sess.device_uuid,
        "container_module": module,
        "reels": {f"{media_pk}_{owner}_{owner}": [f"{taken_at}_{int(time.time())}"]},
        "reel_media_skipped": {},
        "nuxes": {},
        "nuxes_skipped": {},
        "force_seen_story_ids": [],
    }
    r = sess.post_form("/api/v2/media/seen/?reel=1&live_vod=0", obj,
                       "IgApi: media/seen/?reel=1&live_vod=0", gzip_body=True)
    print(f"[story seen       ] {r.status_code} {r.text[:80]}")
    return r.status_code == 200


def like(sess, media_id, pct_watched="0.6394039735099337"):
    obj = {
        "is_2m_enabled": "false",
        "inventory_source": "explore_story",
        "delivery_class": "organic",
        "tap_source": "button",
        "media_id": media_id,
        "like_bubble_user_ids": "",
        "media_pct_watched": pct_watched,
        "radio_type": "wifi-none",
        "_uid": sess.uid,
        "_uuid": sess.device_uuid,
        "nav_chain": ",".join(sess.nav[-6:]) if sess.nav else "",
        "is_from_swipe": False,
        "recs_ix": 0,
        "is_carousel_bumped_post": False,
        "floating_context_items": [],
        "container_module": "feed_timeline",
        "feed_position": 0,
    }
    r = sess.post_form(f"/api/v1/media/{media_id}/like/", obj,
                       f"IgApi: media/{media_id}/like/", extra_form={"d": "0"},
                       extra_headers={"x-fb-session-id": "nid=eb61LiYjtu+6;nc=1;fc=1;bc=0;"})
    print(f"[like             ] {r.status_code} {r.text[:100]}")
    return r


def comment(sess, media_id, text):
    # COMPANION (capture-exact): comment se pehle offensive check
    sess.post_form("/api/v1/media/comment/check_offensive_comment/", {
        "media_id": media_id, "_uid": sess.uid,
        "comment_session_id": str(uuid.uuid4()),
        "_uuid": sess.device_uuid, "comment_text": text,
    }, "IgApi: media/comment/check_offensive_comment/")
    time.sleep(random.uniform(0.8, 2.0))
    obj = {
        "delivery_class": "organic",
        "feed_position": 0,
        "container_module": "feed_timeline",
        "idempotence_token": str(uuid.uuid4()),
        "media_id": media_id,
        "comment_text": text,
        "_uid": sess.uid,
        "_uuid": sess.device_uuid,
        "device_id": sess.android_id,
        "radio_type": "wifi-none",
    }
    r = sess.post_form(f"/api/v1/media/{media_id}/comment/", obj,
                       f"IgApi: media/{media_id}/comment/", extra_form={"d": "0"})
    print(f"[comment          ] {r.status_code} {r.text[:160]}")
    return r


# ------------------------------------------------------------------ utils
def make_test_image(kind="post"):
    """kind: post/story -> WEBP bytes (capture-exact), dp -> JPEG."""
    from PIL import Image, ImageDraw
    w, h = {"story": (720, 1280), "post": (1080, 1080)}.get(kind, (1080, 1080))
    img = Image.new("RGB", (w, h),
                    (random.randint(30, 200), random.randint(30, 200), random.randint(30, 200)))
    d = ImageDraw.Draw(img)
    d.text((20, 20), f"test {time.strftime('%H:%M:%S')}", fill=(255, 255, 255))
    buf = io.BytesIO()
    if kind == "dp":
        img = img.resize((320, 320))
        img.save(buf, "JPEG", quality=87)
        w, h = 320, 320
    else:
        img.save(buf, "WEBP", quality=85 if kind == "story" else 88)
    return buf.getvalue(), w, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookies", default=os.path.join(HERE, "cookies.json"))
    ap.add_argument("--action", default="verify",
                    choices=["verify", "seen", "like", "comment", "all",
                             "upload-story", "upload-photo"])
    ap.add_argument("--comment-text", default="testing 👍")
    ap.add_argument("--media-pk", help="seen/like/comment target media pk")
    ap.add_argument("--owner-id", help="story/media owner uid")
    ap.add_argument("--taken-at", help="story taken_at epoch")
    args = ap.parse_args()

    sess = Session(args.cookies)
    sess.push_nav("MainFeedFragment", "feed_timeline")
    print(f">> account: {sess.username} (uid {sess.uid})")
    if not verify(sess, "START"):
        sys.exit("Session invalid — pehle login karo")

    results = {}
    if args.action in ("upload-story", "all"):
        sess.push_nav("QuickCaptureFragment", "stories_gallery")
        img, w, h = make_test_image("story")
        up = upload_image(sess, img, w, h, kind="story")
        if up:
            pk, taken, _ = configure(sess, up, w, h, is_story=True)
            results["story_pk"], results["story_taken"] = pk, taken
            time.sleep(random.uniform(2, 4))

    if args.action == "seen" and args.media_pk:
        results["seen"] = story_seen(sess, args.media_pk,
                                     args.owner_id or sess.uid,
                                     int(args.taken_at or time.time()))
    if args.action == "seen" and not args.media_pk:
        r = sess.post_form("/api/v1/feed/reels_tray/",
                           {"supported_capabilities_new": "[]",
                            "timezone_offset": sess.tz,
                            "client_session_id": str(uuid.uuid4())},
                           "IgApi: feed/reels_tray/")
        target = None
        try:
            for item in r.json().get("tray", []):
                med = item.get("items", [{}])[0]
                if med.get("pk"):
                    target = (str(med["pk"]),
                              str(med.get("user", {}).get("pk", item.get("user", {}).get("pk", ""))),
                              int(med.get("taken_at", 0)))
                    break
        except Exception:
            pass
        if target:
            results["seen"] = story_seen(sess, *target)
        else:
            print("[seen] tray me story nahi mili — upload-story use karo pehle")

    if args.action in ("upload-photo", "all"):
        img, w, h = make_test_image("post")
        up = upload_image(sess, img, w, h, kind="post")
        if up:
            pk, taken, _ = configure(sess, up, w, h, is_story=False,
                                     caption="automation test (safe to delete)")
            results["photo_pk"] = pk
            time.sleep(random.uniform(2, 4))

    if args.action in ("like", "all"):
        media_id = args.media_pk or results.get("photo_pk")
        if media_id:
            mid = media_id if "_" in media_id else f"{media_id}_{args.owner_id or sess.uid}"
            results["like"] = like(sess, mid).status_code == 200
        else:
            print("[like] --media-pk chahiye ya all chalao")

    if args.action in ("comment", "all"):
        media_id = args.media_pk or results.get("photo_pk")
        if media_id:
            mid = media_id if "_" in media_id else f"{media_id}_{args.owner_id or sess.uid}"
            time.sleep(random.uniform(2, 4))
            results["comment"] = comment(sess, mid, args.comment_text).status_code == 200
        else:
            print("[comment] --media-pk chahiye ya all chalao")

    if args.action == "all":
        if results.get("story_pk"):
            time.sleep(random.uniform(1.5, 3))
            results["seen"] = story_seen(sess, results["story_pk"], sess.uid,
                                         results["story_taken"])
        print("\n== RESULTS ==", json.dumps(results, indent=1))

    time.sleep(1.5)
    if verify(sess, "END"):
        print("\nSESSION VALID ✅ — actions ke baad bhi theek, koi challenge nahi")
    else:
        print("\nSESSION KO ISSUE ❌ — upar ke messages dekho")


if __name__ == "__main__":
    main()
