@echo off
echo ============================================================
echo  IG Research Toolkit - Dependency Installer (Windows)
echo ============================================================
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python install nahi hai ya PATH me nahi.
    echo https://www.python.org/downloads/ se Python 3.10+ install karo
    echo INSTALL karte waqt "Add Python to PATH" tick karna MAT bhoolna!
    pause
    exit /b 1
)
echo [1/4] pip upgrade...
python -m pip install --upgrade pip
echo.
echo [2/4] core dependencies...
python -m pip install requests pycryptodomex pillow
echo.
echo [3/4] optional: curl_cffi (TLS impersonation - login flow ke liye)
python -m pip install curl_cffi || echo (optional - fail hua to bhi chalega)
echo.
echo [4/4] selftest...
python selftest.py
echo.
echo ============================================================
echo  DONE! Ab RUN_GUIDE.md follow karo.
echo ============================================================
pause
