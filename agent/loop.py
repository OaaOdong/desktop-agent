"""智能体循环（ReAct：Thought → Action → Observation）。

这是整个项目的“大脑”。模型没变，变的是它能接触世界，并且能看见后果：
  Agent = LLM + Tools + Loop
- LLM   只输出结构化意图（调哪个工具、传什么参数），不碰文件系统。
- Tools 你写的普通 Python 函数，执行权一直在代码手里。
- Loop  把执行结果原样塞回对话再问一次，让“一次猜测”变成“逐步逼近”。

三道护栏（P24）：步数上限(max_steps)、路径白名单(WORKSPACE)、bash 超时+可中断。
"""
import json
import platform
import re
import sys

from .config import WORKSPACE, MAX_STEPS
from .tools import TOOLS, TOOL_SCHEMAS, tool_source, kill_current_proc

SYSTEM_PROMPT = """你是运行在用户桌面工作区里的编程智能体（类似 Claude Code / Cursor 的 Agent）。
你只能访问工作区内的文件，所有文件操作都会被记录并展示给用户。

# 你能用的工具（只有四个）
- read(path[, offset, limit])：查看文件内容（带行号）。改之前先读，不要猜文件结构。
- edit(path, old_string, new_string)：精确替换。old_string 必须在文件中唯一，否则会报错——这是特性，不是 bug。
- write(path, content)：新建文件或整体覆盖。局部改动请用 edit，不要整文件重写。
- bash(command[, timeout])：跑 shell 命令（搜索、Git、安装、跑测试）。任何命令都要有 timeout。

# 工作纪律（决定你能不能拿高分）
1. 先 read 查证，再 edit 修改；edit 的 old_string 要长到能唯一确定位置。
2. 改完必须自己验证：用 bash 跑测试/运行程序，不要声称“已修复”而不验证。
3. 路径越界会被拒绝；不要试图读写工作区外的文件。
4. 用中文给出简洁的改动说明；复杂任务先列计划再执行。
5. 当工具返回错误（尤其是 edit 不唯一、read 文件不存在），按提示修正，不要硬来。
6. 不确定时多读、多跑命令，少猜。测试，是提示词的一部分。
7. 运行环境是【Windows + cmd.exe】：没有 tail/head/grep/sed/awk/ls/cat，
   输出已由 bash 工具自动截断，所以不要在命令里写这些 Unix 工具或管道，
   否则会报"不是内部或外部命令"并浪费一步。要用搜索请用 `findstr`。
8. 工作区的测试脚本是纯 unittest 风格，可直接 `python test_stats.py` 运行（无需 pytest）；
   若用 `python -m pytest` 也行（已预装）。跑测试只为了验证，别反复重试同一命令。
9. 同一个会失败的命令不要连续重复执行：失败一次就换思路，连续多次失败请直接说明卡点。
10. 收尾要短：任务完成后，最后一条消息只写「改了什么（文件+行号）」和「验证结果（命令+结论）」两行，
    不要整段复述前面已经展示过的内容——每次工具调用和输出用户都已经在界面上看见了。"""


def _env_block() -> str:
    """把真实的运行环境拼进系统提示，避免模型凭训练记忆猜（比如猜成 Linux）。"""
    try:
        entries = sorted(
            (p.name + "/" if p.is_dir() else p.name) for p in WORKSPACE.iterdir()
        )
    except OSError:
        entries = []
    listing = ", ".join(entries) if entries else "(空)"
    return (
        "\n# 运行环境（以实际检测为准，不要凭印象猜系统）\n"
        f"- 操作系统：{platform.system()} {platform.release()}；命令解释器是 Windows cmd.exe。\n"
        f"- bash 的 cwd 即工作区 {WORKSPACE}，命令里直接用相对路径即可。\n"
        f"- Python 解释器：{sys.executable}\n"
        f"- 工作区现有文件：{listing}\n"
    )


