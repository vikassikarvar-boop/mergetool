#!/usr/bin/env python3
"""
ig_profile.py — PROFILE MANAGEMENT for own accounts (API-based)
================================================================
Actions (sab private API, existing Session signing ke saath):
  info                    current profile state dikhao
  bio "text"              biography set karo
  name "Full Name"        display name set karo
  dp photo.jpg            profile picture change karo
  private / public        account privacy toggle
  post photo.jpg          feed photo post (option: --caption)
  delete <media_id|pk>    apna post delete karo

USAGE:
  python ig_profile.py --cookies cookies_duck.json info
  python ig_profile.py --cookies cookies_duck.json bio "research dummy"
  python ig_profile.py --cookies cookies_duck.json dp duck.jpg
  python ig_profile.py --cookies cookies_duck.json private
  python ig_profile.py --cookies cookies_duck.json post img.jpg --caption "test"
  python ig_profile.py --cookies cookies_duck.json delete 34998837...

SIRF apne/dummy accounts par use karo.
"""
import argparse
import json
import os
import random
import sys
import time

from ig_actions import (Session, upload_image, configure, BASE,  # noqa: F401
                        send_client_events)

FRIENDLY_EDIT = "IgApi: accounts/edit_profile/"
FRIENDLY_USER = "IgApi: accounts/current_user/?edit=true"


def current_user(sess):
    r = sess.get("/api/v1/accounts/current_user/?edit=true", FRIENDLY_USER)
    if r.status_code != 200:
        sys.exit(f"current_user failed: {r.status_code} {r.text[:200]}")
    j = r.json()
    if j.get("status") != "ok":
        sys.exit(f"current_user status: {j.get('status')} {r.text[:200]}")
    return j["user"]


# ------------------------------------------------------------------ info
def cmd_info(sess):
    u = current_user(sess)
    print("=" * 60)
    print(f"  username        : @{u.get('username')}")
    print(f"  full_name       : {u.get('full_name')}")
    print(f"  pk (user id)    : {u.get('pk')}")
    print(f"  private         : {u.get('is_private')}")
    print(f"  followers       : {u.get('follower_count')}")
    print(f"  following       : {u.get('following_count')}")
    print(f"  media count     : {u.get('media_count')}")
    print(f"  biography       : {u.get('biography')!r}")
    print(f"  external_url    : {u.get('external_url') or '(none)'}")
    print(f"  email           : {u.get('email')}")
    print(f"  phone           : {u.get('phone_number') or '(none)'}")
    print(f"  profile pic     : {u.get('profile_pic_url')}")
    print("=" * 60)


# ------------------------------------------------------------------ edit
def cmd_bio(sess, text):
    """allaction capture-exact: set_biography {_uid, device_id, _uuid, raw_text}."""
    obj = {"_uid": sess.uid, "device_id": sess.android_id,
           "_uuid": sess.device_uuid, "raw_text": text}
    r = sess.post_form("/api/v1/accounts/set_biography/", obj,
                       "IgApi: accounts/set_biography/")
    try:
        j = r.json()
    except Exception:
        j = {}
    print(f"[set_biography] {r.status_code} status={j.get('status')}")
    if r.status_code != 200 or j.get("status") != "ok":
        print(f"   !! {r.text[:300]}")
        return False
    return True


def cmd_name(sess, text):
    """allaction capture-exact: update_profile_name — PLAIN form, unsigned."""
    r = sess.post_plain("/api/v1/accounts/update_profile_name/",
                        {"first_name": text, "_uuid": sess.device_uuid},
                        "IgApi: accounts/update_profile_name/")
    try:
        j = r.json()
    except Exception:
        j = {}
    print(f"[update_name  ] {r.status_code} status={j.get('status')}")
    if r.status_code != 200 or j.get("status") != "ok":
        print(f"   !! {r.text[:300]}")
        return False
    return True


