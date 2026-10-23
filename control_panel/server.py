"""
Unified Control Panel (hub) - sirf stdlib, koi install nahi.
Har tool apne folder me apni script se chalta hai (subprocess). Tool ki files kabhi modify nahi hoti.
Run:  python server.py   ->  http://127.0.0.1:8800
"""
import json, os, re, subprocess, sys, threading, time, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
import campaign, comments, bios, health

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                     # "merge tool" folder
DATA = os.path.join(HERE, "data")
LOGS = os.path.join(DATA, "logs")
REGISTRY = os.path.join(HERE, "registry.json")
JOBS_FILE = os.path.join(DATA, "jobs.json")
PORT = int(os.environ.get("HUB_PORT", "8800"))
os.makedirs(LOGS, exist_ok=True)

LOCK = threading.Lock()
JOBS = {}      # id -> dict (meta + "lines")
PROCS = {}     # id -> Popen


# ---------------------------------------------------------------- registry
def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_registry():
    """Har request par fresh padhta hai -> registry/tool JSON badlo, restart ki zaroorat nahi."""
    reg = _read_json(REGISTRY)
    tools = []
    for t in reg.get("tools", []):
        t = dict(t)
        folder = os.path.join(ROOT, t["folder"])
        t["_dir"] = folder
        t["exists"] = os.path.isdir(folder)
        actions = list(t.get("actions", []))
        af = t.get("actions_file")
        if af:
            try:
                for a in _read_json(os.path.join(folder, af)).get("tools", []):
                    actions.append(a)
            except Exception as e:
                t["error"] = f"actions_file load fail: {e}"
        for a in actions:
            a.setdefault("fields", [])
            a.setdefault("fixed", [])
            a.setdefault("status_rules", [])
            if not a.get("label"):
                a["label"] = a["id"]
            a["exists"] = os.path.isfile(os.path.join(folder, a["script"]))
        t["actions"] = actions
        tools.append(t)
    return tools


def public_tools(tools):
    return [{k: v for k, v in t.items() if not k.startswith("_")} for t in tools]


# ---------------------------------------------------------------- argv build
def build_argv(tool, action, values):
    py = tool.get("python") or sys.executable
    argv = [py, "-u", action["script"]] + list(action.get("fixed", []))
    shown = list(argv)
    for f in action["fields"]:
        v = values.get(f["name"])
        typ = f.get("type", "text")
        secret = typ == "password"
        if typ == "flag":
            if v and f.get("arg"):
                argv.append(f["arg"]); shown.append(f["arg"])
            continue
        if typ == "multi":
            v = [x for x in (v or []) if x in f.get("options", [])]
            empty = not v
        else:
            v = "" if v is None else str(v).strip()
            empty = v == ""
        if empty:
            if f.get("required"):
                raise ValueError(f"'{f.get('label', f['name'])}' zaroori hai")
            continue
        vals = v if isinstance(v, list) else [v]
        for x in vals:
            if f.get("arg"):
                argv += [f["arg"], x]; shown += [f["arg"], "******" if secret else x]
            else:
                argv.append(x); shown.append("******" if secret else x)
    return argv, shown


