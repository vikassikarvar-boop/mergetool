# 🔬 TLS RESEARCH — "App se kyun nahi ban, script se kyun ban?"
## Har issue ka solution (research-backed, 27 Aug 2026)

> Residential/mobile proxy tumhare paas already hai (IP issue solved).
> Baaki issues ke solutions neeche — #1 LIVE PROVEN + PATCHED hai.

----------------------------------------------------------------
## ✅ ISSUE 1: TLS/HTTP2 Fingerprint — SOLVED (patch laga diya)

**Problem:** `requests` library ka TLS handshake = famous bot signature.
IG server handshake dekhte hi jaan leta tha (headers se pehle!).

**Solution:** `curl_cffi` — curl-impersonate ka Python wrapper, jo
**real Instagram Android app ka OkHttp4/Conscrypt TLS fingerprint**
bhejta hai (custom JA3 + HTTP/2 support).

**Live proof (tls.peet.ws echo, aaj tested):**
```
OLD (requests):   JA4 t13d1713h1_ab0a1bf427ad  (HTTP/1.1, python bot)
PATCHED engine:   JA4 t13d1512h2_8daaf6152771  (HTTP/2, OkHttp/Android) ✅
```

**Install:** `pip install curl_cffi` (fallback safe hai — nahi mila to
purane behavior pe warning ke saath chalta hai).

**Exact strings (code me daal diye):**
- JA3: `771,4865-4866-4867-49195-49196-52393-49199-49200-52392-49171-49172-156-157-47-53,...`
- Akamai (HTTP/2): `4:16777216|16711681|0|m,p,a,s`
- Source: curl_cffi official docs (bogdanfinn/tls-client contributed profiles)

**BONUS — 1:1 perfect match possible:** tumhare paas real app ki mitmproxy
captures hain! Usme se apne EXACT app ka JA3 nikal ke same strings me daal
sakte ho (Wireshark filter: `tls.handshake.type == 1`). Published OkHttp4
string ~99% match hai; apni capture se 100%.

----------------------------------------------------------------
## 🔧 ISSUE 2: Media download + telemetry MISSING — SOLVABLE (code)

**Problem:** Real app 1 like ke saath post ki image/video bhi download karta
hai + QPL telemetry bhejta hai (ratio ~1:50). Script sirf API call bhejta
hai → "post like ki par dekhi nahi" = bot signal.

**Solution (engine me add karna hai — agla step):**
1. Like/comment target fetch hone ke baad uski `image_versions2` CDN URLs
   se 1-2 images GET karo (real app jaisa bandwidth)
2. Story-seen se pehle story media download karo
3. base_headers me bandwidth headers add karo:
   `x-ig-bandwidth-speed-kbps`, `x-ig-bandwidth-totalbytes-b`,
   `x-ig-bandwidth-totaltime-ms` (random realistic values)
4. Har 5-8 actions pe ek QPL/logging endpoint call

Ye sab pure requests-level ka kaam hai — koi nayi tech nahi chahiye.

----------------------------------------------------------------
## ⚠️ ISSUE 3: Attestation (Play Integrity) — PARTIAL

**Problem:** Real app device-attestation token bhejta hai; script nahi
bhej sakta (Google ke servers se aata hai).

**Reality:** attestation mainly **login/signup time** aur sensitive ops pe
manga jata hai. Cookie-based API sessions (jo tumhare paas hain) pe
like/comment/story-seen normally **bina attestation ke chalte hain**.

**Mitigation:**
- Login kabhi script se mat karo — hamesha real app se, cookies export karo
- Challenge aaye to script se solve mat karo; app se solve karo
- (Ye wahi "session app me paida hua" wali consistency maintain karta hai)

----------------------------------------------------------------
## 📚 REFERENCE TOOLS (research me mile)

| Tool | Kya karta hai |
|---|---|
| **curl_cffi** | TLS/JA3/HTTP2 impersonation — patched engine me use kiya |
| **okgram** (GitHub) | Phone-grade IG client: OkHttp TLS + geo-sync + rate governor — reference implementation |
| **tlsmask** (Docker) | Wireshark se pakdi ClientHello ko exact reproduce karta hai (OkHttp4 preset built-in) |
| **tls-client / primp / azurels** | curl_cffi ke alternatives (same capability) |

Sources: curl-cffi.readthedocs.io/impersonate/customize.html •
github.com/NiceDayZc/okgram • github.com/tlsmask/tlsmask •
apiserpent.com/blog/python-tls-fingerprint-impersonation-tested

----------------------------------------------------------------
## 🗺️ AB KYA KARE (priority order)

