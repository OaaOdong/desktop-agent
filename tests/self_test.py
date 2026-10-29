"""端到端自测：不依赖网络 / API Key，用 mock LLM 验证核心逻辑。

运行：
  cd desktop-agent
  python tests/self_test.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent.config import WORKSPACE
from agent.tools import read_file, write_file, edit_file, bash, TOOLS
from agent.mcp_client import MCPClient
from agent.loop import Agent

import tempfile, shutil, atexit
from pathlib import Path

# 在临时副本里跑测试，绝不污染交付用的 workspace/（里面故意留了 bug 供演示）
_TMP = tempfile.mkdtemp(prefix="desktop-agent-selftest-")
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))
for _f in ("stats.py", "test_stats.py", "README.md"):
    shutil.copy(WORKSPACE / _f, Path(_TMP) / _f)
_TMPWS = Path(_TMP)
import agent.config as _cfg, agent.tools as _tools, agent.loop as _loop
_cfg.WORKSPACE = _TMPWS
_tools.WORKSPACE = _TMPWS
_loop.WORKSPACE = _TMPWS


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def test_tools():
    print("\n== 四工具单元测试 ==")
    ok = True

    # read：带行号 + 分页提示
    txt = read_file("stats.py", limit=3)
    ok &= check("read 返回带行号文本", isinstance(txt, str) and "1\t" in txt)

    # read：越界被拒
    try:
        read_file("../.gitignore")
        ok &= check("read 越界被拒", False)
    except ValueError:
        ok &= check("read 越界被拒", True)

    # write：原子写 + 行数提示
    msg = write_file("__selftest__.txt", "line1\nline2\n")
    ok &= check("write 创建并报告行数", "2 行" in msg and os.path.exists(_TMPWS / "__selftest__.txt"))

    # edit：唯一替换成功
    before = read_file("__selftest__.txt")
    msg2 = edit_file("__selftest__.txt", "line1", "LINE1")
    ok &= check("edit 唯一替换成功", "1 处替换成功" in msg2 and "LINE1" in read_file("__selftest__.txt"))

    # edit：不唯一报错（不猜）—— 先构造一个含重复片段的文件
    write_file("__dup__.txt", "alpha\nbeta\nalpha\n")
    try:
        edit_file("__dup__.txt", "alpha", "ALPHA")  # 出现 2 次，应报错
        ok &= check("edit 不唯一报错", False)
    except ValueError:
        ok &= check("edit 不唯一报错", True)
    (WORKSPACE / "__dup__.txt").unlink(missing_ok=True)
    (_TMPWS / "__dup__.txt").unlink(missing_ok=True)

    # bash：exit_code + stdout/stderr
    out = bash("python -c \"print('hi')\"", timeout=15)
    ok &= check("bash 返回 exit_code=0 与 stdout", "exit_code=0" in out and "hi" in out)

    # bash：非零退出也正常返回
    out2 = bash("python -c \"import sys; sys.exit(3)\"", timeout=15)
    ok &= check("bash 非零退出正常返回", "exit_code=3" in out2)

    # 清理
    (WORKSPACE / "__selftest__.txt").unlink(missing_ok=True)
    (_TMPWS / "__selftest__.txt").unlink(missing_ok=True)
    return ok


def test_mcp():
    print("\n== MCP stdio 客户端 ==")
    ok = True
    server = os.path.join(ROOT, "example_server", "weather_server.py")
    client = MCPClient("weather", sys.executable, [server])
    try:
        client.initialize()
        tools = client.list_tools()
        ok &= check("MCP list_tools 含 get_weather", any(t["function"]["name"] == "get_weather" for t in tools))
        text, is_err = client.call_tool("get_weather", {"city": "杭州"})
        ok &= check("MCP call get_weather 成功", (not is_err) and "杭州" in text)
    except Exception as e:
        print("  MCP 测试异常：", e)
        ok = False
    finally:
        client.close()
    return ok


class MockLLM:
    """脚本化 LLM：按预定顺序返回 tool_calls，最后给结论。"""
    def __init__(self, script):
        self.script = list(script)
        self.i = 0

    def chat(self, messages, tools=None, temperature=0.2):
        if self.i < len(self.script):
            r = self.script[self.i]
            self.i += 1
            return r
        return {"content": "已完成", "tool_calls": []}


def test_loop():
    print("\n== Agent 循环端到端 ==")
    ok = True
    OLD = '        return 0.0  # BUG（演示用）：空列表应该抛 ValueError，这里却返回 0'
    NEW = '        raise ValueError("mean() arg is an empty sequence")'
    script = [
        {"content": None, "tool_calls": [{"name": "read", "arguments": {"path": "stats.py"}}]},
        {"content": None, "tool_calls": [{"name": "edit", "arguments": {"path": "stats.py", "old_string": OLD, "new_string": NEW}}]},
        {"content": None, "tool_calls": [{"name": "bash", "arguments": {"command": "python test_stats.py"}}]},
        {"content": "已修复 mean([]) 的 bug：空列表现在抛 ValueError，测试通过。", "tool_calls": []},
    ]
    llm = MockLLM(script)
    agent = Agent(llm, mcp_clients=[], max_steps=8)

    events = []
    import threading
    interrupt = threading.Event()
    final = agent.run("修复 stats.py 里 mean 对空列表的 bug 并跑测试", events.append, interrupt)

    actions = [e for e in events if e["type"] == "action"]
    obss = [e for e in events if e["type"] == "observation"]
    ok &= check("循环产生了 3 次工具调用", len(actions) == 3)
    ok &= check("最后给出 final", any(e["type"] == "final" for e in events))
    ok &= check("有可见的 observation", len(obss) >= 3)

    # 验证副作用：临时副本里的 stats.py 真的被改了，且测试通过
    try:
        ns = {}
        code = (_TMPWS / "stats.py").read_text(encoding="utf-8")
        exec(compile(code, "stats.py", "exec"), ns)
        raised = False
        try:
            ns["mean"]([])
        except ValueError:
            raised = True
        ok &= check("stats.py 真的被改：mean([]) 抛 ValueError", raised)
    except Exception as e:
        print("  验证副作用异常：", e)
        ok = False
    return ok


if __name__ == "__main__":
    results = []
    results.append(test_tools())
    results.append(test_mcp())
    results.append(test_loop())
    print("\n========================================")
    print("全部通过 ✅" if all(results) else "存在失败 ❌")
    sys.exit(0 if all(results) else 1)
