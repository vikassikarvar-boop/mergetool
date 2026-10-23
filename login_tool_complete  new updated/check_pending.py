import os, glob

HERE = r"D:\new ig login app and cookies check\ig_login_tool"
SUB_DIR = os.path.join(HERE, "saved_cookies_part22")
PART22_PATH = r"D:\arena ai project\account format changer to server format\parttt 22.txt"

# Find cookies in root or subfolder
existing_cookies = set()
for d in [HERE, SUB_DIR]:
    if os.path.exists(d):
        for f in os.listdir(d):
            if f.startswith("cookies_") and f.endswith(".json"):
                uname = f[len("cookies_"):-len(".json")]
                existing_cookies.add(uname)

print(f"Total existing cookie files in saved folder: {len(existing_cookies)}")

with open(PART22_PATH, "r", encoding="utf-8") as f:
    accounts = [l.strip().split(":")[0] for l in f if l.strip()]

done = [a for a in accounts if a in existing_cookies]
pending = [a for a in accounts if a not in existing_cookies]

print(f"Total accounts in parttt 22.txt: {len(accounts)}")
print(f"Already done ({len(done)}): {done}")
print(f"\nPending to login ({len(pending)}): {pending}")
