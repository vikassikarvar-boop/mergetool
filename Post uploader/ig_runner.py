#!/usr/bin/env python3
"""
ig_runner.py — FOLDER-BASED AUTOMATION RUNNER (apne/dummy accounts only)
=========================================================================
Sab kuch folders se uthata hai — cookies files me proxy/fingerprint/
language/timezone embedded hai, wahi EXACT apply hota hai.

FOLDER STRUCTURE:
  cookies/   account cookie files (device-capture format, .json)
             filename = account name  (unicorn.json -> account "unicorn")
  dp/        profile pictures (jpg/png/webp) — har account nayi pick karta hai
  post/      post + story images (jpg/png/webp) — next-unused pick hota hai
  bio/       <accountname>.txt ya bio.txt (fallback) — bio text

USAGE:
  python ig_runner.py list                          # accounts + inventory
  python ig_runner.py info                          # sab accounts

  # SIRF EK action:
  python ig_runner.py dp                            # sirf dp upload
  python ig_runner.py bio                           # sirf bio
  python ig_runner.py post --caption "hello"        # sirf post
  python ig_runner.py private                       # sirf private

  # MULTIPLE actions ek saath (order me chalte hain):
  python ig_runner.py dp post                       # dp + post
  python ig_runner.py bio dp post                   # bio + dp + post
  python ig_runner.py story post private            # story + post + private

  python ig_runner.py dp --account unicorn          # sirf ek account
State: runner_state.json (used images track karta hai — repeat nahi hote)
"""
import argparse
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DIRS = {k: os.path.join(HERE, k) for k in ("cookies", "dp", "post", "story", "bio")}
STATE_FILE = os.path.join(HERE, "runner_state.json")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")

from ig_actions import Session, upload_image, configure  # noqa: E402
from ig_profile import (cmd_info, cmd_bio, cmd_dp, cmd_post,  # noqa: E402
                        set_privacy, _load_image)


# ---------------------------------------------------------------- helpers
def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE, encoding="utf-8"))
    return {"used": {}}


def save_state(st):
    json.dump(st, open(STATE_FILE, "w", encoding="utf-8"), indent=1)


def accounts():
    """cookies/ folder ke saare valid JSON files -> [(name, path)]"""
    out = []
    for fn in sorted(os.listdir(DIRS["cookies"])):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(DIRS["cookies"], fn)
        try:
            json.load(open(p, encoding="utf-8"))
            out.append((os.path.splitext(fn)[0], p))
        except Exception as e:
            print(f"⚠️  {fn} parse fail: {e}")
    return out


def pick_image(acct, purpose):
    """purpose: 'dp' | 'post' | 'story' — folders me se next-UNUSED file."""
    folders = {"dp": [DIRS["dp"]], "post": [DIRS["post"]],
               "story": [DIRS["story"], DIRS["post"]]}[purpose]
    st = load_state()
    used = set(st["used"].get(acct, {}).get(purpose, []))
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        cands = sorted(f for f in os.listdir(folder)
                       if f.lower().endswith(IMG_EXT))
        avail = [f for f in cands if f not in used]
        if avail:
            pick = avail[0]      # oldest-first, no repeat
            st["used"].setdefault(acct, {}).setdefault(purpose, []).append(pick)
            save_state(st)
            return os.path.join(folder, pick)
        if cands:
            print(f"⚠️  {purpose}: saari files use ho chuki hain ({len(cands)}) — reuse")
            return os.path.join(folder, cands[0])
    return None


def pick_bio(acct, username):
    for name in (f"{acct}.txt", f"{username}.txt", "bio.txt"):
        p = os.path.join(DIRS["bio"], name)
        if os.path.exists(p):
            txt = open(p, encoding="utf-8").read().strip()
            if txt:
                return txt
    return None


