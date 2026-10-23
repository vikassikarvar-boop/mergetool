"""
Bulk campaign engine (hub side). Post uploader ki koi file modify nahi hoti -
uska ig_profile.py har account/image ke liye explicit args ke saath subprocess me chalta hai.

Storage:  data/campaign/<account>/dp/*   data/campaign/<account>/post/*   data/campaign/<account>/used.json
Rule   :  ek image sirf EK account ki hoti hai (hash duplicate dusre account me reject) aur
          ek account me ek image dobara post nahi hoti (used.json).
"""
import hashlib, json, os, random, re, shutil, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
CAMP = os.path.join(HERE, "data", "campaign")
THUMBS = os.path.join(HERE, "data", "thumbs")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
KINDS = ("dp", "post")
os.makedirs(CAMP, exist_ok=True)
os.makedirs(THUMBS, exist_ok=True)
_lock = threading.Lock()


def safe_name(s):
    return re.sub(r"[^\w.\-]", "_", s)[:120]


def acc_dir(acc, kind=None):
    d = os.path.join(CAMP, safe_name(acc))
    return os.path.join(d, kind) if kind else d


def list_images(acc, kind):
    d = acc_dir(acc, kind)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.lower().endswith(IMG_EXT))


def _used_path(acc):
    return os.path.join(acc_dir(acc), "used.json")


def load_used(acc):
    try:
        with open(_used_path(acc), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"post": [], "dp": []}


def save_used(acc, u):
    os.makedirs(acc_dir(acc), exist_ok=True)
    with open(_used_path(acc), "w", encoding="utf-8") as f:
        json.dump(u, f, indent=1)


def discover_accounts(cookies_dir):
    out = []
    if os.path.isdir(cookies_dir):
        for f in sorted(os.listdir(cookies_dir)):
            m = re.fullmatch(r"cookies_(.+)\.json", f)
            if m:
                out.append((m.group(1), os.path.join(cookies_dir, f)))
    return out


def account_info(cookies_dir):
    res = []
    for name, path in discover_accounts(cookies_dir):
        used = load_used(name)
        dp, posts = list_images(name, "dp"), list_images(name, "post")
        res.append({"name": name, "cookies": path, "dp": dp, "posts": posts,
                    "used_posts": [p for p in posts if p in used["post"]],
                    "dp_used": [p for p in dp if p in used["dp"]]})
    return res


# ------------------------------------------------------------ hashes (cross-account uniqueness)
def _sha(data):
    return hashlib.sha1(data).hexdigest()


def _all_hashes():
    h = {}
    if not os.path.isdir(CAMP):
        return h
    for acc in os.listdir(CAMP):
        for k in KINDS:
            d = os.path.join(CAMP, acc, k)
            if os.path.isdir(d):
                for f in os.listdir(d):
                    try:
                        with open(os.path.join(d, f), "rb") as fh:
                            h[_sha(fh.read())] = (acc, k, f)
                    except OSError:
                        pass
    return h


def add_image(acc, kind, filename, data, hashes=None):
    """returns (ok, message)"""
    if kind not in KINDS:
        return False, "bad kind"
    if not filename.lower().endswith(IMG_EXT):
        return False, "image nahi hai"
    with _lock:
        hs = hashes if hashes is not None else _all_hashes()
        sh = _sha(data)
        if sh in hs:
            a, k, f = hs[sh]
            where = "isi account" if a == safe_name(acc) else f"account '{a}'"
            return False, f"duplicate (already {where} me: {k}/{f})"
        d = acc_dir(acc, kind)
        os.makedirs(d, exist_ok=True)
        name = safe_name(filename)
        base, ext = os.path.splitext(name)
        i = 1
        while os.path.exists(os.path.join(d, name)):
            name = f"{base}_{i}{ext}"; i += 1
        with open(os.path.join(d, name), "wb") as f:
            f.write(data)
        hs[sh] = (safe_name(acc), kind, name)
        return True, name


def delete_image(acc, kind, name):
    p = os.path.join(acc_dir(acc, kind), safe_name(name))
    if os.path.isfile(p):
        os.remove(p)
        u = load_used(acc)
        for k in KINDS:
            if name in u[k]:
                u[k].remove(name)
        save_used(acc, u)
        return True
    return False


def move_image(acc, frm, to, name):
    if frm == to or frm not in KINDS or to not in KINDS:
        return False
    src = os.path.join(acc_dir(acc, frm), safe_name(name))
    if not os.path.isfile(src):
        return False
    os.makedirs(acc_dir(acc, to), exist_ok=True)
    shutil.move(src, os.path.join(acc_dir(acc, to), safe_name(name)))
    return True


