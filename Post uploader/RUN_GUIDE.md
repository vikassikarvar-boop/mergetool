# 🚀 IG Research Toolkit — Complete Run Guide
================================================================
Folder-based automation: cookies/, dp/, post/, bio/ folders me
files dalo, commands chalao. Har account ka proxy, fingerprint,
language, timezone uski COOKIE FILE se AUTO apply hota hai.

----------------------------------------------------------------
## 📁 FOLDER STRUCTURE
```
ig_login_tool/
├── cookies/          ← account cookie files (.json, device-capture format)
│                        filename = account name (unicorn.json → "unicorn")
├── dp/               ← profile pictures (jpg/png/webp)
├── post/             ← post + story images (jpg/png/webp)
├── story/            ← OPTIONAL: sirf stories ke liye alag images
├── bio/              ← bio text: <account>.txt ya bio.txt (sabke liye)
├── ig_runner.py      ← main runner
├── runner_state.json ← auto-generated: used images ka record
└── install.bat       ← one-time dependency installer
```

----------------------------------------------------------------
## 1️⃣ INSTALL (one-time)
```
install.bat        (double-click — Windows)
```
Ya manually:
```
pip install requests pycryptodomex pillow curl_cffi
```

----------------------------------------------------------------
## 2️⃣ COOKIES FILES READY KARO
Har account ki file `cookies/` me dalo — ye EXACT format chahiye
(device-capture tool ka output):
```json
{
  "username": "account.name",
  "country": "UK",
  "cookies": { "sessionid": "...", "ds_user_id": "...", "mid": "...", "rur": "..." },
  "mobile_api_session": {
    "identifiers": { "android_id": "android-xxx", "uuids": ["<device-uuid>", "<family-uuid>"] },
    "device_info": { "app_version": "...", "api_level": "...", "android_version": "...",
                     "dpi": "...", "resolution": "...", "manufacturer": "...",
                     "model": "...", "cpu": "...", "build_number": "...",
                     "device_codename": "...", "locale": "en_GB" },
    "session_data": { "Authorization": "Bearer IGT:2:..." }
  },
  "fingerprint": { "proxy_url": "http://user:pass_country-gb_session-xxx_lifetime-168h@geo.iproyal.com:12321",
                   "proxy_country": "UK", "timezone_offset": 0 }
}
```
**Cookie file se ye sab AUTO apply hota hai:**
| Field | Kahan use hota hai |
|---|---|
| `fingerprint.proxy_url` | saare requests isi proxy se (sticky session) |
| `device_info.*` | exact User-Agent + configure device block |
| `identifiers.*` | x-ig-android-id / device-id / family-device-id headers |
| `fingerprint.timezone_offset` | x-ig-timezone-offset + configure |
| `device_info.locale` | app/device/mapped locale + accept-language |
| `cookies.rur` | ig-u-rur header (region code, e.g. RVA/CLN) |
| `session_data.Authorization` | Bearer auth |

⚠️ **RULES:** proxy_country = timezone = locale MATCH hona chahiye
(UK proxy → tz 0/3600 + en_GB). Mismatch = flag signal.

----------------------------------------------------------------
## 3️⃣ IMAGES + BIO READY KARO
```
dp/pic1.jpg              ← profile pictures
post/photo1.jpg          ← post/story images
bio/bio.txt              ← sab accounts ke liye common bio
bio/unicorn.txt          ← ya per-account specific bio (priority)
```
- Runner har baar **next-unused** image pick karta hai (repeat nahi)
- Images auto-convert: dp→JPEG, post/story→WEBP (real app jaisa)
- Badi images auto-resize max 1440px

----------------------------------------------------------------
## 4️⃣ COMMANDS

### ⭐ INTERACTIVE MENU (recommended — kuch yaad rakhne ki zaroorat nahi)
```
python ig_runner.py
```
Terminal me menu dikhega — number choose karo, tool khud poochhega:
- kis account par (ya sab par)
- kitne posts/stories upload karne hain
- caption kya ho

```
   IG RESEARCH TOOLKIT — MENU
  1. List (accounts + inventory)
  2. Info (profile status)
  3. Bio change
  4. DP upload
  5. Post upload  (kitne posts: poochha jayega)
  6. Story upload (kitni stories: poochha jayega)
  7. Account PRIVATE karo
  8. Account PUBLIC karo
  9. Combo (multiple actions ek saath)
  0. Exit
```

### Direct commands (agar terminal one-liner chahiye)
```bash
python ig_runner.py list                        # accounts + inventory
python ig_runner.py dp                          # sirf dp
python ig_runner.py post --count 3              # 3 posts (2-5 min gap har ek me)
python ig_runner.py story --count 2             # 2 stories
python ig_runner.py post --count 2 --caption "hi" --account unicorn
python ig_runner.py dp post                     # combo: dp + post
python ig_runner.py bio dp post private         # full combo
```

### Pacing (automatic)
- Ek hi action ke multiple uploads ke beech: **2-5 min**
- Alag actions ke beech: **8-20s**
- Alag accounts ke beech: **45-90s**

----------------------------------------------------------------
## 5️⃣ FULL EXAMPLE SESSION
```
1. install.bat                              (one-time)
2. cookies/unicorn.json dalo                (capture tool se export)
3. post/photo1.jpg + dp/pic1.jpg dalo
4. bio/bio.txt me text likho
5. python ig_runner.py list                 (verify: account + inventory)
6. python ig_runner.py info                 (session valid hai?)
7. python ig_runner.py story                (pehla action)
8. python ig_runner.py post --caption "hi"
9. python ig_runner.py bio
10. python ig_runner.py dp
```
Har action ke beech tool khud human-like delays + telemetry bhejta hai.
Multiple accounts ho to accounts ke beech 45-90s gap auto.

----------------------------------------------------------------
## 6️⃣ UNDER THE HOOD (request fidelity)
Har upload real-app capture-exact format me jaata hai:
- rupload: WEBP bytes, share_type, image_compression block, priority "u=6, i"
- configure: 25-34 field bodies, gallery-picker nav_chain, retry_context
- Companions: check_offensive preflight + pdq_hash_info + logging_client_events
- Timing: human-like jitter (1.5-4s gaps)
(Capture sources: fullaction.mitm + allactioninonefile.mitm)

----------------------------------------------------------------
## 7️⃣ TROUBLESHOOTING
| Problem | Fix |
|---|---|
| `login_required` | Session dead — fresh cookies export karo |
| `challenge_required` | Account restricted — app me manually solve karo, fir fresh cookies |
| `407 / proxy auth` | Proxy session expire — cookie file me naya session URL |
| Images khatam ("reuse") | post/ me aur images dalo, ya runner_state.json delete |
| Bio skip | bio/ me txt file check karo (naam: account.txt ya bio.txt) |

----------------------------------------------------------------
## 8️⃣ SAFETY RULES ⚠️
- SIRF apne/dummy accounts
- Cookies files KABHI public repo me mat dalo (live tokens hote hain)
- Password/TOTP/proxy creds kahin plain paste na karo
- Ek account par din me kuch hi actions rakho (burst = flag)
- Geo mismatch se bacho: proxy country = timezone = locale
