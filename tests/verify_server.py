"""服务器冒烟测试：在子线程起 uvicorn，用标准库 urllib 验证静态页与 /api/tree。"""
import sys, os, time, threading, urllib.request, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import uvicorn
from server.app import app

PORT = 8799
URL = f"http://127.0.0.1:{PORT}"

def run():
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")

t = threading.Thread(target=run, daemon=True)
t.start()
for _ in range(50):
    try:
        urllib.request.urlopen(URL + "/api/tree", timeout=0.5); break
    except Exception:
        time.sleep(0.1)

ok = True
# 静态页
html = urllib.request.urlopen(URL + "/", timeout=2).read().decode()
ok &= ("我的 Cursor" in html)
print(f"  [{'PASS' if ok else 'FAIL'}] 静态首页可访问，含标题")

# /api/tree 返回工作区结构
data = json.loads(urllib.request.urlopen(URL + "/api/tree", timeout=2).read())
names = [c["name"] for c in data["children"]]
ok &= ("stats.py" in names and "test_stats.py" in names)
print(f"  [{'PASS' if ok else 'FAIL'}] /api/tree 返回 workspace 结构: {names}")

# /api/file 读文件（越界应报错）
r = urllib.request.urlopen(URL + "/api/file?path=stats.py", timeout=2)
print(f"  [PASS] /api/file 正常返回 stats.py")

print("\n服务器冒烟测试", "✅" if ok else "❌")
sys.exit(0 if ok else 1)
