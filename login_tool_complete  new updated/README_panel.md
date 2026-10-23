# IG Tools Panel — browser se tools chalao (bina command yaad rakhe)

## Start karna (Windows)
1. Poora zip ek folder me extract karo
2. **`run_panel.bat`** double-click karo
3. Browser me **http://127.0.0.1:8765** khul jayega

Manual start:
```
pip install flask requests pycryptodomex
python panel.py
```

## Panel me kya-kya hai

| Tab | Kaam |
|---|---|
| **Login** | Username/password/TOTP/country/proxy form → live output → status badge (SUCCESS / WRONG_PASSWORD / THROTTLED...) |
| **Baaki Tools** | tools.json registry se loaded tools (cookies check, batch login). Naya tool = nayi JSON entry |
| **History** | Saare purane runs + unka poora output (click karke dekho) — `panel_jobs.json` me save hoti hai |
| **Cookies** | Login success par bani session files — download/delete |
| **Help** | Status codes ka matlab + proxy tips |

## Naya tool connect karna (future tools ke liye)

`tools.json` kholo, `tools` array me entry add karo:

```json
{
  "id": "mera_tool",
  "label": "Mera Naya Tool",
  "script": "mera_script.py",
  "desc": "kya karta hai",
  "fields": [
    {"name": "acc", "label": "Account file", "type": "text", "required": true, "arg": "--accounts"},
    {"name": "count", "label": "Count", "type": "text", "positional": true},
    {"name": "fast", "label": "Fast mode", "type": "flag", "arg": "--fast"}
  ],
  "status_rules": [
    {"pattern": "DONE OK", "status": "SUCCESS"}
  ]
}
```

- `arg` = CLI flag (`--username` wagera), `positional: true` = bina flag ke value
- `type`: text / password / select (+options) / flag (checkbox)
- `status_rules` = output me pattern mile to history me wo status dikhega
- Script isi folder me honi chahiye. Panel refresh karo — tool "Baaki Tools" tab me dikh jayega.

## Zaroori
- Panel sirf **local** chalao (internet par expose mat karo — koi auth nahi hai)
- `cookies_*.json` + `panel_jobs.json` me sensitive data hota hai — share mat karo
- Login tips Help tab me hain (sticky proxy, 429 cooldown, needs_upgrade ignore karna)
