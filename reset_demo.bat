@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ==================================================
echo   Reset demo scene  -  restore the bug in stats.py
echo ==================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python not found in PATH.
    pause
    exit /b 1
)

python reset_demo.py
if errorlevel 1 goto fail

echo.
pause
exit /b 0

:fail
echo.
echo [ERROR] Reset failed. Scroll up for the reason.
pause
exit /b 1