def do_action(sess, acct, action, caption, count=1):
    """Ek action execute karo. True return kare to success."""
    if action == "info":
        cmd_info(sess)
        return True
    elif action == "bio":
        txt = pick_bio(acct, sess.username)
        if not txt:
            print("  !! bio/ me txt file nahi mili — skip")
            return False
        print(f"  bio text: {txt[:60]!r}")
        return cmd_bio(sess, txt)
    elif action == "dp":
        img = pick_image(acct, "dp")
        if not img:
            print("  !! dp/ folder me image nahi — skip"); return False
        print(f"  dp image: {os.path.basename(img)}")
        cmd_dp(sess, img)
        return True
    elif action == "post":
        n = max(1, count if count else 1)
        for k in range(n):
            if n > 1:
                print(f"\n   [post {k+1}/{n}]")
            img = pick_image(acct, "post")
            if not img:
                print("  !! post/ folder me image nahi — skip"); return False
            print(f"  post image: {os.path.basename(img)}")
            cmd_post(sess, img, caption or "")
            if k < n - 1:
                gap = random.uniform(120, 300)   # posts ke beech 2-5 min
                print(f"  ... next post se pehle {gap:.0f}s gap ...")
                time.sleep(gap)
        return True
    elif action == "story":
        n = max(1, count if count else 1)
        for k in range(n):
            if n > 1:
                print(f"\n   [story {k+1}/{n}]")
            img = pick_image(acct, "story")
            if not img:
                print("  !! story/ ya post/ folder me image nahi — skip"); return False
            print(f"  story image: {os.path.basename(img)}")
            data, w, h = _load_image(img, "story")
            up = upload_image(sess, data, w, h, kind="story")
            if up:
                time.sleep(random.uniform(2.0, 4.0))
                pk, taken, code = configure(sess, up, w, h, is_story=True)
                if code == 200:
                    print(f"   STORY LIVE: pk={pk}")
            if k < n - 1:
                gap = random.uniform(120, 300)
                print(f"  ... next story se pehle {gap:.0f}s gap ...")
                time.sleep(gap)
        return True
    elif action in ("private", "public"):
        set_privacy(sess, action == "private")
        return True
    return False


def run_on(acct, path, actions, caption, count=1):
    print("\n" + "=" * 62)
    print(f"ACCOUNT: {acct}  ({path})")
    print(f"ACTIONS: {' + '.join(actions)}" + (f"  (count={count})" if count > 1 else ""))
    print("=" * 62)
    sess = Session(path)
    print(f"  @{sess.username} uid={sess.uid} geo={sess.geo['locale']} "
          f"tz={sess.tz} proxy={'yes' if sess.proxy_configured else 'NO!'}")

    for i, action in enumerate(actions):
        print(f"\n--- [{i+1}/{len(actions)}] {action.upper()} ---")
        do_action(sess, acct, action, caption, count)
        if i < len(actions) - 1:
            gap = random.uniform(8, 20)   # actions ke beech human gap
            print(f"  ... {gap:.0f}s gap ...")
            time.sleep(gap)
    time.sleep(random.uniform(2, 4))


# ------------------------------------------------------------------ list
def do_list():
    print("== ACCOUNTS (cookies/ folder) ==")
    accs = accounts()
    if not accs:
        print("  (khali hai — cookie files yahan dalo)")
    for name, path in accs:
        d = json.load(open(path, encoding="utf-8"))
        ai = d.get("account_info", {})
        fp = d.get("fingerprint", {})
        px = fp.get("proxy_url", "")
        sess_name = px.split("session-")[1].split("_")[0] if "session-" in px else "?"
        print(f"  {name:12s} @{d.get('username','?'):20s} "
              f"pk={ai.get('pk')} country={d.get('country')} "
              f"tz={fp.get('timezone_offset')} proxy_session={sess_name} "
              f"media={ai.get('media_count')}")
    print("\n== INVENTORY ==")
    for k in ("dp", "post", "story"):
        if os.path.isdir(DIRS[k]):
            files = [f for f in os.listdir(DIRS[k]) if f.lower().endswith(IMG_EXT)]
            print(f"  {k:6s}: {len(files)} images")
    bio_files = os.listdir(DIRS["bio"]) if os.path.isdir(DIRS["bio"]) else []
    print(f"  bio   : {len(bio_files)} txt files {bio_files[:5]}")


# ------------------------------------------------------------------ main
MENU_ACTIONS = {
    "1": ("list",), "2": ("info",), "3": ("bio",), "4": ("dp",),
    "5": ("post",), "6": ("story",), "7": ("private",), "8": ("public",),
}


