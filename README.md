# Unified Instagram Automation & Control Hub (Merge Tool)

Ek unified web control panel aur 3 independent tools ka complete suite jo Instagram accounts ko safely aur efficiently manage karta hai.

---

## 📁 Project Structure

```text
merge tool/
├── control_panel/                  # Unified Web UI & API Hub (runs on port 8800)
│   ├── server.py                   # Central HTTP server & API gateway
│   ├── campaign.py                 # Multi-account bulk runner (DP, Bio, Posts, Privacy)
│   ├── bios.py                     # AI-free unique female bio generator (geo-aware)
│   ├── comments.py                 # Round-robin comment blast engine
│   ├── comment_worker.py           # Worker for individual comments
│   ├── health.py                   # Session & health monitoring manager
│   ├── health_worker.py            # Android endpoint health inspector
│   ├── static/index.html           # Modern dark-mode Web UI
│   ├── registry.json               # Modular tool discovery registry
│   └── run_hub.bat                 # 1-click launcher
│
├── Post uploader/                  # Tool 1: Post, DP, Bio & Story Uploader
│   ├── post_uploader.py
│   ├── ig_actions.py
│   ├── ig_profile.py
│   └── ...
│
├── ig_multi_matrix_engine/         # Tool 2: Matrix Comment Engine
│   ├── matrix_runner.py
│   ├── ig_actions.py
│   └── ...
│
└── login_tool_complete new updated/ # Tool 3: Advanced Per-Device Login Suite
    ├── ig_login_perdevice.py
    ├── panel.py
    └── ...
```

---

## 🚀 Quick Start

### 1. Launch Control Panel
Control panel ko shuru karne ke liye:
- **Option A**: Double click `control_panel/run_hub.bat`
- **Option B**: Run via terminal:
  ```bash
  cd control_panel
  python server.py
  ```
- Browser me open karein: **`http://127.0.0.1:8800`**

---

## ✨ Features

1. **Integrated Web UI**:
   - Sabhi 3 tools ek hi screen se control hote hain bina unke source code ko modify kiye.
   - Har tool independently updatable hai.

2. **Bulk Campaign (Multi-Account 1-Click)**:
   - 10+ accounts par ek sath action (DP upload, unique posts, privacy setting).
   - Person-specific unique photo enforcement (kisi ek person ki image dusre account me repeat nahi hogi).
   - Auto Female Bio generator jo geo/country ke hisab se authentic aesthetic bios banata hai.

3. **Comment Blast**:
   - Kisi bhi IG post URL par custom comments round-robin format me post karna.
   - Roster management: active accounts ko add ya remove karne ka live option.

4. **Account Health & Profile Inspector**:
   - Real-time status detection: `ALIVE`, `SUSPENDED`, `EXPIRED`, `CHALLENGE`, `PROXY_ERROR`.
   - Live profile stats:
     - 📸 **Posts count** (exact uploaded media count)
     - 🖼️ **DP Status** (profile picture uploaded vs blank)
     - 🔒 **Account Type** (Private vs Public)
     - 👥 **Follower & Following count**
   - Safe Account Removal / Archiving (suspended ya expired accounts ko backup me safely save karke remove karna).

---

## 🔒 Security & Privacy Notice
* Cookie files (`cookies_*.json`) aur sensitive proxy passwords `.gitignore` me protected hain taaki public leak na ho sake.
* Apna session add karne ke liye `cookies/` folder me apni cookie files paste karein ya UI se upload karein.