def _load_image(path, kind):
    """Image load + capture-jaisi conversion: dp=JPEG, post/story=WEBP."""
    import io
    try:
        from PIL import Image
    except ImportError:
        sys.exit("PIL chahiye: pip install pillow")
    im = Image.open(path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    # max side 1440 (capture me uploads 1440 the)
    if max(im.size) > 1440:
        im.thumbnail((1440, 1440), Image.LANCZOS)
    w, h = im.size
    buf = io.BytesIO()
    if kind == "dp":
        im.save(buf, "JPEG", quality=87)
    else:
        im.save(buf, "WEBP", quality=85 if kind == "story" else 88)
    return buf.getvalue(), w, h


# ------------------------------------------------------------------ DP
def cmd_dp(sess, path):
    data, w, h = _load_image(path, "dp")
    upload_id = upload_image(sess, data, w, h, kind="dp")
    if not upload_id:
        sys.exit("DP upload fail hua")
    time.sleep(random.uniform(1.0, 2.5))
    # capture-exact PLAIN form (signed_body NAHI): _uuid, use_fbuploader,
    # remove_birthday_selfie, upload_id
    r = sess.post_plain("/api/v1/accounts/change_profile_picture/",
                        {"_uuid": sess.device_uuid, "use_fbuploader": "true",
                         "remove_birthday_selfie": "False", "upload_id": upload_id},
                        "IgApi: accounts/change_profile_picture/")
    try:
        j = r.json()
    except Exception:
        j = {}
    print(f"[change_dp    ] {r.status_code} status={j.get('status')}")
    if r.status_code == 200 and j.get("status") == "ok":
        print(f"   new dp: {j.get('user', {}).get('profile_pic_url')}")
        send_client_events(sess, module="profile_edit", n_events=1)
    else:
        print(f"   !! {r.text[:300]}")


# ------------------------------------------------------------------ privacy
def set_privacy(sess, private):
    path = "/api/v1/accounts/set_private/" if private else "/api/v1/accounts/set_public/"
    obj = {"_uid": sess.uid, "_uuid": sess.device_uuid}
    r = sess.post_form(path, obj, f"IgApi: accounts/set_{'private' if private else 'public'}/")
    try:
        j = r.json()
    except Exception:
        j = {}
    print(f"[set_{'private' if private else 'public':6s}] {r.status_code} status={j.get('status')}")
    if r.status_code == 200 and j.get("status") == "ok":
        u = j.get("user", {})
        print(f"   account ab {'PRIVATE' if u.get('is_private') else 'PUBLIC'} hai")
    else:
        print(f"   !! {r.text[:300]}")


# ------------------------------------------------------------------ post
def cmd_post(sess, path, caption):
    data, w, h = _load_image(path, "post")
    upload_id = upload_image(sess, data, w, h, kind="post")
    if not upload_id:
        sys.exit("photo upload fail hua")
    time.sleep(random.uniform(2.0, 4.0))
    pk, taken, code = configure(sess, upload_id, w, h, is_story=False, caption=caption)
    if code == 200:
        print(f"   POST LIVE: pk={pk} (media_id={pk}_{sess.uid})")
    else:
        print("   !! post configure fail")


def cmd_delete(sess, media_id):
    if "_" not in str(media_id):
        media_id = f"{media_id}_{sess.uid}"
    obj = {"media_id": media_id, "_uid": sess.uid, "_uuid": sess.device_uuid}
    r = sess.post_form(f"/api/v1/media/{media_id}/delete/", obj,
                       f"IgApi: media/{media_id}/delete/")
    try:
        j = r.json()
    except Exception:
        j = {}
    print(f"[delete       ] {r.status_code} did_delete={j.get('did_delete')}")
    if r.status_code != 200:
        print(f"   !! {r.text[:300]}")


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="Profile management (own accounts)")
    ap.add_argument("--cookies", required=True)
    ap.add_argument("--geo", default=None, help="override geo preset (IN/GB/US)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    p = sub.add_parser("bio");     p.add_argument("text")
    p = sub.add_parser("name");    p.add_argument("text")
    p = sub.add_parser("dp");      p.add_argument("image")
    sub.add_parser("private")
    sub.add_parser("public")
    p = sub.add_parser("post");    p.add_argument("image"); p.add_argument("--caption", default="")
    p = sub.add_parser("delete");  p.add_argument("media_id")
    a = ap.parse_args()

    sess = Session(a.cookies, geo=a.geo)
    print(f"session: @{sess.username} (uid={sess.uid}, geo={sess.geo['locale']}, tz={sess.tz})")

    if a.cmd == "info":    cmd_info(sess)
    elif a.cmd == "bio":   cmd_bio(sess, a.text)
    elif a.cmd == "name":  cmd_name(sess, a.text)
    elif a.cmd == "dp":    cmd_dp(sess, a.image)
    elif a.cmd == "private": set_privacy(sess, True)
    elif a.cmd == "public":  set_privacy(sess, False)
    elif a.cmd == "post":  cmd_post(sess, a.image, a.caption)
    elif a.cmd == "delete": cmd_delete(sess, a.media_id)


if __name__ == "__main__":
    main()
