"""
Hub comment worker - Multi Matrix Engine ke ig_actions.py ko IMPORT karke ek comment karta hai.
(ig_actions.py ko koi change nahi; hub bas uske functions call karta hai.)

usage: python comment_worker.py <matrix_dir> <cookies.json> <post_url_or_shortcode> <text_file_utf8>
"""
import os, sys, time, random

matrix_dir, cookies, target, text_file = sys.argv[1:5]
sys.path.insert(0, matrix_dir)
os.chdir(matrix_dir)
text = open(text_file, encoding="utf-8").read().strip()

import ig_actions as A

try:
    pk = A.url_to_media_id(target) if ("/" in target or not target.isdigit()) else target
    if not pk:
        print("HUB_COMMENT_FAIL bad post url"); sys.exit(2)
    sess = A.Session(cookies)
    sess.push_nav("MainFeedFragment", "feed_timeline")
    print(f">> account: {sess.username}")
    if not A.verify(sess, "START"):
        print("HUB_COMMENT_FAIL session invalid / challenge"); sys.exit(3)
    time.sleep(random.uniform(1.5, 3.5))
    sess.reset_nav_to_feed()
    sess.push_nav("CommentsListFragment", "comments_v2")
    r = A.comment(sess, str(pk), text)
    body = (r.text or "").replace(" ", "")
    if r.status_code == 200 and '"status":"ok"' in body:
        print("HUB_COMMENT_OK")
    else:
        print("HUB_COMMENT_FAIL " + (r.text or "")[:200].replace("\n", " "))
        sys.exit(4)
except SystemExit:
    raise
except Exception as e:
    print(f"HUB_COMMENT_FAIL exception: {e}")
    sys.exit(5)
