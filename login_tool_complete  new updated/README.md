# ig_login_tool — Instagram Android API login (2026 CAA edition)

Instagram **451.0.0.53.80 Android** (version code **385713073**,
x-bloks-version-id `799db3e387d7a21a19c72918b8698b6cd28a1516ade363792c100ed45a0f9f0b`)
ke exact request formats par based. `templates.json` me real app ke headers + bodies
byte-for-byte stored hain; script runtime par sirf dynamic cheezein bharti hai:

- username / encrypted password (`#PWD_INSTAGRAM:4:<ts>:<blob>`)
- timestamps, per-run UUIDs (waterfall_id, pigeon, conn-uuid)
- **fresh server-issued `aac`** (process_client_data response se capture hota hai —
  purana static aac sirf fallback hai)
- server-issued `x-mid` (jo IG bhejta hai wahi aage use hota hai)
- 2FA TOTP code (authenticator secret se auto-generate, RFC 6238)

## Kaunsi script chalayein

| Script | Kab use karein |
|---|---|
| **`ig_login_perdevice.py`** | **MAIN TOOL** — proxy + country support, per-account unique device fingerprint, 2026 AP-2FA auto-complete |
| `ig_login.py` | Single account, bina proxy ke (direct connection). Same 2026 flow |
| `batch_login_uk.py` | Pending accounts ka batch (proxy list rotate karta hai) |
| `check_cookies.py` | Saved cookies/session alive hain ya nahi |
| `check_pending.py` | Pending accounts list |
| `selftest.py` | Offline format/patching self-test |
| `force_ipv4.py` | IPv6 issue ho to wrapper |

### Run command (proxy + country ke saath)

```
pip install requests pycryptodomex

python ig_login_perdevice.py --username U --password P --totp-secret BASE32SECRET ^
    --country PH --proxy "http://user:pass@gw.dataimpulse.com:PORT"
```

Flags sirf `ig_login_perdevice.py` me hain: `--country` (PH/US_EST/US_PST/UK/IN),
`--proxy`, `--timezone-offset`, `--output`. (`ig_login.py` in flags ko accept
NAHI karta — purani "unrecognized arguments" error isi wajah se aati thi.)

## Login flow

```
PATH A: legacy /api/v1/accounts/login/  (proxy-safe, plain TLS)
        -> 2026 me Instagram is endpoint par har version ke liye
           "needs_upgrade" deta hai (deprecated). Ye fail hona NORMAL hai.
PATH B: bloks CAA flow (asal rasta):
 1. POST /api/v1/launcher/mobileconfig/
 2. POST /api/v1/attestation/create_android_keystore/     (fail-safe)
 3. GET  /api/v1/qe/sync/          -> password encryption key (header se)
 4. POST bloks .../caa.login.process_client_data_and_redirect/  -> FRESH aac capture
 5. POST bloks .../reg.youthregulation.deletepregent.async/
 6. POST bloks .../caa.phone.number.prefill.async.controller/
 7. POST bloks .../caa.login.oauth.token.fetch.async/
 8. POST bloks .../caa.login.async.send_login_request/
 9. Response diagnosis (2026 format):
      - credentials embedded  -> SUCCESS
      - 2FA_AP  -> entrypoint_async -> code_entry -> code_entry_async (TOTP auto)
      - 2FA_OLD -> purana two_step_verification flow (fallback)
      - WRONG_PASSWORD / NOT_FOUND / DISABLED / CHALLENGE -> clear message + exit 2
10. Success par: IG-Set-Authorization Bearer IGT:2 token + sessionid cookies
11. Verify: GET /api/v1/multiple_accounts/get_account_family/
```

## Response diagnosis (exit codes)

| Exit | Matlab |
|---|---|
| 0 | Login SUCCESS — cookies JSON save ho gayi |
| 2 | Diagnosed credential/account problem (neeche table) |
| 1 | Unexpected failure — response snippet print hota hai |

| Diagnosis | Instagram ka actual jawab | Matlab |
|---|---|---|
| `WRONG PASSWORD` | "Incorrect password — The password you entered is incorrect" | Username sahi, password galat |
| `USERNAME NOT FOUND` | "We can't find an account with ..." + signup funnel | Username typo/renamed/kabhi exist nahi kiya |
| `ACCOUNT RECOVERY SCREEN` | "Recover your account — login info no longer connected" | Account disabled/deleted, YA us proxy IP se repeated failures ka escalation — doosre fresh sticky proxy se retry karo |
| `CHECKPOINT/CHALLENGE` | checkpoint + challenge | Browser me www.instagram.com/challenge complete karo |
| `2FA_AP` (auto) | ap.two_step_verification.* screens | TOTP secret se code khud ban kar submit hota hai |

