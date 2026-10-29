"""桌面窗口启动器。

双击运行：在本机起一个 FastAPI 服务，再用 pywebview 打开一个**原生窗口**
（没有浏览器地址栏——这是“桌面应用”而非“localhost 网页”的关键判定，P35）。

如果本机没装 pywebview，会自动降级为用默认浏览器打开 localhost 页面，
并给出安装提示（此时窗口带地址栏，仅适合本地开发，不算交付形态）。

用法：
  python run_desktop.py            # 起服务 + 开窗口
  python run_desktop.py --no-window # 只起服务（headless，方便 curl -N 看事件流，P35）
"""
import sys
import threading
import time
import webbrowser

import uvicorn

from server.app import app

PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"


def start_server():
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def wait_until_up(timeout=10):
    import urllib.request
    for _ in range(timeout * 10):
        try:
            urllib.request.urlopen(URL, timeout=0.5)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def main():
    headless = "--no-window" in sys.argv
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    if not wait_until_up():
        print("服务启动失败，请检查端口是否被占用。")
        return

    if headless:
        print(f"服务已启动（无窗口模式）：{URL}")
        print("用 `curl -N -X POST ...` 或前端连 /ws 即可看到事件流。Ctrl+C 退出。")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("已退出。")
        return

    try:
        import webview  # 第三方，需 pip install pywebview
        webview.create_window(
            "我的 Cursor · 桌面智能体",
            URL,
            width=1280,
            height=820,
            min_size=(900, 600),
        )
        webview.start()
    except ImportError:
        print("⚠️ 未检测到 pywebview，降级为浏览器打开（带地址栏，仅限本地开发）。")
        print("   交付形态请先安装：pip install pywebview，再运行本脚本。")
        webbrowser.open(URL)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("已退出。")


if __name__ == "__main__":
    main()
