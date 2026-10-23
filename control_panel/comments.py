"""
Comment Blast: ek post par N comments, active accounts me round-robin (har account ek-ek comment).
Roster (active accounts) hub me manage hota hai - add/remove/active toggle - tool files untouched.
"""
import json, os, random, re, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ROSTER = os.path.join(DATA, "roster.json")
HUB_COOKIES = os.path.join(DATA, "cookies")
HISTORY = os.path.join(DATA, "comment_history.json")
os.makedirs(HUB_COOKIES, exist_ok=True)
SOFT = ("commenting too fast", "feedback_required", "challenge_required", "login_required",
        "checkpoint", "comment_not_allowed", "spam", "session invalid")


def load_roster():
    try:
        with open(ROSTER, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_roster(r):
    os.makedirs(DATA, exist_ok=True)
    with open(ROSTER, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1, ensure_ascii=False)


def scan_sources(dirs):
    """dirs: [(label, path)] -> {name: {name, cookies, source}} (pehle mile wale ko priority)"""
    found = {}
    for label, d in dirs:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            m = re.fullmatch(r"cookies_(.+)\.json", f)
            if m and m.group(1) not in found:
                found[m.group(1)] = {"name": m.group(1), "cookies": os.path.join(d, f), "source": label}
    return found


def roster_view(dirs):
    avail = scan_sources(dirs)
    roster = load_roster()
    for r in roster:
        r["exists"] = os.path.isfile(r["cookies"])
    inr = {r["name"] for r in roster}
    return {"roster": roster, "available": [v for k, v in avail.items() if k not in inr]}


def roster_add(name, dirs):
    avail = scan_sources(dirs)
    if name not in avail:
        raise ValueError("cookie file nahi mili")
    r = load_roster()
    if any(x["name"] == name for x in r):
        return
    r.append({"name": name, "cookies": avail[name]["cookies"], "source": avail[name]["source"], "active": True})
    save_roster(r)


def roster_set(name, active=None, remove=False):
    r = load_roster()
    if remove:
        r = [x for x in r if x["name"] != name]
    else:
        for x in r:
            if x["name"] == name and active is not None:
                x["active"] = bool(active)
    save_roster(r)


def save_uploaded_cookie(raw):
    d = json.loads(raw.decode("utf-8"))
    name = d.get("username")
    if not name or "cookies" not in d:
        raise ValueError("ye valid cookie file nahi (username/cookies missing)")
    safe = re.sub(r"[^\w.\-]", "_", name)
    with open(os.path.join(HUB_COOKIES, f"cookies_{safe}.json"), "wb") as f:
        f.write(raw)
    return safe


def split_comments(txt):
    seen, out = set(), []
    for l in (txt or "").splitlines():
        l = l.strip()
        if l and l.lower() not in seen:
            seen.add(l.lower()); out.append(l)
    return out


def _log_history(rows):
    try:
        h = json.load(open(HISTORY, encoding="utf-8"))
    except Exception:
        h = []
    h.extend(rows)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(h[-2000:], f, ensure_ascii=False, indent=0)


def plan_assign(comments, accounts, shuffle=False):
    accs = list(accounts)
    if shuffle:
        random.shuffle(accs)
    return [(c, accs[i % len(accs)]) for i, c in enumerate(comments)] if accs else []


def run_comments(job, spec, matrix_dir, procs):
    log = job["lines"].append
    rows = job["progress"]
    dry, fast = bool(spec.get("dry")), bool(spec.get("fast"))
    gap = (3, 6) if fast else (max(10, int(spec.get("gap_min", 60))), max(15, int(spec.get("gap_max", 180))))
    stopped = lambda: job.get("_stopped")
    accounts = spec["accounts"]                # [{name,cookies}]
    dead, fails = set(), {}
    byname = {a["name"]: a for a in accounts}
    order = [a["name"] for a in accounts]
    url = spec["url"]
    hist = []

    def nap(why):
        s = random.uniform(*gap)
        log(f"   ... {int(s)}s wait ({why})")
        t = time.time() + (0.2 if dry else s)
        while time.time() < t and not stopped():
            time.sleep(0.5)

    def attempt(name, text, row):
        cookies = byname[name]["cookies"]
        log(f"[{name}] > comment: {text}")
        if dry:
            log("   (dry-run: kuch bheja nahi)"); return True, ""
        fd, tf = tempfile.mkstemp(suffix=".txt"); os.close(fd)
        with open(tf, "w", encoding="utf-8") as f:
            f.write(text)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        argv = [sys.executable, "-u", os.path.join(HERE, "comment_worker.py"), matrix_dir, cookies, url, tf]
        try:
            p = subprocess.Popen(argv, cwd=matrix_dir, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
            procs[(job["id"], name)] = p
            out = []
            for raw in iter(p.stdout.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                out.append(line); log("   " + line)
            p.wait()
        finally:
            procs.pop((job["id"], name), None)
            try: os.remove(tf)
            except OSError: pass
        txt = "\n".join(out)
        low = txt.lower()
        ok = "HUB_COMMENT_OK" in txt
        if not dry:
            try:
                import health
                c = health.load_cache()
                if ok:
                    c[name] = {"status": "ALIVE", "detail": "comment live", "http": 200, "checked_at": time.time()}
                    health.save_cache(c)
                elif "accounts/suspended" in low or "suspended" in low or ("disabled" in low and "account" in low):
                    c[name] = {"status": "SUSPENDED", "detail": "account suspended/disabled", "http": 400, "checked_at": time.time()}
                    health.save_cache(c)
                elif "login_required" in low:
                    c[name] = {"status": "EXPIRED", "detail": "cookie/session expire", "http": 403, "checked_at": time.time()}
                    health.save_cache(c)
                elif "challenge_required" in low or "checkpoint" in low:
                    c[name] = {"status": "CHALLENGE", "detail": "checkpoint/challenge required", "http": 400, "checked_at": time.time()}
                    health.save_cache(c)
            except Exception:
                pass
        if not ok and any(m in txt.lower() for m in SOFT):
            dead.add(name); log(f"   !! [{name}] is run me band (limit/challenge/session) - baaki accounts se chalega")
        return ok, txt[-200:]

    rr = 0
    for i, row in enumerate(rows):
        if stopped():
            row["status"] = "STOPPED"; continue
        text = row["text"]
        done = False
        tried = 0
        while tried < 2 and not done and not stopped():
            alive = [n for n in order if n not in dead]
            if not alive:
                log("sab accounts band - campaign ruk gaya"); break
            name = alive[rr % len(alive)]
            rr += 1; tried += 1
            row["account"] = name; row["status"] = "RUNNING"
            if i > 0 and tried == 1:
                nap("comments ke beech gap")
                if stopped(): break
            ok, tail = attempt(name, text, row)
            if ok:
                row["status"] = "OK"; done = True
                fails[name] = 0
                hist.append({"t": time.time(), "post": url, "account": name, "text": text})
            else:
                fails[name] = fails.get(name, 0) + 1
                if fails[name] >= 2:
                    dead.add(name)
                row["status"] = "FAIL"; row["note"] = tail[-80:]
        if not done and row["status"] == "RUNNING":
            row["status"] = "STOPPED"
        if not [n for n in order if n not in dead]:
            for r2 in rows[i + 1:]:
                if r2["status"] == "QUEUED":
                    r2["status"] = "SKIPPED"
            break
    if hist and not dry:
        _log_history(hist)
    okc = sum(1 for r in rows if r["status"] == "OK")
    log(f"\nCOMMENTS KHATAM: {okc}/{len(rows)} posted" + (" (dry-run)" if dry else ""))
    if stopped():
        return "STOPPED"
    return "DONE" if okc == len(rows) else ("PARTIAL" if okc else "FAILED")
