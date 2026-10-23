#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IG Tools Panel — local web UI (Flask)
=====================================
Browser se apne saare tools chalao: forms bharo, button dabao, live output dekho.
Naye tools add karne ke liye sirf tools.json me entry daalni hai.

Run:  python panel.py        (phir browser me http://127.0.0.1:8765)
Windows: run_panel.bat double-click karo.
"""
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid

from flask import (Flask, Response, jsonify, request,
                   send_from_directory, stream_with_context)

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = json.load(open(os.path.join(HERE, "tools.json"), encoding="utf-8"))
JOBS_FILE = os.path.join(HERE, "panel_jobs.json")
JOBS = []
JOBS_LOCK = threading.Lock()
SUBS = {}   # job_id -> live job state

app = Flask(__name__, static_folder=os.path.join(HERE, "static"))


# ---------------- history persistence ----------------
def load_jobs():
    global JOBS
    try:
        JOBS = json.load(open(JOBS_FILE, encoding="utf-8"))
        if not isinstance(JOBS, list):
            JOBS = []
    except Exception:
        JOBS = []


def save_jobs():
    try:
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(JOBS[:200], f, ensure_ascii=False, indent=1)
    except Exception:
        pass


load_jobs()


def match_status(tool, text):
    for rule in tool.get("status_rules", []):
        try:
            if re.search(rule["pattern"], text, re.I):
                return rule["status"]
        except re.error:
            if rule["pattern"].lower() in text.lower():
                return rule["status"]
    return None


def build_argv(tool, params):
    argv = [sys.executable, "-u", os.path.join(HERE, tool["script"])]
    for f in tool.get("fields", []):
        raw = params.get(f["name"])
        v = (raw if isinstance(raw, str) else "").strip()
        ftype = f.get("type", "text")
        if ftype == "flag":
            if v.lower() in ("1", "true", "yes", "on"):
                argv.append(f["arg"])
            continue
        if not v:
            continue
        if f.get("positional"):
            argv.append(v)
        elif f.get("arg"):
            argv += [f["arg"], v]
    return argv


def run_job(job_id, tool, params):
    sub = SUBS[job_id]
    argv = build_argv(tool, params)
    shown = " ".join('"%s"' if (" " in a or "#" in a or "@" in a) else "%s"
                     for a in [])  # placeholder, replaced below
    args_disp = []
    for a in argv[3:]:
        args_disp.append('"%s"' % a if any(c in a for c in " #@") else a)
    sub["lines"].append("$ python %s %s" % (tool["script"], " ".join(args_disp)))
    rc = -1
    try:
        proc = subprocess.Popen(
            argv, cwd=HERE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        sub["proc"] = proc
        for line in proc.stdout:
            sub["lines"].append(line.rstrip("\n"))
            if len(sub["lines"]) > 6000:
                del sub["lines"][:2000]
        proc.wait()
        rc = proc.returncode
    except Exception as e:
        sub["lines"].append(f"[panel error] {type(e).__name__}: {e}")
    text = "\n".join(sub["lines"])
    status = match_status(tool, text) or {
        0: "SUCCESS", 1: "FAILED", 2: "DIAGNOSED", 3: "THROTTLED",
    }.get(rc, f"EXIT_{rc}")
    sub.update(done=True, exit_code=rc, status=status, ended=time.time())
    rec = {
        "id": job_id, "tool": tool["id"], "label": tool.get("label", tool["id"]),
        "time": sub["started"],
        "when": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(sub["started"])),
        "duration": round(sub["ended"] - sub["started"], 1),
        "username": (params.get("username") or "").strip(),
        "status": status, "exit_code": rc,
        "all_lines": sub["lines"][:3000],
    }
    with JOBS_LOCK:
        JOBS.insert(0, rec)
        save_jobs()


# ---------------- routes ----------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/tools")
def api_tools():
    return jsonify(TOOLS)


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(force=True)
    tool = next((t for t in TOOLS["tools"] if t["id"] == data.get("tool")), None)
    if not tool:
        return jsonify({"error": "unknown tool"}), 400
    params = data.get("params") or {}
    for f in tool.get("fields", []):
        if f.get("required") and not str(params.get(f["name"]) or "").strip():
            return jsonify({"error": f"Field zaroori hai: {f['label']}"}), 400
    script_path = os.path.join(HERE, tool["script"])
    if not os.path.exists(script_path):
        return jsonify({"error": f"Script nahi mili: {tool['script']}"}), 400
    job_id = uuid.uuid4().hex[:10]
    SUBS[job_id] = {
        "lines": [], "done": False, "started": time.time(),
        "tool": tool["id"], "label": tool.get("label", tool["id"]),
        "params": {k: v for k, v in params.items() if k != "password"},
        "status": "RUNNING", "exit_code": None,
    }
    threading.Thread(target=run_job, args=(job_id, tool, params), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/stream/<job_id>")
def api_stream(job_id):
    sub = SUBS.get(job_id)
    if not sub:
        return jsonify({"error": "no such job"}), 404

    def gen():
        idx = 0
        while True:
            while idx < len(sub["lines"]):
                line = sub["lines"][idx]
                idx += 1
                yield "data: %s\n\n" % json.dumps({"t": "line", "v": line}, ensure_ascii=False)
            if sub["done"]:
                yield "data: %s\n\n" % json.dumps(
                    {"t": "done", "status": sub["status"],
                     "exit_code": sub["exit_code"],
                     "duration": round(sub["ended"] - sub["started"], 1)},
                    ensure_ascii=False)
                break
            time.sleep(0.2)
    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/jobs")
def api_jobs():
    jid = request.args.get("id")
    if jid:
        rec = next((j for j in JOBS if j["id"] == jid), None)
        if rec:
            return jsonify(rec)
        sub = SUBS.get(jid)
        if sub:
            return jsonify({"id": jid, "status": sub["status"],
                            "username": sub["params"].get("username", ""),
                            "all_lines": sub["lines"]})
        return jsonify({"error": "not found"}), 404
    with JOBS_LOCK:
        return jsonify([{k: v for k, v in j.items() if k != "all_lines"}
                        for j in JOBS[:100]])


@app.route("/api/cookies")
def api_cookies():
    out = []
    for p in sorted(glob.glob(os.path.join(HERE, "cookies*.json")),
                    key=os.path.getmtime, reverse=True):
        base = os.path.basename(p)
        if base == "cookies.json" or base.startswith("cookies_"):
            pass
        try:
            j = json.load(open(p, encoding="utf-8"))
            ck = j.get("cookies", j) if isinstance(j, dict) else {}
            out.append({
                "file": base, "size": os.path.getsize(p),
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
                "username": j.get("username", "") if isinstance(j, dict) else "",
                "user_id": str(j.get("user_id") or (ck.get("ds_user_id", "") if isinstance(ck, dict) else "")),
                "has_session": bool((ck.get("sessionid") if isinstance(ck, dict) else "") or
                                    (j.get("sessionid") if isinstance(j, dict) else "")),
            })
        except Exception:
            out.append({"file": base, "size": os.path.getsize(p), "error": True})
    return jsonify(out)


@app.route("/api/cookies/download/<path:name>")
def api_cookies_download(name):
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+\.json", name):
        return "bad name", 400
    if not os.path.exists(os.path.join(HERE, name)):
        return "not found", 404
    return send_from_directory(HERE, name, as_attachment=True)


@app.route("/api/cookies/delete", methods=["POST"])
def api_cookies_delete():
    name = (request.get_json(force=True) or {}).get("file", "")
    if not re.fullmatch(r"cookies[A-Za-z0-9_.\-]*\.json", name):
        return jsonify({"error": "bad name"}), 400
    p = os.path.join(HERE, name)
    if os.path.exists(p):
        os.remove(p)
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


def preflight_deps():
    """Zaroori packages ka quick check — kami ho to clear message."""
    missing = []
    for mod, pkg in [("requests", "requests"), ("Cryptodome", "pycryptodomex"), ("flask", "flask")]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("!! Ye packages missing hain:", ", ".join(missing))
        print("   Install: pip install " + " ".join(missing))
        return False
    return True


if __name__ == "__main__":
    preflight_deps()
    port = int(os.environ.get("PANEL_PORT", "8765"))
    host = os.environ.get("PANEL_HOST", "0.0.0.0")
    print(f"IG Tools Panel → http://127.0.0.1:{port}")
    print("Band karne ke liye Ctrl+C dabao.")
    app.run(host=host, port=port, threaded=True, debug=False)
