"""Female-style unique bio generator. Har bio unique: batch + pichhli used bios (data/bio_used.json) se match nahi hogi."""
import json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
USED = os.path.join(HERE, "data", "bio_used.json")

EMO = ["🌸", "✨", "🦋", "🌷", "💫", "🤍", "🌙", "☕", "📚", "🎧", "🌼", "🍒", "🫶", "🌻", "💗", "🧿", "🪩", "🎀", "🌈", "🍓", "🕊️", "💐", "🪷", "☁️"]

VIBES_EN = [
    "Living life in pastel shades", "Coffee, books & good vibes", "Soul full of sunshine", "Dreamer | Overthinker",
    "Soft heart, strong mind", "Making memories, not excuses", "Just a girl with big dreams", "Sunsets & sarcasm",
    "Wanderlust in my veins", "Handle with care, filled with love", "Main character energy", "Good vibes only",
    "Happiness looks good on me", "Growing, glowing, going", "Be kind to your mind", "Stay soft, stay strong",
    "Chasing sunsets & dreams", "Little things make me happy", "Not perfect, just real", "Smiling is my favourite",
    "Self love is the best love", "Bloom at your own pace", "Quietly confident", "Collecting moments, not things",
    "Gratitude over everything", "Catch me where the music is", "Find joy in the ordinary", "Classy with a little sass",
]
VIBES_HI = [
    "Dil se desi, vibes se global", "Chai, music aur thodi si pagalpanti", "Khud ki favourite hoon", "Zindagi ko simple rakhna",
    "Muskurana meri aadat hai", "Thodi shaant, thodi shararati", "Apni duniya ki queen", "Sapne bade, dil chhota nahi",
    "Hasna mana hai? Bilkul nahi", "Dil ki sachchi, baaton ki pakki", "Khushiyan chhoti, yaadein badi", "Jo hai wahi sach hai",
    "Simple hoon par special hoon", "Apni marzi ki malkin", "Vibes alag, andaaz alag",
]
INTERESTS = [
    "Music lover", "Travel addict", "Foodie", "Book nerd", "Dancer at heart", "Cat mom", "Dog lover", "Skincare & selfcare",
    "Fitness journey", "Art & chai", "Photography", "Mehendi lover", "Sunset chaser", "Plant mom", "Coffee addict",
    "Movie buff", "Cafe hopper", "Nature lover", "Fashion & fun", "Poetry & pages", "Gym & gratitude", "Cooking experiments",
    "Journaling", "Beach person", "Mountain girl", "Rainy day lover", "Dessert first", "Chai > everything",
]
TAIL = [
    "Be kind ✨", "Spread love 🤍", "Stay positive", "Grateful 🙏", "No drama please", "Dream big", "Always evolving",
    "Believe in magic", "Choose happiness", "Keep shining", "Trust the process", "Blessed", "Stay humble", "Smile more",
]
ZODIAC = ["Aries ♈", "Taurus ♉", "Gemini ♊", "Cancer ♋", "Leo ♌", "Virgo ♍", "Libra ♎", "Scorpio ♏", "Sagittarius ♐", "Capricorn ♑", "Aquarius ♒", "Pisces ♓"]
CITIES = {
    "IN": ["Mumbai", "Delhi", "Pune", "Jaipur", "Kolkata", "Bangalore", "Hyderabad", "Lucknow", "Chandigarh", "Ahmedabad", "Indore", "Goa"],
    "UK": ["London", "Manchester", "Birmingham", "Leeds", "Bristol", "Liverpool", "Edinburgh", "Glasgow", "Cardiff", "Leicester"],
    "US": ["New York", "Los Angeles", "Chicago", "Houston", "Miami", "Seattle", "Austin", "Boston", "San Diego", "Atlanta"],
    "PH": ["Manila", "Cebu", "Davao", "Quezon City", "Makati", "Baguio"],
}
COUNTRY_MAP = {"IN": "IN", "INDIA": "IN", "UK": "UK", "GB": "UK", "US": "US", "US_EST": "US", "US_PST": "US", "PH": "PH"}


def _load():
    try:
        with open(USED, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def mark_used(bios):
    s = _load()
    s.update(b.strip() for b in bios if b and b.strip())
    os.makedirs(os.path.dirname(USED), exist_ok=True)
    with open(USED, "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent=0)


def _one(country, style):
    c = COUNTRY_MAP.get((country or "").upper(), "IN")
    hinglish = style == "hinglish" or (style == "auto" and c == "IN" and random.random() < 0.45)
    vibe = random.choice(VIBES_HI if hinglish else VIBES_EN)
    ints = random.sample(INTERESTS, 3)
    e = random.sample(EMO, 3)
    city = random.choice(CITIES[c])
    layout = random.randint(0, 5)
    if layout == 0:
        s = f"{e[0]} {vibe}\n{ints[0]} | {ints[1]} | {ints[2]}\n📍{city}"
    elif layout == 1:
        s = f"{vibe} {e[0]}\n{e[1]} {ints[0]} & {ints[1]}\n{random.choice(TAIL)}"
    elif layout == 2:
        s = f"{e[0]} {ints[0]} {e[1]} {ints[1]}\n{vibe}\n{random.choice(ZODIAC)} | {city}"
    elif layout == 3:
        s = f"{vibe}\n{e[0]} {ints[0]} • {ints[1]} • {ints[2]} {e[1]}"
    elif layout == 4:
        s = f"{e[0]} {city} {e[1]}\n{vibe}\n{ints[0]} | {random.choice(TAIL)}"
    else:
        s = f"{ints[0]} {e[0]} {ints[1]}\n{vibe} {e[1]}\n{random.choice(ZODIAC)}"
    return s[:150]


def generate(n, countries=None, style="auto", exclude=()):
    """n bios -> list. countries = list (har bio ke liye optional country)."""
    used = _load() | set(exclude)
    out = []
    for i in range(n):
        ctry = countries[i] if countries and i < len(countries) else "IN"
        for _ in range(300):
            b = _one(ctry, style)
            if b not in used:
                break
        else:
            b = _one(ctry, style) + " " + random.choice(EMO)
        used.add(b)
        out.append(b)
    return out
