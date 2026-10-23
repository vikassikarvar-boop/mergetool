"""
Account Health & Session Status Manager for Control Panel.
Checks:
- ALIVE: Session active and valid (HTTP 200)
- SUSPENDED: Account suspended/disabled by Instagram
- EXPIRED: Cookies/session expired (login_required / HTTP 401/403)
- CHALLENGE: Checkpoint/Challenge required (SMS/Selfie/App verification)
- PROXY_ERROR: Proxy failure (payment required / connection failure)
- NO_SESSION: Invalid cookie file without auth tokens
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE_FILE = os.path.join(DATA, "account_health.json")
ARCHIVE_DIR = os.path.join(DATA, "archived_cookies")
WORKER_SCRIPT = os.path.join(HERE, "health_worker.py")
os.makedirs(DATA, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

_lock = threading.Lock()
_state = {
    "checking": False,
    "total": 0,
    "done": 0,
    "current": "",
}


def load_cache():
    with _lock:
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def save_cache(cache):
    with _lock:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def get_progress():
    with _lock:
        return dict(_state)


def check_single(matrix_dir, cookies_path, acc_name=None):
    if not os.path.isfile(cookies_path):
        return {"status": "BAD_FILE", "detail": "cookie file exist nahi karti", "http": None, "checked_at": time.time()}

    try:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        p = subprocess.run(
            [sys.executable, WORKER_SCRIPT, matrix_dir, cookies_path],
            capture_output=True,
            text=True,
            timeout=40,
            cwd=HERE,
            creationflags=flags
        )
        for line in reversed(p.stdout.splitlines()):
            if "HUB_HEALTH " in line:
                raw = line.split("HUB_HEALTH ", 1)[1]
                data = json.loads(raw)
                data["checked_at"] = time.time()
                return data

        # If worker produced error or timeout
        err = p.stderr.strip() or p.stdout.strip()
        return {
            "status": "ERROR",
            "detail": err[-150:] if err else "Worker failed without output",
            "http": None,
            "checked_at": time.time()
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "detail": "Check timed out (proxy/network issue)",
            "http": None,
            "checked_at": time.time()
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "detail": str(e)[:150],
            "http": None,
            "checked_at": time.time()
        }


def check_account_and_save(matrix_dir, name, cookies_path, source=""):
    res = check_single(matrix_dir, cookies_path, name)
    res["cookies"] = cookies_path
    res["source"] = source
    cache = load_cache()
    cache[name] = res
    save_cache(cache)
    return res


def check_all_accounts(matrix_dir, accounts_list):
    """
    accounts_list: [{'name': '...', 'cookies': '...', 'source': '...'}]
    """
    global _state
    with _lock:
        if _state["checking"]:
            return False
        _state["checking"] = True
        _state["total"] = len(accounts_list)
        _state["done"] = 0
        _state["current"] = ""

    def worker():
        global _state
        cache = load_cache()
        for idx, item in enumerate(accounts_list):
            name = item["name"]
            cpath = item["cookies"]
            with _lock:
                _state["current"] = name
            res = check_single(matrix_dir, cpath, name)
            res["cookies"] = cpath
            res["source"] = item.get("source", "")
            cache[name] = res
            save_cache(cache)
            with _lock:
                _state["done"] = idx + 1
            time.sleep(0.5)

        with _lock:
            _state["checking"] = False
            _state["current"] = ""

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return True


def remove_account(name, cookie_sources_list, permanent=False):
    """
    Finds all cookie files for 'name' across cookie_sources_list,
    moves them to ARCHIVE_DIR (or deletes them if permanent=True),
    and cleans up cache.
    Returns list of paths processed.
    """
    removed = []
    fname = f"cookies_{name}.json"
    target_archive = os.path.join(ARCHIVE_DIR, name)
    os.makedirs(target_archive, exist_ok=True)

    for label, d in cookie_sources_list:
        if not os.path.isdir(d):
            continue
        cpath = os.path.join(d, fname)
        if os.path.isfile(cpath):
            if permanent:
                try:
                    os.remove(cpath)
                    removed.append(cpath)
                except OSError:
                    pass
            else:
                try:
                    dst = os.path.join(target_archive, f"{label}_{fname}")
                    shutil.move(cpath, dst)
                    removed.append(cpath)
                except Exception:
                    try:
                        os.remove(cpath)
                        removed.append(cpath)
                    except OSError:
                        pass

    # Clean cache
    cache = load_cache()
    if name in cache:
        cache.pop(name, None)
        save_cache(cache)

    return removed


def remove_by_status(status_list, cookie_sources_list, permanent=False):
    """
    Removes all accounts matching any status in status_list.
    Returns dict {name: count_removed_files}.
    """
    cache = load_cache()
    to_remove = [name for name, info in cache.items() if info.get("status") in status_list]
    report = {}
    for name in to_remove:
        rem = remove_account(name, cookie_sources_list, permanent=permanent)
        report[name] = len(rem)
    return report
