# ig_profile.py — Usage Guide
================================================================
Apne/dummy accounts ke profile actions — sab Instagram private API se.
Sirf APNE accounts par use karo.

----------------------------------------------------------------
## 1. Cookies file (NEW format — device-capture based)

Tool is format ko directly samajhta hai — kuch manually set karne
ki zaroorat NAHI. File se ye sab AUTO-apply hota hai:

| File ka field            | Kahan use hota hai                          |
|--------------------------|---------------------------------------------|
| `mobile_api_session.session_data.Authorization` | Bearer auth header |
| `identifiers.android_id` | `x-ig-android-id` header                    |
| `identifiers.uuids[0]`   | `x-ig-device-id` header                     |
| `identifiers.uuids[1]`   | `x-ig-family-device-id` header              |
| `device_info` (model, dpi, resolution, cpu, build...) | **exact User-Agent** + post/story metadata |
| `device_info.locale`     | app-locale/device-locale/UA locale           |
| `fingerprint.timezone_offset` | `x-ig-timezone-offset` (file ka value authoritative) |
| `fingerprint.proxy_url`  | **session proxy — automatic** (env proxy ignore hota hai) |
| `fingerprint.proxy_country` / `country` | `x-ig-app-startup-country` (UK→GB) |
| `cookies.rur`            | `ig-u-rur` header (region code, e.g. CLN)    |
| `cookies.*`              | cookie jar (domain .instagram.com)          |

Example UA jo file se build hota hai:
```
Instagram 400.0.0.49.68 Android (29/10; 560dpi; 1440x3120; HUAWEI; VOG-L29; HUVOG; kirin980; en_GB; 799297105)
```
(Legacy format — ig_login.py ka output — bhi kaam karta hai.)

----------------------------------------------------------------
## 2. Commands

Sab commands ka pattern:
```
python ig_profile.py --cookies <cookies_file.json> <action> [args]
```

| Command | Kya karta hai |
|---|---|
| `info` | Current profile state (bio, name, privacy, counts, dp url) |
| `bio "text"` | Biography set (edit_profile + set_biography dono) |
| `name "Full Name"` | Display name set |
| `dp photo.jpg` | Profile picture change |
| `private` | Account private karo |
| `public` | Account public karo |
| `post photo.jpg --caption "text"` | Feed me photo post |
| `delete <media_id ya pk>` | Apna post delete |

### Examples
```
python ig_profile.py --cookies cookies_duck.json info
python ig_profile.py --cookies cookies_duck.json private
python ig_profile.py --cookies cookies_duck.json public
python ig_profile.py --cookies cookies_duck.json bio "research dummy account"
python ig_profile.py --cookies cookies_duck.json name "Duck Research"
python ig_profile.py --cookies cookies_duck.json dp duck.jpg
python ig_profile.py --cookies cookies_duck.json post sunset.jpg --caption "test post"
python ig_profile.py --cookies cookies_duck.json delete 3499883712345678901
```

Notes:
- `delete` me sirf pk doge to media_id `<pk>_<uid>` auto ban jaata hai
- `dp`/`post` ke liye `pip install pillow` chahiye
- `bio`/`name` current baaki fields echo karta hai (kuch clear nahi hota)
- `--geo GB` se geo override possible (normally file ke values hi use hote hain)

----------------------------------------------------------------
## 3. Recommended test sequence (naye account par)

```
1. info                        # baseline dekho
2. private                     # privacy toggle test
3. public
4. bio "test bio"              # bio test
5. dp photo.jpg                # profile pic test
6. post photo.jpg --caption "t" # post test (output me media_id milega)
7. delete <wo media_id>        # cleanup test
8. info                        # final state verify
```
Har step 200/ok de — tabhi agla step karo.

----------------------------------------------------------------
## 4. Troubleshooting

