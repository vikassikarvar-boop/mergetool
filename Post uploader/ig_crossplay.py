#!/usr/bin/env python3
"""
ig_crossplay.py — Multi-account CROSS-interaction research engine.
Apne 2-3 dummy accounts ke beech realistic interactions:
  camel -> duck ki post like/comment, bear -> camel ki story view, etc.

Design:
  * Har account: apna cookies file, apna device profile, apna proxy (alag IP)
  * Ek session = ek hi account (insaan ek waqt me ek account chalata hai)
  * Inventory: har account ke 3 posts + roz 1 story (targets ke liye)
  * Comments: unique text generator — kabhi repeat NAHI (duplicate = spam signal)
  * Likes: distribute across posts, same target repeat NAHI
  * Wahi human timing model: log-normal gaps, dwell, long pauses, windows

FILES:
  accounts.json          — account list (cookies path + proxy per account)
  crossplay_config.json  — timing/budget tuning
  crossplay_state.json   — persistent state (counts, liked pairs, blocks)
  crossplay_log.csv      — har action ka log (actor -> target)

USAGE:
  python ig_crossplay.py --mode status
  python ig_crossplay.py --mode inventory      # posts/stories ensure karo
  python ig_crossplay.py --mode session        # ek test session
  python ig_crossplay.py --mode day            # full day research run
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import random
import sys
import time

import ig_actions as A

HERE = A.HERE
BLOCK_MARKERS = ("rate_limit_error", "feedback_required", "action_block",
                 "challenge_required", "checkpoint_required", "sentry_block",
                 "try again later", "comment_not_allowed")

DEFAULT_CFG = {
    "activity_windows": [["09:30", "12:30"], ["14:30", "17:30"], ["20:30", "23:00"]],
    "sessions_per_day": [3, 5],
    "session_minutes": [8, 22],
    "actions_per_session": {"comment": [2, 6], "like": [4, 12], "seen": [1, 4]},
    "dwell_seconds": {"like": [4, 25], "comment": [8, 40], "seen": [3, 12]},
    "gap_base_median": 14.0,
    "gap_clip": [6, 65],
    "long_pause_prob": 0.07,
    "long_pause": [90, 420],
    "filler_every": [3, 6],
    "posts_per_account": 3,
    "hard_daily_cap": {"comment": 25, "like": 60, "seen": 40},
    "discovery_mode": True,
    "escalation_per_day": 1.2,
    "post_block_cooldown_min": 40,
}

OPENERS = ["nice", "love this", "wow", "haha", "omg", "great shot", "so cool",
           "damn", "lit", "clean", "sheesh", "facts", "real", "yo", "hey"]
MIDS = ["one 🔥", "vibes 😄", "picture 👌", "moment ✨", "work 💯", "click 📸",
        "post 🙌", "frame 🎯", "shot 🤯", "energy ⚡", "style 😎", "idea 💡"]
TAILS = ["", "!", "!!", " fr", " tho", " no cap", " 😅", " 👀", " 💀", " 🫡",
         " keep it up", " respect"]


def load_json(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def save_json(p, o):
    json.dump(o, open(p, "w", encoding="utf-8"), indent=1)


def make_comment(state):
    """Unique comment — recent history se kabhi match nahi."""
    recent = set(state.get("recent_comments", [])[-80:])
    for _ in range(50):
        t = f"{random.choice(OPENERS)} {random.choice(MIDS)}{random.choice(TAILS)}".strip()
        if t not in recent:
            return t
    return f"{random.choice(OPENERS)} {random.choice(MIDS)}{random.choice(TAILS)} {random.randint(10,99)}"


def human_gap(cfg, fatigue=0):
    if random.random() < cfg["long_pause_prob"]:
        g = random.uniform(*cfg["long_pause"])
        print(f"   ...long pause {g:.0f}s")
        return g
    g = random.lognormvariate(math.log(cfg["gap_base_median"]), 0.65)
    return max(cfg["gap_clip"][0], min(cfg["gap_clip"][1], g)) * (1 + 0.04 * fatigue)


def in_window(cfg):
    now = dt.datetime.now()
    for a, b in cfg["activity_windows"]:
        ha, ma = map(int, a.split(":")); hb, mb = map(int, b.split(":"))
        if ha * 60 + ma <= now.hour * 60 + now.minute <= hb * 60 + mb:
            return True
    return False


def secs_to_next_window(cfg):
    """0 = abhi window me ho; N>0 = N sec baad agli window; None = aaj ki
    saari windows khatam."""
    now = dt.datetime.now()
    cur = now.hour * 60 + now.minute
    starts = []
    for a, b in cfg["activity_windows"]:
        ha, ma = map(int, a.split(":")); hb, mb = map(int, b.split(":"))
        if ha * 60 + ma <= cur <= hb * 60 + mb:
            return 0
        starts.append(ha * 60 + ma)
    future = [s for s in starts if s > cur]
    return (min(future) - cur) * 60 if future else None


def is_blocked(resp):
    return resp.status_code == 429 or any(m in resp.text for m in BLOCK_MARKERS)


class CSVLog:
    def __init__(self, path):
        new = not os.path.exists(path)
        self.f = open(path, "a", newline="", encoding="utf-8")
        self.w = csv.writer(self.f)
        if new:
            self.w.writerow(["ts", "day", "session", "actor", "action",
                             "target_acct", "target_id", "status", "ok",
                             "blocked", "dwell", "gap", "note"])

    def row(self, *a):
        self.w.writerow(a); self.f.flush()


# ------------------------------------------------------------- inventory
def own_posts(sess):
    r = sess.get(f"/api/v1/feed/user/{sess.uid}/", "IgApi: feed/user/",
                 params={"count": 12})
    try:
        return [f"{it['pk']}_{sess.uid}" for it in r.json().get("items", [])
                if str(it.get("user", {}).get("pk")) == sess.uid]
    except Exception:
        return []


def ensure_inventory(sess, cfg, log):
    """3 posts + 1 story per account."""
    posts = own_posts(sess)
    need = max(0, cfg["posts_per_account"] - len(posts))
    for i in range(need):
        img, w, h = A.make_test_image()
        up = A.upload_image(sess, img, w, h, is_story=False)
        if up:
            A.configure(sess, up, w, h, is_story=False,
                        caption=f"test {time.strftime('%d%m')}")
        time.sleep(random.uniform(8, 20))
    img, w, h = A.make_test_image(story=True)
    up = A.upload_image(sess, img, w, h, is_story=True)
    if up:
        A.configure(sess, up, w, h, is_story=True)
    print(f">> inventory done: {sess.username}")


def get_today_story(sess):
    r = sess.post_form("/api/v1/archive/reel/day_shells/",
                       {"include_suggested_highlights": False},
                       "IgApi: archive/reel/day_shells/")
    try:
        m0 = r.json().get("items", [{}])[0].get("items", [{}])[0]
        if m0.get("pk"):
            return str(m0["pk"]), int(m0.get("taken_at", 0))
    except Exception:
        pass
    return None, 0


# --------------------------------------------------------------- session
def run_actor_session(actor, others, cfg, state, log, day, ses_idx):
    """Ek insaan ek account chalata hai — actor ke actions, targets = others."""
    acct = actor["name"]
    sess = actor["sess"]
    # APP OPEN — real user app kholta hai, startup sequence fire hota hai
    A.cold_start(sess)
    budgets = actor["budgets"]
    duration = random.uniform(*cfg["session_minutes"]) * 60
    t_end = time.time() + duration
    planned = []
    for act, (lo, hi) in cfg["actions_per_session"].items():
        planned += [act] * random.randint(lo, hi)
    random.shuffle(planned)
    print(f"\n>> SESSION #{ses_idx}: actor={acct}, {len(planned)} actions, "
          f"~{duration/60:.0f} min")
    seq = 0; since_filler = 0
    filler_at = random.randint(*cfg["filler_every"])
    used_targets = state.setdefault("used_pairs", [])[-30:]

    for act in planned:
        if time.time() > t_end:
            print("   (session window khatam)"); break
        if budgets.get(act, 0) <= 0:
            continue
        # target pick — koi doosra account, recent pair avoid
        cands = []
        for o in others:
            if act == "seen":
                if o.get("story") and o["story"][0]:
                    pair = f"{acct}->{o['name']}:seen:{o['story'][0]}"
                    if pair not in used_targets:
                        cands.append((o, pair))
            else:
                for mid in o["posts"]:
                    pair = f"{acct}->{o['name']}:{act}:{mid}"
                    if pair not in used_targets:
                        cands.append((o, pair))
        if not cands:
            print(f"   ({act}: fresh target nahi mila, skip)"); continue
        target, pair = random.choice(cands)
        tmid = target["story"][0] if act == "seen" else pair.rsplit(":", 1)[1]

        seq += 1
        gap = human_gap(cfg, fatigue=seq)
        time.sleep(gap)
        dwell = random.uniform(*cfg["dwell_seconds"][act])
        time.sleep(dwell)

        blocked = False; status = 0; ok = False; note = ""
        if act == "like":
            r = A.like(sess, tmid)
            status, ok, note = r.status_code, '"ok"' in r.text, r.text[:100]
            blocked = is_blocked(r)
        elif act == "comment":
            txt = make_comment(state)
            r = A.comment(sess, tmid, txt)
            status, ok, note = r.status_code, '"ok"' in r.text, r.text[:100]
            blocked = is_blocked(r)
            if ok:
                state.setdefault("recent_comments", []).append(txt)
        elif act == "seen":
            pk, taken = target["story"]
            body = {"_uid": sess.uid, "_uuid": sess.device_uuid,
                    "container_module": "feed_timeline_item_header",
                    "reels": {f"{pk}_{target['uid']}_{target['uid']}":
                              [f"{taken}_{int(time.time())}"]},
                    "reel_media_skipped": {}, "nuxes": {}, "nuxes_skipped": {},
                    "force_seen_story_ids": []}
            r = sess.post_form("/api/v2/media/seen/?reel=1&live_vod=0", body,
                               "IgApi: media/seen/?reel=1&live_vod=0",
                               gzip_body=True)
            status, ok, note = r.status_code, '"ok"' in r.text, r.text[:80]
            blocked = is_blocked(r)

        log.row(time.strftime("%Y-%m-%d %H:%M:%S"), day, ses_idx, acct, act,
                target["name"], tmid, status, ok, blocked, round(dwell, 1),
                round(gap, 1), note)
        print(f"   #{seq:02d} {acct} {act:7s} -> {target['name']}: "
              f"{status} {'⛔BLOCK' if blocked else 'ok'}")
        used_targets.append(pair)
        budgets[act] -= 1
        d = state["days"][day]["done"].setdefault(acct, {})
        d[act] = d.get(act, 0) + 1
        since_filler += 1
        if since_filler >= filler_at:
            time.sleep(random.uniform(3, 9))
            try:
                sess.get("/api/v1/feed/timeline/", "IgApi: feed/timeline/",
                         params={"count": 8})
            except Exception:
                pass
            since_filler = 0
            filler_at = random.randint(*cfg["filler_every"])
        if blocked:
            state["blocks"].append({"ts": time.strftime("%F %T"), "actor": acct,
                                    "action": act,
                                    "count_today": d[act]})
            state["cooldown"][acct] = time.time() + cfg["post_block_cooldown_min"] * 60
            print(f"   ⛔ {acct} par block — cooldown set")
            break
        save_json("crossplay_state.json", state)
    save_json("crossplay_state.json", state)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["status", "inventory", "session", "day"],
                    default="status")
    ap.add_argument("--accounts", default=os.path.join(HERE, "accounts.json"))
    ap.add_argument("--config", default=os.path.join(HERE, "crossplay_config.json"))
    ap.add_argument("--actor", help="sirf ye account actions karega; baaki sab "
                    "sirf TARGET honge (risk ek hi account par)")
    args = ap.parse_args()

    cfg = {**DEFAULT_CFG, **load_json(args.config, {})}
    acc_cfg = load_json(args.accounts, None)
    if not acc_cfg or len(acc_cfg.get("accounts", [])) < 2:
        sys.exit("accounts.json me kam se kam 2 accounts chahiye")
    state = load_json("crossplay_state.json",
                      {"day_index": 0, "last_day": "", "days": {}, "blocks": [],
                       "cooldown": {}, "recent_comments": [], "used_pairs": []})

    accounts = []
    for a in acc_cfg["accounts"]:
        if not os.path.exists(a["cookies"]):
            print(f"!! {a['name']}: {a['cookies']} nahi mila — skip")
            continue
        sess = A.Session(a["cookies"], geo=a.get("geo"))
        if a.get("proxy"):
            sess.s.proxies = {"http": a["proxy"], "https": a["proxy"]}
        accounts.append({"name": a["name"], "sess": sess, "uid": sess.uid,
                         "posts": [], "story": None})
        print(f">> {a['name']}: geo={sess.geo['startup_country']} "
              f"tz={sess.tz} locale={sess.locale}")
    if len(accounts) < 2:
        sys.exit("Kam se kam 2 valid accounts chahiye")
    print(f">> accounts loaded: {[x['name'] for x in accounts]}")

    ok_all = True
    for x in accounts:
        if not A.verify(x["sess"], x["name"][:5]):
            x["dead"] = True; ok_all = False
    accounts = [x for x in accounts if not x.get("dead")]
    if len(accounts) < 2:
        sys.exit("2+ valid sessions nahi bachi")

    if args.mode == "status":
        print(json.dumps({"blocks": state["blocks"][-6:], "days": state["days"]},
                         indent=1, default=str))
        return

    if args.mode == "inventory":
        for x in accounts:
            ensure_inventory(x["sess"], cfg, None)
        print("inventory done — ab --mode session/day chalao")
        return

    day = time.strftime("%Y-%m-%d")
    if day != state.get("last_day"):
        state["day_index"] += 1 if state.get("last_day") else 0
        state["last_day"] = day
    state["days"].setdefault(day, {"done": {}, "sessions": 0})

    # per-account budgets (discovery escalation)
    esc = cfg["escalation_per_day"] ** state["day_index"] if cfg["discovery_mode"] else 1
    for x in accounts:
        x["budgets"] = {}
        for act in ("comment", "like", "seen"):
            base = cfg["actions_per_session"][act][1] * 3
            x["budgets"][act] = min(int(base * esc), cfg["hard_daily_cap"][act])
        x["posts"] = own_posts(x["sess"])
        x["story"] = get_today_story(x["sess"])
        if not x["story"][0]:
            img, w, h = A.make_test_image(story=True)
            up = A.upload_image(x["sess"], img, w, h, is_story=True)
            if up:
                pk, taken, st = A.configure(x["sess"], up, w, h, is_story=True)
                if pk and st == 200:
                    x["story"] = (pk, taken)  # upload se direct capture
        if not x["story"][0]:
            x["story"] = get_today_story(x["sess"])
        print(f">> {x['name']}: {len(x['posts'])} posts, story={x['story'][0]}, "
              f"budgets={x['budgets']}")

    log = CSVLog("crossplay_log.csv")
    try:
        if args.mode == "session":
            if args.actor:
                actor = next((x for x in accounts if x["name"] == args.actor), None)
                if not actor:
                    sys.exit(f"actor '{args.actor}' accounts.json me nahi mila")
                print(f">> FIXED ACTOR MODE: sirf {args.actor} actions karega")
            else:
                actor = random.choice(accounts)
            run_actor_session(actor, [x for x in accounts if x is not actor],
                              cfg, state, log, day, state["days"][day]["sessions"] + 1)
        else:
            # DAY-24 MODE: poore din ke windows cover karo — bahar wait,
            # window aane par resume. Ek command = poora din.
            target_sessions = random.randint(*cfg["sessions_per_day"])
            done = 0
            print(f">> day mode: {target_sessions} sessions planned across windows")
            while done < target_sessions:
                wait = secs_to_next_window(cfg)
                if wait is None:
                    print(">> aaj ki saari windows khatam — day complete")
                    break
                if wait > 0:
                    print(f">> window ke bahar — {wait/60:.0f} min wait "
                          f"(phone side me, script soya hua)")
                    time.sleep(wait)
                    continue
                avail = [x for x in accounts
                         if time.time() >= state["cooldown"].get(x["name"], 0)]
                if args.actor:
                    avail = [x for x in avail if x["name"] == args.actor]
                if not avail:
                    print(">> actor cooldown me — 15 min baad recheck")
                    time.sleep(900)
                    continue
                actor = avail[0] if args.actor else random.choice(avail)
                done += 1
                state["days"][day]["sessions"] += 1
                run_actor_session(actor, [x for x in accounts if x is not actor],
                                  cfg, state, log, day, state["days"][day]["sessions"])
                save_json("crossplay_state.json", state)
                if done < target_sessions:
                    gap = random.uniform(1500, 4500)
                    print(f">> sessions ke beech break: {gap/60:.0f} min")
                    time.sleep(gap)
    except KeyboardInterrupt:
        print("\n>> interrupted — state saved")
    save_json("crossplay_state.json", state)
    print("\n=== POST STATE ===")
    for x in accounts:
        A.verify(x["sess"], x["name"][:5])
    print(f">> aaj: {json.dumps(state['days'][day]['done'])}")


if __name__ == "__main__":
    main()