def reset_used(acc):
    save_used(acc, {"post": [], "dp": []})


def import_folder(accounts, root):
    """root ke andar har sub-folder = ek account (naam match). Sub-folder me dp/ aur post/ ho to wahi use,
    warna pehli image = DP, baaki = posts."""
    root = root.strip().strip('"')
    if not os.path.isdir(root):
        return {"error": "folder nahi mila"}
    names = [a[0] for a in accounts]
    report, hs = [], _all_hashes()

    def match(folder):
        f = folder.lower()
        for n in names:
            if n.lower() == f:
                return n
        for n in names:
            if n.lower() in f or f in n.lower():
                return n
        return None

    def imgs(d):
        return sorted(os.path.join(d, x) for x in os.listdir(d) if x.lower().endswith(IMG_EXT)) if os.path.isdir(d) else []

    for sub in sorted(os.listdir(root)):
        sp = os.path.join(root, sub)
        if not os.path.isdir(sp):
            continue
        acc = match(sub)
        if not acc:
            report.append({"folder": sub, "account": None, "msg": "koi matching account nahi"})
            continue
        dpf, pof = imgs(os.path.join(sp, "dp")), imgs(os.path.join(sp, "post"))
        if not dpf and not pof:
            allf = imgs(sp)
            dpf, pof = allf[:1], allf[1:]
        added, dups = 0, 0
        for kind, files in (("dp", dpf), ("post", pof)):
            for p in files:
                with open(p, "rb") as fh:
                    ok, _ = add_image(acc, kind, os.path.basename(p), fh.read(), hs)
                added += ok
                dups += (not ok)
        report.append({"folder": sub, "account": acc, "added": added, "skipped": dups})
    return {"report": report}


def thumb_path(acc, kind, name):
    src = os.path.join(acc_dir(acc, kind), safe_name(name))
    if not os.path.isfile(src):
        return None
    dst = os.path.join(THUMBS, f"{safe_name(acc)}__{kind}__{safe_name(name)}.jpg")
    if not os.path.isfile(dst):
        try:
            from PIL import Image
            im = Image.open(src).convert("RGB")
            im.thumbnail((260, 260))
            im.save(dst, "JPEG", quality=80)
        except Exception:
            return src
    return dst


# ------------------------------------------------------------ campaign runner
def _split_captions(txt):
    return [l.strip() for l in (txt or "").splitlines() if l.strip()]


