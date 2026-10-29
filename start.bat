@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ==================================================
echo   Desktop Agent  -  one click launcher
echo ==================================================
echo Working directory: %CD%
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python not found in PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%v in ('python -c "import sys;print(sys.version.split()[0])"') do set PYVER=%%v
echo Python %PYVER%
echo.

echo [1/3] Checking dependencies ...
python -c "import fastapi, uvicorn, websockets" >nul 2>&1
if errorlevel 1 (
    echo       Installing requirements.txt ...
    python -m pip install -r requirements.txt
    if errorlevel 1 goto fail
) else (
    echo       backend deps OK
)

python -c "import webview" >nul 2>&1
if errorlevel 1 (
    echo       Installing pywebview ...
    python -m pip install pywebview==5.2
    if errorlevel 1 echo       [WARN] pywebview failed, will fall back to browser window.
) else (
    echo       pywebview OK
)
echo.

echo [2/3] Checking .env ...
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo       Created .env from template, opening Notepad ...
    echo       Fill OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL, save, close it.
    start /wait notepad ".env"
)
findstr /b /c:"OPENAI_API_KEY=sk-xxxxxxxx" ".env" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo       [WARN] .env still holds the placeholder key.
    echo              Window will open, but chatting fails until you set a real key.
    echo.
)
echo.

echo [3/3] Starting desktop window ...
echo       (close the window or press Ctrl+C here to quit)
echo.
python run_desktop.py
if errorlevel 1 goto fail

echo.
echo Exited.
pause
exit /b 0

:fail
echo.
echo [ERROR] Something failed above. Scroll up for the reason.
pause
exit /b 1