def prompt_account_choice(accs):
    """Returns selected [(name, path)] — user picks one ya 'all'."""
    print("\nACCOUNTS:")
    for i, (name, path) in enumerate(accs, 1):
        print(f"   {i}. {name}")
    print(f"   0. SAB accounts ({len(accs)})")
    while True:
        ch = input("Kis account par? [0=all]: ").strip()
        if ch in ("", "0"):
            return accs
        if ch.isdigit() and 1 <= int(ch) <= len(accs):
            return [accs[int(ch) - 1]]
        print("   sahi number dalo")


def menu():
    while True:
        print("\n" + "=" * 46)
        print("   IG RESEARCH TOOLKIT — MENU")
        print("=" * 46)
        print("  1. List (accounts + inventory)")
        print("  2. Info (profile status)")
        print("  3. Bio change")
        print("  4. DP upload")
        print("  5. Post upload  (kitne posts: poochha jayega)")
        print("  6. Story upload (kitni stories: poochha jayega)")
        print("  7. Account PRIVATE karo")
        print("  8. Account PUBLIC karo")
        print("  9. Combo (multiple actions ek saath)")
        print("  0. Exit")
        ch = input("\nChoice: ").strip()

        if ch == "0":
            print("Bye!")
            return
        accs = accounts()
        if not accs:
            print("⚠️  cookies/ folder khali hai — pehle cookie files dalo")
            continue

        if ch == "1":
            do_list()
            continue
        if ch == "9":
            print("Combo ke liye numbers space se likho (e.g. 3 4 5)")
            print("  2=info 3=bio 4=dp 5=post 6=story 7=private 8=public")
            sel = input("Actions: ").split()
            actions = []
            for s in sel:
                if s in MENU_ACTIONS and MENU_ACTIONS[s][0] != "list":
                    actions += MENU_ACTIONS[s]
            if not actions:
                print("kuch valid select nahi hua"); continue
        elif ch in MENU_ACTIONS:
            actions = list(MENU_ACTIONS[ch])
        else:
            print("valid choice dalo"); continue

        selected = prompt_account_choice(accs)

        count = 1
        if any(x in actions for x in ("post", "story")):
            c = input("Kitne uploads? [1]: ").strip()
            if c.isdigit() and int(c) > 0:
                count = int(c)
        caption = ""
        if "post" in actions:
            caption = input("Caption (khali chhod sakte ho): ").strip()

        print(f"\n>>> RUN: {' + '.join(actions).upper()}"
              + (f" x{count}" if count > 1 else "")
              + f" — {len(selected)} account(s)")
        for i, (name, path) in enumerate(selected):
            run_on(name, path, actions, caption, count)
            if i < len(selected) - 1:
                gap = random.uniform(45, 90)
                print(f"\n... accounts ke beech {gap:.0f}s gap ...")
                time.sleep(gap)
        print("\nDONE ✅")


def main():
    ap = argparse.ArgumentParser(description="Folder-based IG automation runner")
    ap.add_argument("actions", nargs="*",
                    choices=["list", "info", "bio", "dp", "post",
                             "story", "private", "public"],
                    help="ek ya zyada actions (e.g. dp post). Khali = interactive menu")
    ap.add_argument("--account", default=None,
                    help="sirf is account par (default: cookies/ ke sab accounts)")
    ap.add_argument("--caption", default="", help="post caption")
    ap.add_argument("--count", type=int, default=1,
                    help="post/story kitne upload karne hain (default 1)")
    a = ap.parse_args()

    for d in DIRS.values():
        os.makedirs(d, exist_ok=True)

    if not a.actions:          # koi argument nahi -> interactive menu
        menu()
        return

    if "list" in a.actions:
        do_list()
        return
    actions = a.actions

    accs = accounts()
    if not accs:
        sys.exit("cookies/ folder khali hai — pehle cookie files dalo")
    if a.account:
        accs = [(n, p) for n, p in accs if n == a.account]
        if not accs:
            sys.exit(f"account '{a.account}' cookies/ me nahi mila")

    print(f"MODE: {' + '.join(actions).upper()}"
          + (f" x{a.count}" if a.count > 1 else "")
          + f" — {len(accs)} account(s)")
    for i, (name, path) in enumerate(accs):
        run_on(name, path, actions, a.caption, a.count)
        if i < len(accs) - 1:
            gap = random.uniform(45, 90)
            print(f"\n... accounts ke beech {gap:.0f}s gap ...")
            time.sleep(gap)
    print("\nDONE ✅")


if __name__ == "__main__":
    main()
