"""桌面窗口启动器。

设计：
  后台线程起 FastAPI 服务（127.0.0.1:8765），主线程负责把 UI 页面承载到一个
  **无地址栏**的桌面窗口里。前端（ui/app.js）只通过 WebSocket + fetch 与本地服务
  通信，因此“窗口技术”可自由替换，不影响前端/后端逻辑。

窗口承载策略（按可靠性排序）：
  1. 系统已装的 Edge / Chrome 以 `--app` 模式打开本地页面。
     --app 模式会隐藏地址栏/工具栏，呈现为一个独立应用窗口，且复用系统已装的
     WebView2/Chromium，不依赖 pythonnet/COM，最稳。
  2.（可选）`--pywebview` 时优先用 pywebview 的原生 WebView2 窗口；若其在当前
     环境挂起或失败，自动回退到第 1 种方案。

用法：
  python run_desktop.py            # 起服务 + 开窗口（默认 Edge/Chrome --app）
  python run_desktop.py --pywebview# 优先 pywebview 原生窗口
  python run_desktop.py --no-window# 只起服务（headless，P35 事件流调试用）
"""
import os
import sys
import time
import threading
import subprocess
import webbrowser
import urllib.request

PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"
WINDOW_TITLE = "我的 Cursor · 桌面智能体"


def start_server():
    import uvicorn
    from server.app import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def wait_until_up(timeout=10):
    for _ in range(timeout * 10):
        try:
            urllib.request.urlopen(URL, timeout=0.5)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def find_browser():
    """返回 (exe路径, 支持_app模式) 或 None。优先 Edge/Chrome 的 --app（无地址栏）。"""
    import shutil
    for name in ("msedge.exe", "chrome.exe", "chromium.exe"):
        p = shutil.which(name)
        if p:
            return p, True
    extras = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for p in extras:
        if os.path.exists(p):
            return p, True
    # 退回系统默认浏览器（会带地址栏，仅兜底）
    return None, False


def launch_browser_window(url):
    """用系统浏览器以 --app（无地址栏）模式打开本地页面。成功返回 Popen，失败返回 None。"""
    exe, supports_app = find_browser()
    if exe and supports_app:
        try:
            proc = subprocess.Popen(
                [exe, f"--app={url}", "--new-window",
                 "--no-first-run", "--no-default-browser-check",
                 "--disable-features=ChromeWhatsNewUI"],
            )
            return proc
        except Exception:
            pass
    if exe:
        try:
            webbrowser.open(url)
            return None
        except Exception:
            pass
    return None


def _window_visible(title):
    """用 Win32 枚举可见窗口，判断标题包含给定字符串的窗口是否已出现。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = [False]

        def cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                if title in buf.value:
                    found[0] = True
                    return False  # 停止枚举
            return True

        EnumWindows = user32.EnumWindows
        EnumWindows.argtypes = [
            ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
            wintypes.LPARAM,
        ]
        EnumWindows.restype = wintypes.BOOL
        EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
        return found[0]
    except Exception:
        return False


def try_pywebview_watchdog(timeout=12):
    """在子线程里尝试 pywebview；用看门狗检测窗口是否真的出现，否则回退。
    返回 True 表示 pywebview 窗口已成功承载（调用方应等其关闭）；
    返回 False 表示挂起/失败，调用方应回退浏览器。"""
    try:
        import webview  # 第三方，需 pip install pywebview
    except ImportError:
        return False

    state = {}

    def opener():
        try:
            webview.create_window(
                WINDOW_TITLE, URL, width=1280, height=820, min_size=(900, 600),
            )
            state["created"] = True
            webview.start()
        except Exception as e:
            state["err"] = repr(e)

    th = threading.Thread(target=opener, daemon=True)
    th.start()

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _window_visible(WINDOW_TITLE):
            th.join()  # 等用户关闭窗口（webview.start 返回）
            return True
        time.sleep(0.2)

    if state.get("err"):
        sys.stderr.write(f"[warn] pywebview 启动异常，回退浏览器：{state['err']}\n")
    else:
        sys.stderr.write("[warn] pywebview 窗口未在限定时间内出现（疑似后端挂起），回退浏览器 --app 模式\n")
    return False


def main():
    headless = "--no-window" in sys.argv
    force_pywebview = "--pywebview" in sys.argv

    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    if not wait_until_up():
        print("服务启动失败，请检查端口是否被占用。")
        return

    if headless:
        print(f"服务已启动（无窗口模式）：{URL}")
        print("用前端连 /ws 即可看到事件流。Ctrl+C 退出。")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("已退出。")
        return

    # 优先 pywebview（可选）：带看门狗，挂起/失败自动回退浏览器
    if force_pywebview:
        if try_pywebview_watchdog():
            return
        proc = launch_browser_window(URL)
        if proc:
            proc.wait()
        return

    # 默认：直接用最稳的 Edge/Chrome --app（无地址栏），瞬时开窗
    proc = launch_browser_window(URL)
    if proc:
        proc.wait()
        return

    # 没找到系统浏览器，回退 pywebview 原生窗口
    if try_pywebview_watchdog():
        return

    # 连系统浏览器都找不到，最后兜底用 webbrowser（带地址栏）
    print("⚠️ 未找到可用浏览器，降级为默认浏览器打开（带地址栏，仅限本地演示）。")
    webbrowser.open(URL)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("已退出。")


if __name__ == "__main__":
    main()