# ---------------------------------------------------------------- jobs
def save_jobs():
    with LOCK:
        meta = [{k: v for k, v in j.items() if k != "lines"} for j in JOBS.values()]
    meta.sort(key=lambda j: j["started"])
    try:
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(meta[-300:], f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def load_jobs():
    if not os.path.isfile(JOBS_FILE):
        return
    try:
        for j in _read_json(JOBS_FILE):
            if j.get("status") == "RUNNING":
                j["status"] = "INTERRUPTED"
            j["lines"] = None      # lazily loaded from log
            JOBS[j["id"]] = j
    except Exception:
        pass


def job_lines(j):
    if j.get("lines") is None:
        p = os.path.join(LOGS, j["id"] + ".log")
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                j["lines"] = f.read().splitlines()
        except Exception:
            j["lines"] = []
    return j["lines"]


def classify(action, text, rc, stopped):
    if stopped:
        return "STOPPED"
    for r in action.get("status_rules", []):
        try:
            if re.search(r["pattern"], text):
                return r["status"]
        except re.error:
            pass
    return "DONE" if rc == 0 else "FAILED"


def run_job(job, tool, action, argv):
    log_path = os.path.join(LOGS, job["id"] + ".log")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        p = subprocess.Popen(argv, cwd=tool["_dir"], env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=flags)
    except Exception as e:
        job["lines"].append(f"[hub] start fail: {e}")
        job.update(status="FAILED", ended=time.time(), rc=-1)
        save_jobs(); return
    PROCS[job["id"]] = p
    with open(log_path, "w", encoding="utf-8") as lf:
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            job["lines"].append(line)
            lf.write(line + "\n"); lf.flush()
    rc = p.wait()
    PROCS.pop(job["id"], None)
    text = "\n".join(job["lines"])
    job.update(rc=rc, ended=time.time(), status=classify(action, text, rc, job.get("_stopped")))
    job.pop("_stopped", None)
    save_jobs()


def start_job(tool_id, action_id, values):
    tools = load_registry()
    tool = next((t for t in tools if t["id"] == tool_id), None)
    if not tool:
        raise ValueError("tool nahi mila")
    action = next((a for a in tool["actions"] if a["id"] == action_id), None)
    if not action:
        raise ValueError("action nahi mila")
    if not action["exists"]:
        raise ValueError(f"script nahi mili: {action['script']}")
    argv, shown = build_argv(tool, action, values)
    job = {"id": uuid.uuid4().hex[:10], "tool": tool["id"], "tool_label": tool["label"],
           "action": action["id"], "action_label": action["label"],
           "cmd": " ".join(shown[1:] if len(shown) > 1 else shown),
           "started": time.time(), "ended": None, "status": "RUNNING", "rc": None, "lines": []}
    with LOCK:
        JOBS[job["id"]] = job
    save_jobs()
    threading.Thread(target=run_job, args=(job, tool, action, argv), daemon=True).start()
    return job["id"]


def _kill(p):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    else:
        p.terminate()


def stop_job(jid):
    j = JOBS.get(jid)
    if not j or j.get("status") != "RUNNING":
        return False
    j["_stopped"] = True
    p = PROCS.get(jid)
    if p:
        _kill(p)
    for key, cp in list(PROCS.items()):          # campaign child processes
        if isinstance(key, tuple) and key[0] == jid:
            _kill(cp)
    return True


# ---------------------------------------------------------------- bulk campaign
def uploader_dir():
    t = next((t for t in load_registry() if t["id"] == "uploader"), None)
    if not t or not t["exists"]:
        raise ValueError("Post uploader folder nahi mila")
    return t["_dir"]


def cookies_dir():
    return os.path.join(uploader_dir(), "cookies")


def start_campaign(spec):
    accs = {n: p for n, p in campaign.discover_accounts(cookies_dir())}
    sel = []
    for a in spec.get("accounts", []):
        if a.get("name") in accs:
            sel.append(a)
    if not sel:
        raise ValueError("koi account select nahi")
    if spec.get("auto_bio"):                    # khali bio wale accounts ke liye unique female bio
        need = [a for a in sel if not (a.get("bio") or "").strip() and a.get("want_bio", True)]
        gen = bios.generate(len(need), [account_country(accs[a["name"]]) for a in need])
        for a, b in zip(need, gen):
            a["bio"] = b
    if not spec.get("dry"):
        bios.mark_used([a.get("bio", "") for a in sel])
    prog = {}
    for a in sel:
        n = a["name"]
        avail = len([f for f in campaign.list_images(n, "post") if f not in campaign.load_used(n)["post"]])
        want = avail if str(a.get("posts")) == "all" else min(int(a.get("posts") or 0), avail)
        a["posts"] = want
        prog[n] = {"status": "QUEUED", "dp": "-" if not a.get("do_dp") else "..",
                   "bio": "-" if not (a.get("bio") or "").strip() else "..",
                   "posts_total": want, "posts_done": 0, "posts_failed": 0,
                   "private": ".." if a.get("private") else "-", "note": ""}
        if int(a.get("posts") or 0) < want:
            pass
    job = {"id": uuid.uuid4().hex[:10], "tool": "campaign", "tool_label": "Bulk Campaign",
           "action": "campaign", "action_label": f"{len(sel)} accounts" + (" (dry-run)" if spec.get("dry") else ""),
           "cmd": "campaign: " + ", ".join(a["name"] for a in sel),
           "started": time.time(), "ended": None, "status": "RUNNING", "rc": None, "lines": [],
           "progress": prog}
    with LOCK:
        JOBS[job["id"]] = job
    save_jobs()
    spec = dict(spec, accounts=sel)
    up = uploader_dir()

    def go():
        try:
            st = campaign.run_campaign(job, spec, up, accs, PROCS)
        except Exception as e:
            job["lines"].append(f"[hub] campaign error: {e}"); st = "FAILED"
        job.update(status=st, ended=time.time(), rc=0)
        job.pop("_stopped", None)
        try:
            with open(os.path.join(LOGS, job["id"] + ".log"), "w", encoding="utf-8") as f:
                f.write("\n".join(job["lines"]) + "\n")
        except OSError:
            pass
        save_jobs()
    threading.Thread(target=go, daemon=True).start()
    return job["id"]


def account_country(cookie_path):
    try:
        return _read_json(cookie_path).get("country") or "IN"
    except Exception:
        return "IN"


def tool_dir(tid):
    t = next((t for t in load_registry() if t["id"] == tid), None)
    if not t or not t["exists"]:
        raise ValueError(f"{tid} folder nahi mila")
    return t["_dir"]


def cookie_sources():
    out = []
    for label, tid, sub in (("uploader", "uploader", "cookies"), ("matrix", "matrix", "cookies"), ("login", "login", "")):
        try:
            out.append((label, os.path.join(tool_dir(tid), sub) if sub else tool_dir(tid)))
        except ValueError:
            pass
    out.append(("hub", comments.HUB_COOKIES))
    return out


def all_accounts_list():
    avail = comments.scan_sources(cookie_sources())
    return sorted(list(avail.values()), key=lambda x: x["name"])


def start_comments(spec):
    url = (spec.get("url") or "").strip()
    if not url:
        raise ValueError("post URL do")
    texts = comments.split_comments(spec.get("comments"))
    if not texts:
        raise ValueError("comments likho (ek line = ek comment)")
    roster = [r for r in comments.load_roster() if r.get("active") and os.path.isfile(r["cookies"])]
    if not roster:
        raise ValueError("koi active account nahi - roster me add/activate karo")
    if spec.get("shuffle"):
        import random; random.shuffle(roster)
    rows = [{"n": i + 1, "text": t, "account": roster[i % len(roster)]["name"], "status": "QUEUED", "note": ""}
            for i, t in enumerate(texts)]
    job = {"id": uuid.uuid4().hex[:10], "tool": "comments", "tool_label": "Comment Blast",
           "action": "comments", "action_label": f"{len(texts)} comments / {len(roster)} accounts" + (" (dry-run)" if spec.get("dry") else ""),
           "cmd": "post: " + url, "started": time.time(), "ended": None, "status": "RUNNING", "rc": None,
           "lines": [], "progress": rows}
    with LOCK:
        JOBS[job["id"]] = job
    save_jobs()
    md = tool_dir("matrix")

    def go():
        try:
            st = comments.run_comments(job, dict(spec, accounts=roster, url=url), md, PROCS)
        except Exception as e:
            job["lines"].append(f"[hub] comments error: {e}"); st = "FAILED"
        job.update(status=st, ended=time.time(), rc=0)
        job.pop("_stopped", None)
        try:
            with open(os.path.join(LOGS, job["id"] + ".log"), "w", encoding="utf-8") as f:
                f.write("\n".join(job["lines"]) + "\n")
        except OSError:
            pass
        save_jobs()
    threading.Thread(target=go, daemon=True).start()
    return job["id"]


def jobs_meta():
    with LOCK:
        out = [{k: v for k, v in j.items() if k not in ("lines", "_stopped")} for j in JOBS.values()]
    out.sort(key=lambda j: j["started"], reverse=True)
    return out


# ---------------------------------------------------------------- http
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "static", "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if path == "/api/tools":
            return self._send(200, public_tools(load_registry()))
        if path == "/api/roster":
            return self._send(200, comments.roster_view(cookie_sources()))
        if path == "/api/health":
            accs = all_accounts_list()
            cache = health.load_cache()
            return self._send(200, {
                "accounts": accs,
                "cache": cache,
                "progress": health.get_progress()
            })
        if path == "/api/camp/accounts":
            try:
                return self._send(200, [{k: v for k, v in a.items() if k != "cookies"}
                                        for a in campaign.account_info(cookies_dir())])
            except Exception as e:
                return self._send(400, {"error": str(e)})
        if path == "/api/camp/img":
            q = {k: v[0] for k, v in parse_qs(qs).items()}
            tp = campaign.thumb_path(q.get("acc", ""), q.get("kind", ""), q.get("name", ""))
            if not tp:
                return self._send(404, {"error": "nahi mila"})
            with open(tp, "rb") as f:
                ct = "image/webp" if tp.endswith(".webp") else "image/png" if tp.endswith(".png") else "image/jpeg"
                data = f.read()
            self.send_response(200); self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=3600"); self.end_headers()
            return self.wfile.write(data)
        if path == "/api/jobs":
            return self._send(200, jobs_meta())
        m = re.fullmatch(r"/api/jobs/(\w+)", path)
        if m:
            j = JOBS.get(m.group(1))
            if not j:
                return self._send(404, {"error": "job nahi mila"})
            since = int(dict(x.split("=") for x in qs.split("&") if "=" in x).get("since", 0))
            lines = job_lines(j)
            meta = {k: v for k, v in j.items() if k not in ("lines", "_stopped")}
            return self._send(200, dict(meta, lines=lines[since:], total=len(lines)))
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if self.path.startswith("/api/camp/upload"):
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            ok, msg = campaign.add_image(q.get("acc", ""), q.get("kind", ""), q.get("name", "x.jpg"), raw)
            return self._send(200, {"ok": ok, "msg": msg})
        if self.path.startswith("/api/roster/upload"):
            try:
                return self._send(200, {"ok": True, "name": comments.save_uploaded_cookie(raw)})
            except Exception as e:
                return self._send(400, {"error": str(e)})
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            return self._send(400, {"error": "bad json"})
        try:
            if self.path == "/api/roster/add":
                comments.roster_add(body["name"], cookie_sources()); return self._send(200, {"ok": True})
            if self.path == "/api/roster/set":
                comments.roster_set(body["name"], body.get("active"), bool(body.get("remove")))
                return self._send(200, {"ok": True})
            if self.path == "/api/comments/start":
                return self._send(200, {"id": start_comments(body)})
            if self.path == "/api/health/check":
                name = body.get("name")
                accs = {a["name"]: a for a in all_accounts_list()}
                if name not in accs:
                    return self._send(400, {"error": "account cookies nahi mili"})
                res = health.check_account_and_save(tool_dir("matrix"), name, accs[name]["cookies"], accs[name].get("source", ""))
                return self._send(200, res)
            if self.path == "/api/health/check_all":
                ok = health.check_all_accounts(tool_dir("matrix"), all_accounts_list())
                return self._send(200, {"ok": ok})
            if self.path == "/api/health/remove":
                name = body.get("name")
                if not name:
                    return self._send(400, {"error": "name missing"})
                rem = health.remove_account(name, cookie_sources(), permanent=bool(body.get("permanent")))
                comments.roster_set(name, remove=True)
                return self._send(200, {"ok": True, "removed": rem})
            if self.path == "/api/health/remove_by_status":
                status_list = body.get("status") or ["SUSPENDED"]
                rep = health.remove_by_status(status_list, cookie_sources(), permanent=bool(body.get("permanent")))
                for n in rep.keys():
                    comments.roster_set(n, remove=True)
                return self._send(200, {"ok": True, "report": rep})
            if self.path == "/api/bio/generate":
                accs = dict(campaign.discover_accounts(cookies_dir()))
                names = body.get("accounts") or []
                ctr = [account_country(accs[n]) if n in accs else "IN" for n in names]
                g = bios.generate(len(names), ctr, body.get("style", "auto"))
                return self._send(200, {"bios": dict(zip(names, g))})
        except Exception as e:
            return self._send(400, {"error": str(e)})
        if self.path.startswith("/api/camp/"):
            try:
                act = self.path.rsplit("/", 1)[1]
                if act == "delete":
                    return self._send(200, {"ok": campaign.delete_image(body["acc"], body["kind"], body["name"])})
                if act == "move":
                    return self._send(200, {"ok": campaign.move_image(body["acc"], body["from"], body["to"], body["name"])})
                if act == "reset":
                    campaign.reset_used(body["acc"]); return self._send(200, {"ok": True})
                if act == "import":
                    return self._send(200, campaign.import_folder(campaign.discover_accounts(cookies_dir()), body.get("path", "")))
                if act == "start":
                    return self._send(200, {"id": start_campaign(body)})
            except Exception as e:
                return self._send(400, {"error": str(e)})
        if self.path == "/api/run":
            try:
                jid = start_job(body.get("tool"), body.get("action"), body.get("values") or {})
                return self._send(200, {"id": jid})
            except Exception as e:
                return self._send(400, {"error": str(e)})
        m = re.fullmatch(r"/api/jobs/(\w+)/stop", self.path)
        if m:
            return self._send(200, {"ok": stop_job(m.group(1))})
        if self.path == "/api/jobs/clear":
            with LOCK:
                for jid in [k for k, j in JOBS.items() if j["status"] != "RUNNING"]:
                    JOBS.pop(jid, None)
                    try: os.remove(os.path.join(LOGS, jid + ".log"))
                    except OSError: pass
            save_jobs()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    load_jobs()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"Control Panel chal raha hai: http://127.0.0.1:{PORT}   (band karne: Ctrl+C)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
