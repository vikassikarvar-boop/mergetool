#!/usr/bin/env python3
"""
unique_comment_generator.py — Globally Unique Human-Like Comment Engine.
v3 (FIX 13c rebuild).

Why rebuild:
  v1 = word-salad ("Absolute masterpiece clean focus great execution") ->
       caught by IG NLP.
  v2 = grammatically correct BUT 100% of the vocabulary lived in ONE
       semantic family (aesthetic praise: obsessed/balanced/clarity/
       timeless/tones/perspective...). The suspended account's log
       (30-Aug, comment_only_12) showed 12 comments all from that family
       — grammar perfect, pattern obvious.

  v3 = 7 semantic FAMILIES (reactions, opinions, questions, personal,
       casual, humor, aesthetic) with realistic weights, per-account
       flavour bias, and an ANTI-CLUSTER guard that rejects candidates
       too similar to the last comments this account made.

API unchanged (thread-safe): get_unique_comment(account_name),
load_used_comments(). Registry: global_used_comments.json.
"""

import json
import os
import random
import threading
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(HERE, "global_used_comments.json")
COMMENT_LOCK = threading.Lock()

# ──────────────────────────────────────────────────────────────────────────
# FAMILIES — each is a list of complete, natural human comments.
# ──────────────────────────────────────────────────────────────────────────

REACTIONS = [
    "This is great!",
    "Love this one.",
    "So good to see this.",
    "This made my day, honestly.",
    "Really nice post.",
    "Such a great share.",
    "This is awesome!",
    "Great to see this here.",
    "This one is a gem.",
    "Really enjoyed this.",
    "This deserves way more attention.",
    "What a great post.",
    "Honestly one of the better posts I've seen today.",
    "This is exactly what I wanted to see today.",
    "Well done, seriously.",
]

OPINIONS = [
    "I think this is really well done.",
    "You can tell a lot of effort went into this.",
    "The timing on this post is perfect.",
    "This is the kind of content I follow for.",
    "I didn't expect this, but I'm glad I saw it.",
    "It's rare to see something this well put together.",
    "I feel like this doesn't get talked about enough.",
    "Simple, but it really works.",
    "This is a smart way to look at it.",
    "There's a lot going on here that people might miss.",
    "This kind of consistency is impressive in itself.",
    "You don't see this approach very often, and it shows.",
]

QUESTIONS = [
    "How long did this take to put together?",
    "Where was this taken? It looks amazing.",
    "Is there more of this coming? Would love to see it.",
    "What's the story behind this one?",
    "Do you post stuff like this often?",
    "Anyone else think this deserves more views?",
    "What inspired this one?",
    "Is this part of a bigger project?",
    "What editing style is this? Suits it really well.",
    "What gear did you use here?",
]

PERSONAL = [
    "I was just talking about this the other day.",
    "Sharing this with a friend who needs to see it.",
    "Had to stop scrolling for this one.",
    "Came back just to look at this again.",
    "Saving this one for later.",
    "I almost scrolled past, glad I didn't.",
    "First thing I've reacted to all day.",
    "This reminded me of something I saw last week.",
    "Not gonna lie, I watched this twice.",
    "This popped up at the right time for me.",
]

CASUAL = [
    "Okay this is cool.",
    "So good.",
    "No notes.",
    "This one gets me every time.",
    "Quality stuff.",
    "Yep, this is the good stuff.",
    "10/10 from me.",
    "Respect.",
    "This made me smile.",
    "Alright, you have my attention now.",
    "Clean. Really clean.",
    "This hits different.",
]

HUMOR = [
    "And here I was having a boring day.",
    "The algorithm finally did something right today.",
    "My feed needed exactly this.",
    "I have no idea why I like this, but I do.",
    "Okay, I wasn't ready for this one.",
    "This is going straight into my saved folder.",
    "Instructions unclear, liked it three times.",
]

# Aesthetic praise kept but SMALL share (~15%) — still valid for photo posts,
# just no longer the only voice an account has.
AESTHETIC_TEMPLATES = [
    "The {noun} in this is {adj}.",
    "Love the {adj} {noun} here.",
    "Such {adj} {noun} — really well captured.",
    "The {noun} alone makes this one worth saving.",
    "{adj_cap} {noun}, honestly.",
]
AESTHETIC_ADJ = ["clean", "moody", "crisp", "warm", "natural", "bold",
                 "soft", "sharp", "calm", "vivid", "honest", "subtle"]
