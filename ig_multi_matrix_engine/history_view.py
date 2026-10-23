#!/usr/bin/env python3
"""FIX 8 companion: history/<user>/<date>.jsonl ko readable timeline me dikhata hai.

Usage:
  python history_view.py history/user1/2026-08-27.jsonl          # full timeline
  python history_view.py history/user1                            # latest file auto
  python history_view.py <file> --errors                          # sirf errors/blocks
  python history_view.py <file> --events                          # sirf action events
  python history_view.py <file> --show 12                         # line #12 ki FULL detail
  python history_view.py <file> --grep comment                    # filter by text
"""
import json, os, sys, glob

def load(path):
    if os.path.isdir(path):
        files = sorted(glob.glob(os.path.join(path, "*.jsonl")) +
                       glob.glob(os.path.join(path, "*.json")))
        if not files:
            sys.exit(f"No .jsonl/.json files in {path}")
        path = files[-1]
    recs = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except Exception:
            pass
    return path, recs

def short_url(u):
    u = u or ""
    u = u.split("?")[0]
    return u.replace("https://i.instagram.com", "").replace("https://graph.instagram.com", "GRAPH")

def main():
    args, flags = [], []
    av = sys.argv[1:]
    i = 0
    while i < len(av):
        a = av[i]
        if a.startswith("--"):
            flags.append(a)
            if a in ("--show", "--grep") and i + 1 < len(av):
                flags.append(av[i + 1]); i += 1
        else:
            args.append(a)
        i += 1
    if not args:
        print(__doc__); sys.exit(1)
    path, recs = load(args[0])
    print(f"FILE: {path}  ({len(recs)} records)\n")

    if "--data" in flags:
        media_bytes, media_count, api_bytes = 0, 0, 0
        for r in recs:
            if r.get("kind") != "http":
                continue
            body = r.get("resp_body") or ""
            if isinstance(body, str) and body.startswith("<binary"):
                try:
                    media_bytes += int(body.split()[1]); media_count += 1
                except Exception:
                    pass
            else:
                api_bytes += len(str(body)) + len(json.dumps(r.get("resp_headers") or {}))
                api_bytes += len(str(r.get("req_body") or "")) + len(json.dumps(r.get("req_headers") or {}))
        tot = media_bytes + api_bytes
        print(f"MEDIA downloaded : {media_count} files, {media_bytes/1e6:.1f} MB "
              f"(avg {media_bytes/max(media_count,1)/1024:.0f} KB/file)")
        print(f"API req+resp   : {api_bytes/1e6:.1f} MB")
        print(f"TOTAL          : {tot/1e6:.1f} MB  ({tot/1e9:.2f} GB)")
        return

    if "--show" in flags:
        n = int(flags[flags.index("--show") + 1])
        rec = recs[n]
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return

    grep = flags[flags.index("--grep") + 1].lower() if "--grep" in flags else None
    for i, r in enumerate(recs):
        kind, tag = r.get("kind"), r.get("tag", "")
        line = json.dumps(r, ensure_ascii=False, default=str)
        if grep and grep not in line.lower():
            continue
        if "--errors" in flags:
            if not (r.get("error") or r.get("blocked") or (r.get("status") or 200) >= 400
                    or tag in ("BLOCKED_OR_CHALLENGE", "SOFT_LIMIT_STOP")):
                continue
        if "--events" in flags and kind != "event":
            continue
        ts = r.get("ts", "")[-8:]
        if kind == "http":
            st = r.get("status")
            el = r.get("elapsed_ms")
            err = f" ERR:{r['error']}" if r.get("error") else ""
            print(f"[{i:4d}] {ts} HTTP {tag:38s} {st} {el}ms{err}  {short_url(r.get('url'))}")
        elif kind == "event":
            extra = {k: v for k, v in r.items() if k not in ("kind", "tag", "ts", "account")}
            print(f"[{i:4d}] {ts} EVT  {tag:38s} {extra}")
        elif kind == "fingerprint":
            print(f"[{i:4d}] {ts} FP   ua={str(r.get('user_agent'))[:60]} ja3md5={r.get('ja3_md5')} "
                  f"uid={r.get('uid')} proxy={r.get('proxy')}")

if __name__ == "__main__":
    main()