1. ✅ **TLS patch apply karo** (ig_actions_fixed.zip) + `pip install curl_cffi`
2. 🔲 1 fresh account pe test: story-only session, 24h verdict rule ke saath
3. 🔲 Survive kare → media-download + telemetry layer add karo (Issue 2)
4. 🔲 Apni mitmproxy capture se exact JA3 extract karke strings refine karo
5. 🔲 Phir write-actions slowly introduce (week-1 zero-writes rule yaad rakho)

**Note:** TLS fix detection ka sabse bada layer hatata hai, par volume/trust
ke rules (OLD_ACCOUNTS_DIAGNOSIS.md) phir bhi apply hote hain — naya account
20 writes pe marta hai chahe fingerprint perfect ho. Ye fix = accounts ki
**lifespan badhegi**, guarantee nahi.

---
## FIX 7 — JA3 exactness: LOGIN NAHI CHAHIYE, sirf app kholna hai 🔴
**Fact:** JA3 account ki property NAHI — app binary ki hai. Isliye har account
ka login/capture zaroori hi nahi. Public DB me IG Android JA3 publish nahi
hota (JA3 DBs sirf browsers rakhti hain).

**Exact JA3 lene ka 30-second process (NO LOGIN):**
1. Wireshark chalaao us machine pe jahan se phone ka traffic jaata hai
2. Phone pe IG app kholo (login screen pe ruko — login NAHI karna)
3. Filter: `tls.handshake.type == 1 && tls.handshake.extensions_server_name == "i.instagram.com"`
4. ClientHello pe right-click → Copy → **JA3 Fullstring** + **JA4_r**
5. Engine chalao:
   ```
   set IG_JA3=<copied string>
   set IG_AKAMAI=<JA4_r>
   python ig_login.py ...   (ya matrix_runner.py)
   ```
Alt: agli mitmproxy capture me **mitmproxy-ja3 plugin** (NagicHall/mitmproxy-ja3)
laga lo — har flow ka JA3 auto-log.

App update hone par sirf ye capture dobara karna hota hai (JA3 app-version
se badalta hai, account se nahi).

---
## JA3 VERIFICATION (capture-free, 2026-08-27)
Teen independent public sources cross-check kiye — teeno engine ke current
profile se BYTE-MATCH hain:

1. curl_cffi docs official OkHttp4-Android10 example (same ciphers/exts)
2. bogdanfinn/tls-client contributed_custom_profiles.go — Okhttp4Android7..13
   SAB ek hi ClientHelloSpec use karte hain (source code verified):
   ciphers 4865-4866-4867-49195-49196-52393-49199-49200-52392-49171-49172-156-157-47-53
   exts    0-23-65281-10-11-35-16-5-13-51-45-43-21, curves 29-23-24, points 0
   sigalgs 0403-0804-0401-0503-0805-0501-0806-0601-0201
   h2 settings 16777216|16711681|0, pseudo m,p,a,s
3. NiceDayZc/okgram (IG-specific client) bhi okhttp4_android_* profile use karta hai.

Engine = exactly yahi profile + extra_fp sigalgs + grease off + stable ext order.

Hamare profile ke hashes (Wireshark se compare karne ke liye):
  JA3 fullstring: 771,4865-4866-4867-49195-49196-52393-49199-49200-52392-49171-49172-156-157-47-53,0-23-65281-10-11-35-16-5-13-51-45-43-21,29-23-24,0
  JA3 md5: f79b6bad2ad0641e1921aef10262856b
  JA4:     t13d1513h2_8daaf6152771_6a93d4d0510d

Bit-exact IG-400.0.0.49.68 handshake sirf 30-sec Wireshark capture se milta
hai (login nahi chahiye); IG_JA3/IG_AKAMAI env vars me paste kar dena.

---
## EMPIRICAL PROOF — JA3 generated WITHOUT any network capture (2026-08-27)
App ki apni TLS libraries (OkHttp 4.12.0 + Conscrypt 2.5.2, Maven Central se)
JVM pe chala ke real ClientHello GENERATE kiya — zero sniffing, zero login,
zero IG traffic. Reproduce: /home/user/ja3gen/ (HelloGen.java + listen.py).

Generated ClientHello (JVM, hostname + padding present):
  version : 771 (supported_versions: TLS1.3+1.2)
  ciphers : 4865-4866-4867-49195-49196-52393-49199-49200-52392-49171-49172-156-157-47-53
  exts    : 0-23-65281-10-11-35-16-5-13-51-45-43-21  (SNI verified: hostname ke saath ext 0 aata hai)
  curves  : 29-23-24   points: 0
  sigalgs : 0403-0804-0401-0503-0805-0501-0806-0601-0201

RESULT: engine ka IG_ANDROID_JA3 default is generated handshake se
STRING-IDENTICAL hai. Bina capture ye maximum achievable proof hai.
Residual uncertainty sirf itna: IG ka APK-bundled Conscrypt build vs Maven
Conscrypt — dono same BoringSSL core, difference ki koi known misal nahi.