class Agent:
    def __init__(self, llm, mcp_clients=None, max_steps: int = MAX_STEPS):
        self.llm = llm
        self.mcp_clients = mcp_clients or []
        self.max_steps = max_steps

        # 合并内置工具 + MCP 工具 schema，并记录来源用于路由与展示
        self.schemas = list(TOOL_SCHEMAS)
        self.mcp_tools: dict[str, object] = {}  # name -> MCPClient
        for client in self.mcp_clients:
            for t in client.list_tools():
                self.schemas.append(t)
                self.mcp_tools[t["function"]["name"]] = client
                tool_source[t["function"]["name"]] = f"mcp:{t['_mcp_server']}"

    def _route(self, name: str):
        """返回 (callable_or_None, source)。内置工具用本地函数，MCP 工具用客户端转发。"""
        if name in TOOLS:
            return TOOLS[name], "builtin"
        if name in self.mcp_tools:
            return self.mcp_tools[name], f"mcp:{self.mcp_tools[name].name}"
        return None, "unknown"

    def _format_obs(self, obs):
        """把工具返回值整理成 (text, is_error, image_block_or_None)。"""
        if isinstance(obs, dict) and obs.get("__image__"):
            return None, False, obs
        if isinstance(obs, Exception):
            return f"工具执行出错：{obs}", True, None
        return str(obs), False, None

    def run(self, task: str, emit, interrupt):
        """主循环。emit(dict) 推送事件；interrupt 是带 is_set() 的对象，用于中断。"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + _env_block()},
            {"role": "user", "content": task},
        ]
        emit({"type": "system", "text": f"智能体就绪 · 工作区 {WORKSPACE} · 最多 {self.max_steps} 步"})
        emit({"type": "system", "text": f"已挂载工具：{', '.join(sorted(set(tool_source)))}"})

        # 空转护栏：记住每个调用签名的结果，以及当时的“工作区修改计数”。
        # 只有在“同一条命令失败过 + 期间文件没变”时才拦——所以修完 bug 再跑同一条测试是允许的。
        seen: dict[str, dict] = {}
        mutations = 0        # write/edit 成功次数
        consec_fail = 0      # 连续失败次数

        for step in range(1, self.max_steps + 1):
            if interrupt.is_set():
                kill_current_proc()
                emit({"type": "interrupted", "text": "已中断：用户点了停止。"})
                return "（已被用户中断）"

            emit({"type": "step", "step": step})
            try:
                reply = self.llm.chat(messages, tools=self.schemas)
            except Exception as e:
                emit({"type": "error", "text": f"调用模型失败：{e}"})
                return f"（模型调用失败：{e}）"

            # 模型给出的文字（可能是思考/计划）
            if reply["content"]:
                emit({"type": "message", "role": "assistant", "content": reply["content"]})

            # 没有工具调用 → 任务完成
            if not reply["tool_calls"]:
                emit({"type": "final", "content": reply["content"] or "（无文字回复）"})
                return reply["content"] or ""

            # 把 assistant 的 tool_calls 原样记录回对话
            messages.append({
                "role": "assistant",
                "content": reply["content"] or "",
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)},
                    }
                    for i, tc in enumerate(reply["tool_calls"])
                ],
            })

            # 逐个执行工具调用
            for i, tc in enumerate(reply["tool_calls"]):
                if interrupt.is_set():
                    kill_current_proc()
                    emit({"type": "interrupted", "text": "已中断：用户点了停止。"})
                    return "（已被用户中断）"

                name = tc["name"]
                args = tc["arguments"] or {}
                func, source = self._route(name)
                emit({"type": "action", "tool": name, "args": args, "source": source})

                sig = name + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False)
                rec = seen.get(sig)
                if rec and rec["failed"] and rec["mutations"] == mutations:
                    obs_text, is_error, image = (
                        "已拦截重复调用：同一条命令刚刚失败过，且期间工作区没有任何改动，"
                        "再执行结果不会变。请换方法（改参数、换工具）或直接说明卡在哪里。"
                    ), True, None
                    emit({"type": "system", "text": f"拦截重复调用 {name}（源码：{source}）"})
                elif func is None:
                    obs_text, is_error, image = f"未知工具：{name}", True, None
                else:
                    try:
                        if source.startswith("mcp:"):
                            text, is_error = func.call_tool(name, args)
                            obs_text, image = text, None
                        else:
                            result = func(**args) if args else func()
                            obs_text, is_error, image = self._format_obs(result)
                    except Exception as e:
                        obs_text, is_error, image = self._format_obs(e)

                # bash 用退出码表达失败，不是异常。非 0 也算失败：
                # UI 标红（用户要看见红），并计入空转统计（否则模型会把同一命令重跑到底）。
                if not is_error and name == "bash" and isinstance(obs_text, str):
                    m_code = re.match(r"exit_code=(-?\d+)", obs_text)
                    if m_code and int(m_code.group(1)) != 0:
                        is_error = True

                # 成功的写操作会改变工作区，让“再跑一次”重新变得有意义
                if not is_error and name in ("write", "edit"):
                    mutations += 1
                if func is not None:  # 被拦截的调用不覆盖原始失败记录
                    seen[sig] = {"failed": is_error, "mutations": mutations}

                emit({"type": "observation", "tool": name, "content": obs_text or "", "is_error": is_error})

                # 把观察回灌对话（图片转成 image_url 内容块）
                tool_msg = {"role": "tool", "name": name, "tool_call_id": f"call_{i}"}
                if image:
                    tool_msg["content"] = [
                        {"type": "text", "text": f"[图片 {image['path']}]"},
                        {"type": "image_url", "image_url": {"url": f"data:{image['mime']};base64,{image['b64']}"}},
                    ]
                else:
                    tool_msg["content"] = obs_text or ""
                messages.append(tool_msg)

                # 连续失败要么是环境缺东西（该说明），要么是模型在硬来（该刹车）
                consec_fail = consec_fail + 1 if is_error else 0
                if consec_fail >= 3:
                    if consec_fail >= 6:
                        emit({"type": "error", "text": "连续 6 次工具调用失败，已停止。请检查环境后重试。"})
                        return "连续多次工具失败，已停止。"
                    messages.append({
                        "role": "user",
                        "content": (
                            "【系统提示】已连续 3 次以上工具调用失败。停止继续试错，"
                            "直接给出结论：已经完成了什么、卡在哪里、建议用户怎么处理。"
                        ),
                    })
                    emit({"type": "system", "text": f"连续 {consec_fail} 次失败，已要求模型收敛并说明卡点。"})

        emit({"type": "max_steps", "text": "达到步数上限，转人工。"})
        return "达到步数上限，转人工。"