AESTHETIC_NOUN = ["light", "framing", "colours", "angle", "moment",
                  "composition", "edit", "detail", "contrast", "palette"]

EMOJI_POOL = [""] * 16 + ["🔥", "✨", "👏", "😍", "🙌", "💯", "❤️", "🤩", "👌"]

# Realistic family weights (sum ~1.0). No single family dominates anymore.
FAMILY_WEIGHTS = [
    ("reactions", REACTIONS, 0.20),
    ("opinions", OPINIONS, 0.16),
    ("questions", QUESTIONS, 0.14),
    ("personal", PERSONAL, 0.16),
    ("casual", CASUAL, 0.14),
    ("humor", HUMOR, 0.05),
    ("aesthetic", None, 0.15),
]

# Words whose repetition across comments is a clustering signal
_CLUSTER_WORDS = {
    "obsessed", "balance", "balanced", "clarity", "timeless", "tone", "tones",
    "perspective", "smooth", "spectacular", "incredible", "masterpiece",
    "texture", "atmosphere", "visual", "energy", "stunning", "breathtaking",
}

# Per-account recent-comment memory (anti-clustering within a run)
_RECENT = {}  # account -> deque of recent comments
_RECENT_N = 5


def load_used_comments():
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_used_comments(used_set):
    try:
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(used_set)), f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: Could not save comments registry: {e}")


def _content_words(text):
    import re
    return set(re.findall(r"[a-z']{4,}", text.lower()))


def _pick_family(account_name, rng):
    """Pick a family, with a mild deterministic per-account flavour bias so
    accounts don't all sound identical — but every account uses every family."""
    acc_rng = random.Random(f"family_bias:{account_name or 'default'}")
    weights = []
    for name, pool, w in FAMILY_WEIGHTS:
        # ±30% per-account bias, keeps all families alive
        bias = 0.7 + 0.6 * acc_rng.random()
        weights.append(w * bias)
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if r <= acc:
            return FAMILY_WEIGHTS[i]
    return FAMILY_WEIGHTS[0]


def _make_candidate(family_name, pool, rng):
    if family_name == "aesthetic":
        tmpl = rng.choice(AESTHETIC_TEMPLATES)
        adj = rng.choice(AESTHETIC_ADJ)
        text = tmpl.format(adj=adj, adj_cap=adj.capitalize(), noun=rng.choice(AESTHETIC_NOUN))
    else:
        text = rng.choice(pool)
    if rng.random() < 0.20:  # ~20% get one emoji
        text = text.rstrip(".! ") + " " + rng.choice([e for e in EMOJI_POOL if e])
    return " ".join(text.split())


def _cluster_score(candidate, recent_words_list):
    cw = _content_words(candidate)
    sig = len(cw & _CLUSTER_WORDS)
    overlap = sum(1 for rw in recent_words_list if len(cw & rw) >= 2)
    return sig + overlap * 3


def get_unique_comment(account_name=None):
    """Thread-safe, globally unique, natural comment. FIX 13c: multi-family
    pool + anti-clustering against this account's recent comments."""
    with COMMENT_LOCK:
        used = load_used_comments()
        rng = random.Random()
        key = account_name or "default"
        recent = _RECENT.setdefault(key, deque(maxlen=_RECENT_N))
        recent_words = [_content_words(r) for r in recent]

        best, best_score = None, 10 ** 9
        for _ in range(40):
            _name, pool, _w = _pick_family(account_name, rng)
            cand = _make_candidate(_name, pool, rng)
            if cand in used or len(cand) < 8 or len(cand) > 150:
                continue
            s = _cluster_score(cand, recent_words)
            if s < best_score:
                best, best_score = cand, s
            if s == 0:
                break

        if best is None:
            # Extremely rare: everything collided. Plain reaction fallback.
            for cand in rng.sample(REACTIONS, len(REACTIONS)):
                if cand not in used:
                    best = cand
                    break
            if best is None:
                best = f"This is great! ({rng.randint(100, 999)})"

        used.add(best)
        save_used_comments(used)
        recent.append(best)
        return best


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    acct = sys.argv[2] if len(sys.argv) > 2 else "demo"
    print(f"Registry me already used: {len(load_used_comments())} comments")
    print(f"Sample fresh comments for account '{acct}':")
    for _ in range(n):
        print("  -", get_unique_comment(acct))
