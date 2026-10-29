"""护栏专项验证：bash 的 Windows 改写/拦截 + 循环的空转刹车。

跑法：python tests/verify_guard.py
不联网、不需要 Key，改动只发生在临时副本里。
"""
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

# 先把工作区指向临时副本，避免污染演示用的 stats.py
_TMP = Path(tempfile.mkdtemp(prefix="guard_"))
_TMPWS = _TMP / "workspace"
shutil.copytree(ROOT / "workspace", _TMPWS, ignore=shutil.ignore_patterns("__pycache__"))
os.environ["WORKSPACE_DIR"] = str(_TMPWS)

import agent.config as _cfg          # noqa: E402
_cfg.WORKSPACE = _TMPWS

import agent.tools as _tools         # noqa: E402
_tools.WORKSPACE = _TMPWS

import agent.loop as _loop           # noqa: E402
_loop.WORKSPACE = _TMPWS

from agent.tools import bash         # noqa: E402
from agent.loop import Agent         # noqa: E402

ok_all = True


def check(name, cond):
    global ok_all
    ok_all &= bool(cond)
    print(("  PASS " if cond else "  FAIL ") + name)
    return cond


class MockLLM:
    def __init__(self, script):
        self.script = list(script)
        self.i = 0

    def chat(self, messages, tools=None, temperature=0.2):
        if self.i < len(self.script):
            r = self.script[self.i]
            self.i += 1
            return r
        return {"content": "（脚本用尽，直接结束）", "tool_calls": []}


def test_bash_windows():
    print("\n== bash 的 Windows 适配 ==")

    # 1) `| tail -5` 应被自动去掉，命令仍然真的执行（带 bug 时 exit_code=1）
    out = bash("python test_stats.py 2>&1 | tail -5")
    check("`| tail -5` 被自动改写", "已自动去掉" in out)
    check("命令仍真实执行（exit_code=1，因为 bug 还在）", "exit_code=1" in out)
    check("拿到了测试输出（含 FAIL）", "FAIL" in out)

    # 2) 不能安全改写的 Unix 命令应当被拒绝，并给出替代方案
    try:
        bash("cat stats.py")
        check("`cat` 被拒绝", False)
    except ValueError as e:
        check("`cat` 被拒绝且提示 cmd 等价命令", "cmd" in str(e) and "dir" in str(e))

    # 3) 输出截断：200 行以内原样，超出则保留尾部
    out = bash('python -c "print(chr(10).join(str(i) for i in range(300)))"')
    check("超长输出被截断并告知", "已截断" in out and "300" in out.split("--- stderr ---")[0])


def test_repeat_guard():
    print("\n== 重复调用拦截（模型原地打转时刹车） ==")
    same = {"command": "python test_stats.py 2>&1 | tail -5"}
    script = [{"content": None, "tool_calls": [{"name": "bash", "arguments": dict(same)}]} for _ in range(6)]
    events = []
    result = Agent(MockLLM(script), mcp_clients=[], max_steps=8).run(
        "跑测试", events.append, threading.Event()
    )

    obs = [e for e in events if e["type"] == "observation"]
    intercepted = [e for e in obs if "已拦截重复调用" in e["content"]]
    executed = [e for e in obs if "exit_code=" in e["content"]]
    check("只有第一次真的执行了", len(executed) == 1)
    check("后续相同失败调用被拦截", len(intercepted) >= 2)
    check("连续失败后自动停止（不是耗尽步数）", "已停止" in result)


def test_guard_allows_rerun_after_fix():
    print("\n== 改完文件后，同一条测试命令允许重跑 ==")
    OLD = '        return 0.0  # BUG（演示用）：空列表应该抛 ValueError，这里却返回 0'
    NEW = '        raise ValueError("mean() arg is an empty sequence")'
    script = [
        {"content": None, "tool_calls": [{"name": "bash", "arguments": {"command": "python test_stats.py"}}]},
        {"content": None, "tool_calls": [{"name": "edit", "arguments": {"path": "stats.py", "old_string": OLD, "new_string": NEW}}]},
        {"content": None, "tool_calls": [{"name": "bash", "arguments": {"command": "python test_stats.py"}}]},
        {"content": "修好了，测试通过。", "tool_calls": []},
    ]
    events = []
    result = Agent(MockLLM(script), mcp_clients=[], max_steps=8).run(
        "修 bug 并验证", events.append, threading.Event()
    )
    obs = [e for e in events if e["type"] == "observation"]
    bash_obs = [e["content"] for e in obs if e["tool"] == "bash"]
    check("两次 bash 都真的执行了（未被误拦）", len(bash_obs) == 2)
    check("修复前 exit_code=1", "exit_code=1" in bash_obs[0])
    check("修复后 exit_code=0", "exit_code=0" in bash_obs[1])
    check("给出了 final 结论", "测试通过" in result)


if __name__ == "__main__":
    try:
        test_bash_windows()
        test_repeat_guard()
        test_guard_allows_rerun_after_fix()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print("\n========================================")
    print("全部通过 ✅" if ok_all else "存在失败 ❌")
    sys.exit(0 if ok_all else 1)
