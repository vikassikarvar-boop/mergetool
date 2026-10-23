# IG Hub — ek jagah se teeno tools

**Start:** `run_hub.bat` double-click → http://127.0.0.1:8800 (sirf Python chahiye, koi install nahi)

## Kaise kaam karta hai
- Har tool apne folder me, apni script se, alag process me chalta hai. Hub unki files ko **kabhi edit nahi karta**.
- Multiple tasks ek saath chala sakte ho (sidebar me running count dikhta hai), live output, Stop button, History (`data/`).

## Features
1. **🛡️ Account Health Monitor**:
   - Sabhi accounts ki cookies ko real Instagram mobile API se test karta hai.
   - 🟢 `ALIVE`: Session theek hai aur active hai.
   - 🔴 `SUSPENDED`: Instagram ne account suspend / disable kar diya hai.
   - 🟡 `EXPIRED`: Session cookies expire ho gayi hain (re-login zaroori).
   - 🟠 `CHALLENGE`: Account par checkpoint / challenge laga hai (app me verify karo).
   - ⚠️ `PROXY_ERROR`: Proxy connection / payment issue.
   - 1-click me saare accounts check ho jaate hain aur results save rehte hain.
2. **🚀 Bulk Campaign**:
   - Har account ki alag images (folder/drop/import).
   - Ek click me sabhi accounts par DP, unique female bio, posts, private setting.
   - 'Select only Valid (Alive)' button se dead accounts auto-exclude ho jaate hain.
3. **💬 Comment Blast**:
   - Ek post par N comments sabhi active accounts me round-robin (har account 1-1 comment).
   - Active roster management: accounts ko on/off karo ya naya add/remove karo.
4. **Tools Runner**:
   - Login Tool, Post Uploader aur Multi Matrix Engine ke sabhi actions bina code chhede ek hi jagah se.

## Tool update karna
Tool ka folder badal do (script/code) — hub ko kuch nahi karna. Sirf agar CLI args badle:
- **Login tool:** uski apni `tools.json` me hi edit karo (hub wahi padhta hai, refresh karo).
- **Baaki:** `registry.json` me sirf us tool ka block edit karo.

## Naya tool jodna
`registry.json` → `tools` me block add karo (`folder`, `actions` → `script`, `fields`, `fixed`). Browser refresh.
Field types: `text`, `password`, `select`, `flag`, `multi`; `arg` = CLI flag, `positional` = bina flag.

## Note
- Interactive menu wali cheezein (jaise `ig_runner.py` bina args) panel me nahi — uske liye "Runner" action use karo.
- Sirf local (127.0.0.1) par chalta hai; auth nahi hai.
