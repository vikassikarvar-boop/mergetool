@echo off
cd /d "%~dp0"
echo ============================================
echo   IG Tools Panel start ho raha hai...
echo   Browser me khulega: http://127.0.0.1:8765
echo   Band karne ke liye ye window close karo
echo ============================================
python -m pip install flask requests pycryptodomex --quiet 2>nul
if errorlevel 1 (
  py -m pip install flask requests pycryptodomex --quiet 2>nul
)
start "" "http://127.0.0.1:8765"
python panel.py 2>nul
if errorlevel 1 (
  py panel.py
)
pause