| Response | Matlab | Fix |
|---|---|---|
| `login_required` / "You've been logged out" | Sessionid server par dead | Fresh cookies file export karo (kisi aur device se re-login/password-change se session rotate ho jaata hai) |
| `406` / challenge | Action flagged | 24-48h ruko, phir proxy session change karke try |
| `429` | Rate limit | Slow down — actions ke beech gap rakho |
| `checkpoint_required` | IG verification maang raha | App me login karke verify karo, phir fresh cookies |
| Proxy auth fail (407) | IPRoyal session expire (lifetime-59m) | Proxy URL me naya session-name |

----------------------------------------------------------------
## 4b. allactioninonefile.mitm capture-exact rewrite (latest)

Pure upload/edit flows ab LIVE CAPTURE se byte-match hain:

| Action | Format source (capture) |
|---|---|
| bio | `set_biography` {_uid, device_id, _uuid, raw_text} |
| name | `update_profile_name` PLAIN form (first_name + _uuid) |
| dp | JPEG rupload (moz q70, negative entity-rand) + GET resume-check + PLAIN form `change_profile_picture` (use_fbuploader=true, remove_birthday_selfie=False) |
| story | WEBP (libwebp28 q85) + share_type=stories + is_optimistic_upload=false; configure = 34 fields exact (media_folder=Instagram, camera_position=unknown, imported_taken_at...) |
| post | WEBP q88 + share_type=feed; configure = 25 fields (camera_entry_point=360, creation_logger_session_id, gallery-picker nav_chain 4 frags, crop_zoom...) |
| comment | pehle `check_offensive_comment` (media_id + comment_session_id) |
| dono uploads ke baad | `update_media_with_pdq_hash_info` + `logging_client_events` telemetry |
| rupload headers | priority "u=6, i", entity-type image/webp (story/post) |

Notable capture facts: real app ka `check_offensive_multi_text` story-time
par 400 bhi return karta hai — APP IGNORE karke aage badh jaati hai.

**400 ka root-cause (live investigation, 2026-08-26):**
- endpoint `warning/check_offensive_multi_text/` SERVER-SIDE BROKEN hai —
  empty/real/empty-list sab inputs par 400, 6 header variants par bhi 400
- sibling endpoint `media/comment/check_offensive_comment/` SAME session
  se 200 deta hai (`is_offensive:false`) → hamare format/session valid hain
- real IG app ko bhi apne capture me same 400 mila (allactioninonefile.mitm);
  feed-post ke liye real app ne ye call kiya hi nahi tha
- Tool ab: ye call **bhejta hi nahi** (dead endpoint — zero value). Function
  code me reserved hai, IG wapas laye to re-enable ho sakta hai.
- `check_offensive_comment` (comment flow) WORKING hai (200) — wo chalta hai

## 5. Telemetry fidelity (fullaction.mitm audit ke baad add kiya)

Real app har upload ke aas-paas saathi calls bhejta hai jo hamare tool
pehle nahi bhejta tha ("bilkul chup client" = flag signal). Ab:

- **Post/story upload se PEHLE**: `warning/check_offensive_multi_text/`
  (capture-exact format) + human-like jitter delay
- **Configure ke BAAD**: `media/update_media_with_pdq_hash_info/` +
  `graph.instagram.com/logging_client_events` (compressed pigeon events)
- **Geo guard**: cookies file me proxy na ho to WARNING (direct IP se
  geo-mismatch flag risk)

Known limitations (fabricate nahi kiye):
- `claims` HMAC (server-issued) — telemetry message me omitted
- `bk.attribution` device attestation — login gate par iska effect ho
  sakta hai (429)

----------------------------------------------------------------
## 6. Safety rules

- SIRF apne/dummy accounts
- Ek account par actions me gap rakho (burst = flag)
- Proxy country = file ka proxy_country hi rakho (mismatch signal)
- Cookies files kabhi public repo me mat dalo — inme LIVE tokens hote hain
- Password/TOTP/proxy creds chat ya kisi jagah plain paste hue ho to rotate karo
