"""生成真实 trace：用 MockLLM 驱动真实 Agent 代码，跑一段"先失败再恢复"的演示，
输出可直接贴进 docs/trace.md 的事件流。运行：python tests/generate_trace.py

注：本脚本在临时副本工作区里跑，不会改动交付用的 workspace/stats.py。
"""
import os, sys, json, threading, tempfile, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import agent.config as _cfg
import agent.tools as _tools
import agent.loop as _loop
from agent.loop import Agent
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="desktop-agent-trace-")
for _f in ("stats.py", "test_stats.py", "README.md"):
    shutil.copy(_cfg.WORKSPACE / _f, Path(_TMP) / _f)
_TMPWS = Path(_TMP)
_cfg.WORKSPACE = _TMPWS
_tools.WORKSPACE = _TMPWS
_loop.WORKSPACE = _TMPWS


class MockLLM:
    def __init__(self, script):
        self.script = list(script); self.i = 0
    def chat(self, messages, tools=None, temperature=0.2):
        if self.i < len(self.script):
            r = self.script[self.i]; self.i += 1; return r
        return {"content": "已完成", "tool_calls": []}


BUG_LINE = '        return 0.0  # BUG（演示用）：空列表应该抛 ValueError，这里却返回 0'
FIX_LINE = '        raise ValueError("mean() arg is an empty sequence")'

# 故意先犯一个错（old_string 太短、不唯一），再纠正——演示失败与恢复
script = [
    {"content": None, "tool_calls": [{"name": "read", "arguments": {"path": "stats.py"}}]},
    {"content": None, "tool_calls": [{"name": "edit", "arguments": {"path": "stats.py", "old_string": "n", "new_string": "X"}}]},  # 不唯一 → 失败
    {"content": None, "tool_calls": [{"name": "edit", "arguments": {"path": "stats.py", "old_string": BUG_LINE, "new_string": FIX_LINE}}]},  # 纠正 → 成功
    {"content": None, "tool_calls": [{"name": "bash", "arguments": {"command": "python test_stats.py"}}]},
    {"content": "已修复 mean([]) 的 bug：空列表现在抛 ValueError，3 个测试全部通过。", "tool_calls": []},
]

agent = Agent(MockLLM(script), mcp_clients=[], max_steps=8)
events = []
agent.run("修复 stats.py 里 mean 对空列表的 bug 并跑测试", events.append, threading.Event())

out = []
for e in events:
    t = e["type"]
    if t == "system": out.append(f"[system] {e['text']}")
    elif t == "step": out.append(f"\n--- 第 {e['step']} 步 ---")
    elif t == "message": out.append(f"[assistant] {e['content']}")
    elif t == "action": out.append(f"[action] 🔧 {e['tool']}  {json.dumps(e['args'], ensure_ascii=False)}  ({e['source']})")
    elif t == "observation":
        tag = "ERROR" if e["is_error"] else "ok"
        out.append(f"[observation/{tag}] ↳ {e['tool']}:\n{e['content']}")
    elif t == "final": out.append(f"[final] ✅ {e['content']}")

print("\n".join(out))
shutil.rmtree(_TMP, ignore_errors=True)
