@echo off
chcp 65001 >nul
title DesktopAgent 启动器

:: 若已有残留进程（占用 8765 端口），先结束，避免冲突
taskkill /f /im DesktopAgent.exe >nul 2>&1

:: 1) 启动本地服务（无窗口模式，绕开 pywebview 挂起）
start "" "%~dp0DesktopAgent.exe" --no-window

:: 2) 等几秒让服务起来
echo 正在启动本地服务，请稍候...
timeout /t 4 /nobreak >nul

:: 3) 用 Edge 的 --app 模式打开（无地址栏，呈现为独立应用窗口）
echo 正在打开桌面窗口...
set "EDGE="
for %%p in (
  "msedge.exe"
  "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
  "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
) do (
  if not defined EDGE (
    if exist %%p set "EDGE=%%p"
  )
)
if defined EDGE (
  start "" "%EDGE%" --app=http://127.0.0.1:8765/
) else (
  echo 未找到 Microsoft Edge，尝试用默认浏览器打开（会带地址栏）...
  start "" "http://127.0.0.1:8765/"
)

echo.
echo 窗口已打开。演示结束后，先关闭浏览器窗口，再回到这里按任意键退出并清理后台服务。
pause >nul
taskkill /f /im DesktopAgent.exe >nul 2>&1
echo 已结束后台 DesktopAgent 服务。
