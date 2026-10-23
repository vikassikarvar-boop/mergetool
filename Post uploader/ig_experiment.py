#!/usr/bin/env python3
"""
ig_experiment.py v2 — Human-paced detection research harness.
CONFINED: sirf apne account ke apne content par (comment+delete, like+unlike,
own-story seen). Real-human timing model: log-normal gaps, dwell times,
long pauses, fatigue, session windows, filler browsing.

MODES:
  --day      : poora din chalao (activity windows respect hote hain)
  --session  : ek single session abhi (testing ke liye)
  --status   : sirf session/account state check

Config: experiment_config.json (sab timings/budgets wahan tune hote hain)
State:  experiment_state.json (persistent — counts, blocks, cooldowns)
Output: experiment_log.csv + daily summary prints
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
# note: "spam" substring MAT use karo — normal response me "did_report_as_spam"
# field hota hai jo false positive deta hai

DEFAULT_CONFIG = {
    "activity_windows": [["09:30", "12:30"], ["14:30", "17:30"], ["20:30", "23:00"]],
    "sessions_per_day": [2, 4],
    "session_minutes": [10, 30],
    "actions_per_session": {"comment": [2, 8], "like": [4, 14], "seen": [1, 6]},
    "dwell_seconds": {"like": [4, 25], "comment": [8, 40], "seen": [3, 12]},
    "gap_base_median": 12.0,
    "gap_clip": [5, 60],
    "long_pause_prob": 0.07,
    "long_pause": [90, 420],
    "filler_every": [3, 7],
    "hard_daily_cap": {"comment": 30, "like": 80, "seen": 60},
    "discovery_mode": True,
    "escalation_per_day": 1.25,
    "post_block_cooldown_min": 35,
}


# ------------------------------------------------------------------ utils
def load_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def save_json(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), indent=1)


def human_gap(cfg, fatigue=0):
    """Log-normal gap + rare long pause + fatigue drift."""
    if random.random() < cfg["long_pause_prob"]:
        g = random.uniform(*cfg["long_pause"])
        print(f"   ...long pause {g:.0f}s (human distraction)")
        return g
    mu = math.log(cfg["gap_base_median"])
    g = random.lognormvariate(mu, 0.65)
    g = max(cfg["gap_clip"][0], min(cfg["gap_clip"][1], g))
    return g * (1 + 0.04 * fatigue)


def in_window(cfg, now=None):
    now = now or dt.datetime.now()
    for a, b in cfg["activity_windows"]:
        ha, ma = map(int, a.split(":")); hb, mb = map(int, b.split(":"))
        cur = now.hour * 60 + now.minute
        if ha * 60 + ma <= cur <= hb * 60 + mb:
            return True
    return False


class CSVLog:
    def __init__(self, path):
        self.path = path
        new = not os.path.exists(path)
        self.f = open(path, "a", newline="", encoding="utf-8")
        self.w = csv.writer(self.f)
        if new:
            self.w.writerow(["ts", "day", "session", "seq", "action",
                             "status", "ok", "blocked", "dwell",
                             "gap_before", "note"])

    def row(self, day, session, seq, action, status, ok, blocked,
            dwell, gap, note):
        self.w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), day, session,
                         seq, action, status, ok, blocked, round(dwell, 1),
                         round(gap, 1), note[:100]])
        self.f.flush()


# --------------------------------------------------------------- actions
def filler_browse(sess):
    """Realistic browsing noise — sirf GETs, koi write nahi."""
    try:
        sess.get("/api/v1/feed/timeline/", "IgApi: feed/timeline/",
                 params={"is_prefetch": 0, "feed_view_info_uuid": "",
                         "phone_id": "", "is_pull_to_refresh": 0,
                         "device_id": "", "timezone_offset": 19800,
                         "count": 8})
    except Exception:
        pass
    if random.random() < 0.4:
        try:
            sess.get("/api/v1/notifications/badge/", "IgApi: notifications/badge/")
        except Exception:
            pass
    bw = sess.s.headers  # noop keep-alive style
    print("   (browsing filler)")


def do_comment(sess, media_id, log, day, ses, seq, dwell, gap):
    r = A.comment(sess, media_id, f"r{random.randint(1000,9999)} 📌")
    ok = r.status_code == 200 and '"ok"' in r.text
    blocked = r.status_code == 429 or any(m in r.text for m in BLOCK_MARKERS)
    log.row(day, ses, seq, "comment", r.status_code, ok, blocked, dwell, gap,
            r.text)
    ck = ""
    if ok:
        try:
            ck = str(r.json()["comment"]["pk"])
        except Exception:
            pass
    if ck:  # delete hamesha karo — self-contained (block ho ya na ho)
        time.sleep(random.uniform(1.2, 3.5))
        uuid_ = A.TEMPLATES["mobileconfig"]["headers"].get("x-ig-device-id", "")
        rd = sess.post_form(f"/api/v1/media/{media_id}/comment/{ck}/delete/",
                            {"_uid": sess.uid, "_uuid": uuid_},
                            "IgApi: comment/delete/")
        log.row(day, ses, seq, "comment_delete", rd.status_code,
                '"ok"' in rd.text, False, 0, 0, rd.text)
    return blocked


def do_like(sess, media_id, log, day, ses, seq, dwell, gap):
    r = A.like(sess, media_id)
    ok = '"ok"' in r.text
    blocked = r.status_code == 429 or any(m in r.text for m in BLOCK_MARKERS)
    log.row(day, ses, seq, "like", r.status_code, ok, blocked, dwell, gap,
            r.text)
    time.sleep(random.uniform(1.5, 4.0))
    uuid_ = A.TEMPLATES["mobileconfig"]["headers"].get("x-ig-device-id", "")
    obj = {"media_id": media_id, "_uid": sess.uid, "_uuid": uuid_,
           "container_module": "feed_timeline", "radio_type": "wifi-none"}
    r2 = sess.post_form(f"/api/v1/media/{media_id}/unlike/", obj,
                        f"IgApi: media/{media_id}/unlike/",
                        extra_form={"d": "0"})
    log.row(day, ses, seq, "unlike", r2.status_code, '"ok"' in r2.text,
            False, 0, 0, r2.text)
    return blocked


def do_seen(sess, story_pk, taken, log, day, ses, seq, dwell, gap):
    uuid_ = A.TEMPLATES["mobileconfig"]["headers"].get("x-ig-device-id", "")
    body = {"_uid": sess.uid, "_uuid": uuid_,
            "container_module": "feed_timeline_item_header",
            "reels": {f"{story_pk}_{sess.uid}_{sess.uid}":
                      [f"{taken}_{int(time.time())}"]},
            "reel_media_skipped": {}, "nuxes": {}, "nuxes_skipped": {},
            "force_seen_story_ids": []}
    r = sess.post_form("/api/v2/media/seen/?reel=1&live_vod=0", body,
                       "IgApi: media/seen/?reel=1&live_vod=0", gzip_body=True)
    blocked = r.status_code == 429 or any(m in r.text for m in BLOCK_MARKERS)
    log.row(day, ses, seq, "seen", r.status_code, '"ok"' in r.text, blocked,
            dwell, gap, r.text)
    return blocked


# ---------------------------------------------------------------- runner
def run_session(sess, cfg, state, log, day_key, ses_idx, budgets, targets):
    """Ek human-paced session. Returns True agar block aaya."""
    A.cold_start(sess)  # app-open sequence har session ke start par
    duration = random.uniform(*cfg["session_minutes"]) * 60
    t_end = time.time() + duration
    seq = 0
    since_filler = 0
    filler_at = random.randint(*cfg["filler_every"])
    planned = []
    for act, (lo, hi) in cfg["actions_per_session"].items():
        n = random.randint(lo, hi)
        if budgets.get(act, 0) <= 0:
            n = 0
        planned += [act] * n
    random.shuffle(planned)
    print(f">> session #{ses_idx}: {len(planned)} actions planned, "
          f"~{duration/60:.0f} min")

    for act in planned:
        if budgets.get(act, 0) <= 0:
            continue
        if time.time() > t_end:
            print("   (session window khatam)")
            break
        seq += 1
        gap = human_gap(cfg, fatigue=seq)
        time.sleep(gap)
        dwell = random.uniform(*cfg["dwell_seconds"][act])
        time.sleep(dwell)

        blocked = False
        if act == "comment" and targets["media"]:
            blocked = do_comment(sess, targets["media"], log, day_key,
                                 ses_idx, seq, dwell, gap)
        elif act == "like" and targets["media"]:
            blocked = do_like(sess, targets["media"], log, day_key,
                              ses_idx, seq, dwell, gap)
        elif act == "seen" and targets["story"]:
            blocked = do_seen(sess, targets["story"], targets["story_taken"],
                              log, day_key, ses_idx, seq, dwell, gap)
        else:
            continue
        budgets[act] -= 1
        state["days"][day_key]["done"][act] = \
            state["days"][day_key]["done"].get(act, 0) + 1
        since_filler += 1
        if since_filler >= filler_at:
            time.sleep(random.uniform(3, 9))
            filler_browse(sess)
            since_filler = 0
            filler_at = random.randint(*cfg["filler_every"])
        if blocked:
            print(f"\n⛔ BLOCK mila: {act} (day count "
                  f"{state['days'][day_key]['done'][act]})")
            state["blocks"].append({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "action": act,
                                    "day_count": state["days"][day_key]["done"][act]})
            cd = cfg["post_block_cooldown_min"] * 60
            state["pause_until"] = time.time() + cd
            save_json(STATE, state)
            return True
        save_json(STATE, state)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookies", default=os.path.join(HERE, "cookies.json"))
    ap.add_argument("--config", default=os.path.join(HERE, "experiment_config.json"))
    ap.add_argument("--mode", choices=["day", "session", "status"],
                    default="status")
    args = ap.parse_args()

    global STATE
    STATE = os.path.join(HERE, "experiment_state.json")
    cfg = {**DEFAULT_CONFIG, **load_json(args.config, {})}
    state = load_json(STATE, {"day_index": 0, "last_day": "", "days": {},
                              "blocks": [], "pause_until": 0})
    sess = A.Session(args.cookies)
    print(f">> account: {sess.username} (uid {sess.uid})")

    if args.mode == "status":
        A.verify(sess, "NOW")
        print(json.dumps({"blocks": state["blocks"][-5:],
                          "days": state["days"]}, indent=1))
        return

    if time.time() < state.get("pause_until", 0):
        left = int((state["pause_until"] - time.time()) / 60)
        sys.exit(f"Cooldown active — {left} min baad try karo (block ke baad "
                 f"insaan bhi rukta hai)")

    day_key = time.strftime("%Y-%m-%d")
    if day_key != state.get("last_day"):
        state["day_index"] = state.get("day_index", 0) + (1 if state.get("last_day") else 0)
        state["last_day"] = day_key
    dk = state["days"].setdefault(day_key, {"done": {}, "sessions": 0})

    # daily budget — discovery mode me escalate
    esc = cfg["escalation_per_day"] ** state["day_index"] if cfg["discovery_mode"] else 1
    budgets = {}
    for act in ("comment", "like", "seen"):
        base_hi = cfg["actions_per_session"][act][1] * 4
        budgets[act] = min(int(base_hi * esc), cfg["hard_daily_cap"][act])
    print(f">> day #{state['day_index']} budgets: {budgets} "
          f"(already done today: {dk['done']})")

    # targets (self-contained)
    media_id, _ = None, None
    r = sess.get(f"/api/v1/feed/user/{sess.uid}/", "IgApi: feed/user/",
                 params={"count": 5})
    try:
        for it in r.json().get("items", []):
            if str(it.get("user", {}).get("pk")) == sess.uid:
                media_id = f"{it['pk']}_{sess.uid}"
                break
    except Exception:
        pass
    story_pk, story_taken = None, 0
    rs = sess.post_form("/api/v1/archive/reel/day_shells/",
                        {"include_suggested_highlights": False},
                        "IgApi: archive/reel/day_shells/")
    try:
        it0 = rs.json().get("items", [{}])[0]
        m0 = it0.get("items", [{}])[0]
        story_pk, story_taken = str(m0.get("pk", "")), int(m0.get("taken_at", 0))
    except Exception:
        pass
    targets = {"media": media_id, "story": story_pk, "story_taken": story_taken}
    print(f">> targets: media={media_id}, story={story_pk}")
    if not media_id:
        sys.exit("Apni feed post nahi mili — pehle ig_actions.py --action upload-photo")

    log = CSVLog(os.path.join(HERE, "experiment_log.csv"))
    A.verify(sess, "PRE")

    try:
        if args.mode == "session":
            run_session(sess, cfg, state, log, day_key, dk["sessions"] + 1,
                        budgets, targets)
        else:  # day
            n_sessions = random.randint(*cfg["sessions_per_day"])
            for s in range(n_sessions):
                if not in_window(cfg):
                    print("   (activity window ke bahar — session skip)")
                    break
                dk["sessions"] += 1
                blocked = run_session(sess, cfg, state, log, day_key,
                                      dk["sessions"], budgets, targets)
                if blocked:
                    break
                if s < n_sessions - 1:
                    gap = random.uniform(1800, 5400)
                    print(f">> sessions ke beech break: {gap/60:.0f} min")
                    time.sleep(gap)
    except KeyboardInterrupt:
        print("\n>> interrupted — state saved")

    save_json(STATE, state)
    print("\n=== POST STATE ===")
    A.verify(sess, "POST")
    print(f">> aaj ke counts: {dk['done']}")
    if state["blocks"]:
        print(f">> blocks so far: {json.dumps(state['blocks'][-3:])}")


if __name__ == "__main__":
    main()