## Proxy zaroori baatein (2026)

- **STICKY exit IP zaroori hai** — poore login flow (8 requests) me ek hi IP
  rehni chahiye. Per-request ROTATING proxy par IG flow beech me 429/de-detect
  kar deta hai. (DataImpulse: alag-alag ports alag behaviour karte hain —
  test karke sticky wala port use karo.)
- **Har login attempt ke liye FRESH sticky session** — ek baar use hui IP
  jaldi burn hoti hai.
- Country preset (`--country PH`) timezone/locale bhi set karta hai —
  proxy ki exit country se match hona chahiye.

## Zaroori baatein

- **Sirf apne accounts** use karein. Dusron ke credentials ke saath use illegal hai.
- Instagram ToS automated clients allow nahi karta — checkpoint/ban risk hai.
- Output cookies file me poori session hoti hai — **kabhi share/upload na karein**.
- App version change hone par `templates.json`/`device_pool.json` ke version
  constants update karne pad sakte hain (abhi: 451.0.0.53.80 / 385713073).
  Fallback combos: 449.0.0.52.84/1079242191, 448.0.0.0.20/1065560286.

## Files

- `ig_login_perdevice.py` — main tool (proxy/country/device-pool support)
- `ig_login.py` — single-account direct login
- `batch_login_uk.py` — batch runner
- `templates.json` — real app request formats (451.0.0.53.80)
- `device_pool.json` — 89 real device profiles
- `check_cookies.py` / `check_pending.py` — session & pending checks
- `selftest.py` — offline self-test
- `force_ipv4.py` — IPv4 force wrapper


## FIX E — uTLS transport (curl_cffi) [22 Oct 2026]

Proxy se `send_login` pe **429 with 0-byte body** (jabki baaki endpoints 200)?
Wo IG ka TLS-fingerprint detection hai — python-requests ka ClientHello +
HTTP/1.1 login endpoint pe pakda jata hai. instagrapi ne 19-20 Oct 2026 ko
same fix merge kiya ("strict opt-in uTLS transport"); ye tool ab uska
faithful port karta hai.

Ek baar install karo:

    pip install "curl_cffi>=0.15.0"

Uske baad `--tls auto` (default) automatically uTLS use karega:
HTTP/2-only ALPN + TLS 1.3-only + EC curves X25519MLKEM768:X25519:P-256:P-384.

    --tls curl       force uTLS (missing ho to tool exit 2 ke saath batata hai)
    --tls requests   classic HTTP/1.1 (purana behavior)

Log me `[tls] uTLS transport ON ...` line dikhe = naya engine active hai.


## FIX O — WEB-MID capture (old-flow parity) [23 Oct 2026]

Mobile API `mid` cookie set nahi karta — purana flow ek **single web call**
(`https://www.instagram.com/`, same proxy ke through) se `Set-Cookie: mid`
capture karta tha. Ab naya tool bhi wahi karta hai:

* Har run ki shuruat me ek web GET → fresh `mid` (log line `[web-mid] ...`)
* Wahi mid jata hai: `x-mid` headers (pehli request se) + `machine_id`
  payloads (2FA/bloks) + saved cookies JSON (`cookies.mid` — old format)
* Agar IG run ke doran `ig-set-x-mid` se naya mid issue kare to server wala
  mid adopt ho jata hai (headers + payloads consistent rehte hain)
* Web call fail ho to flow nahi rukta — khali mid = fresh-device behavior
* ig_login.py ab templates ka STATIC captured mid kabhi nahi likhta
  (pehle sab accounts ki cookies file me same mid ja raha tha)


## FIX P — PATH A (legacy login) default OFF [23 Oct 2026]

`/api/v1/accounts/login/` (legacy) endpoint **deprecated** hai — har app
version pe `needs_upgrade` (400) deta hai. Pehle tool har attempt pe PATH A
try karta tha = **2 faaltu requests** (legacy qe/sync + legacy login) account
ki IP/session se IG pe jaati thi, phir PATH B (bloks CAA) chalta tha.

Ab: **seedha PATH B** (jaise instagrapi/aiograpi karte hain). Kam requests =
kam exposure. Legacy kabhi try karna ho (special case): `--try-legacy`.