def run_campaign(job, spec, uploader_dir, cookies_by_acc, procs):
    """spec: {accounts:[{name,bio,do_dp,posts,private}], captions, pacing:{...}, dry}"""
    log = job["lines"].append
    pac = spec.get("pacing", {})
    dry = bool(spec.get("dry"))
    fast = bool(pac.get("fast"))
    parallel = max(1, min(int(pac.get("parallel", 1) or 1), 5))
    post_gap = (3, 6) if fast else (int(pac.get("post_gap_min", 120)), int(pac.get("post_gap_max", 300)))
    act_gap = (2, 4) if fast else (8, 20)
    acc_gap = (2, 4) if fast else (45, 90)
    captions = _split_captions(spec.get("captions"))
    stopped = lambda: job.get("_stopped")
    prog = job["progress"]
    plock = threading.Lock()
    cap_idx = [0]

    def nap(rng, why):
        s = random.uniform(*rng)
        log(f"   ... {int(s)}s wait ({why})")
        t = time.time() + (0.2 if dry else s)
        while time.time() < t and not stopped():
            time.sleep(0.5)

    def call(name, args, marker):
        cookies = cookies_by_acc[name]
        argv = [sys.executable, "-u", "ig_profile.py", "--cookies", cookies] + args
        pretty = " ".join(os.path.basename(a) if os.path.isfile(a) else a for a in args)
        log(f"[{name}] > {pretty}")
        if dry:
            log("   (dry-run: kuch bheja nahi)")
            return True
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        p = subprocess.Popen(argv, cwd=uploader_dir, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        procs[(job["id"], name)] = p
        out = []
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            out.append(line)
            log(f"   {line}")
        rc = p.wait()
        procs.pop((job["id"], name), None)
        txt = "\n".join(out)
        low = txt.lower()
        if not dry:
            try:
                import health
                c = health.load_cache()
                if "accounts/suspended" in low or "suspended" in low or ("disabled" in low and "account" in low):
                    c[name] = {"status": "SUSPENDED", "detail": "account suspended/disabled", "http": 400, "checked_at": time.time()}
                    health.save_cache(c)
                elif "login_required" in low:
                    c[name] = {"status": "EXPIRED", "detail": "cookie/session expire", "http": 403, "checked_at": time.time()}
                    health.save_cache(c)
                elif "challenge_required" in low or "checkpoint" in low:
                    c[name] = {"status": "CHALLENGE", "detail": "checkpoint/challenge required", "http": 400, "checked_at": time.time()}
                    health.save_cache(c)
                elif rc == 0 and "!!" not in txt and marker in txt:
                    c[name] = {"status": "ALIVE", "detail": "session valid", "http": 200, "checked_at": time.time()}
                    health.save_cache(c)
            except Exception:
                pass
        return rc == 0 and "!!" not in txt and marker in txt

    def work(a):
        name = a["name"]
        P = prog[name]
        P["status"] = "RUNNING"
        try:
            used = load_used(name)
            fails = 0
            steps = []
            if a.get("do_dp"):
                steps.append("dp")
            if (a.get("bio") or "").strip():
                steps.append("bio")
            steps += ["post"] * P["posts_total"]
            if a.get("private"):
                steps.append("private")
            first = True
            exhausted = False
            for step in steps:
                if stopped():
                    P["status"] = "STOPPED"; return
                if step == "post" and exhausted:
                    continue
                if not first:
                    nap(post_gap if step == "post" else act_gap, step)
                    if stopped():
                        P["status"] = "STOPPED"; return
                first = False
                if step == "dp":
                    cand = [f for f in list_images(name, "dp") if f not in used["dp"]] or list_images(name, "dp")
                    if not cand:
                        log(f"[{name}] DP image nahi hai - skip"); P["dp"] = "SKIP"; continue
                    ok = call(name, ["dp", os.path.join(acc_dir(name, "dp"), cand[0])], "new dp")
                    P["dp"] = "OK" if ok else "FAIL"
                    if ok:
                        used["dp"].append(cand[0])
                        if not dry:
                            save_used(name, used)
                elif step == "bio":
                    ok = call(name, ["bio", a["bio"].strip()], "status=ok")
                    P["bio"] = "OK" if ok else "FAIL"
                elif step == "post":
                    cand = [f for f in list_images(name, "post") if f not in used["post"]]
                    if not cand:
                        log(f"[{name}] aur unique image nahi bachi - posts yahin ruk gaye")
                        P["note"] = "images khatam"
                        P["posts_total"] = P["posts_done"] + P["posts_failed"]
                        exhausted = True
                        continue
                    img = cand[0]
                    with plock:
                        cap = captions[cap_idx[0] % len(captions)] if captions else ""
                        cap_idx[0] += 1
                    args = ["post", os.path.join(acc_dir(name, "post"), img)] + (["--caption", cap] if cap else [])
                    ok = call(name, args, "POST LIVE")
                    if ok:
                        P["posts_done"] += 1; fails = 0
                        used["post"].append(img)
                        if not dry:
                            save_used(name, used)
                    else:
                        P["posts_failed"] += 1; fails += 1
                        if fails >= 2:
                            log(f"[{name}] 2 post lagatar fail - account ruka (session/ban check karo)")
                            P["note"] = "2 fails - ruka"; break
                elif step == "private":
                    P["private"] = "OK" if call(name, ["private"], "PRIVATE") else "FAIL"
            bad = P["posts_failed"] or "FAIL" in (P["dp"], P["bio"], P["private"])
            P["status"] = "PARTIAL" if bad else "DONE"
        except Exception as e:
            log(f"[{name}] ERROR: {e}"); P["status"] = "FAILED"

    queue = [a for a in spec["accounts"]]
    qlock = threading.Lock()

    def worker(_i):
        while not stopped():
            with qlock:
                if not queue:
                    return
                a = queue.pop(0)
                started_before = len(spec["accounts"]) - len(queue) - 1
            if started_before > 0:
                nap(acc_gap, "accounts ke beech gap")
            if stopped():
                prog[a["name"]]["status"] = "STOPPED"; return
            log(f"\n===== @{a['name']} shuru =====")
            work(a)
            log(f"===== @{a['name']} -> {prog[a['name']]['status']} =====")

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(parallel)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for n, P in prog.items():
        if P["status"] in ("QUEUED", "RUNNING"):
            P["status"] = "STOPPED"
    log("\nCAMPAIGN KHATAM" + (" (dry-run)" if dry else ""))
    sts = [P["status"] for P in prog.values()]
    return "STOPPED" if stopped() else ("DONE" if all(s == "DONE" for s in sts) else "PARTIAL")
