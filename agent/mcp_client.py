"""MCP stdio 客户端（JSON-RPC over stdio，纯标准库）。

一次工具调用的完整链路（P29）：
  client→server tools/list  →  server 返回每个工具的 JSON Schema
  host 把这段 JSON 注入模型上下文  →  模型输出 tool_call
  server→client result  →  执行、返回，再回灌对话

关键点（P29/P34）：
- stdio 传输下，server 的 stdout 是协议通道，任何多余的 print 都会污染协议；
  日志必须写 stderr。本客户端与服务端都遵守这一点。
- MCP 解决的只是“怎么连”，连上之后更贵、更危险、更难查——所以按需挂载、限权限、日志走 stderr。
"""
import json
import os
import subprocess
from pathlib import Path


def _stdio_env() -> dict:
    """给 MCP 子进程一个确定的 UTF-8 环境。

    在 en-US 的 Windows（控制台 cp1252）下，子进程若按 cp1252 编码 stdout，
    写中文（如“杭州 22℃”）会抛 UnicodeEncodeError 直接崩掉，父进程读到
    “连接关闭”。强制 PYTHONUTF8=1 / PYTHONIOENCODING=utf-8，让 stdio 通道
    稳定走 UTF-8，不依赖宿主机 locale。
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class MCPClient:
    def __init__(self, name: str, command: str, args: list[str]):
        self.name = name
        self.proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # 行缓冲，保证协议消息逐行 flush
            env=_stdio_env(),
        )
        self._id = 0
        self._read_stderr()  # 吞掉服务端启动期的 stderr（不阻塞）

    def _read_stderr(self):
        # 非阻塞地读一点 stderr，避免管道写满卡死（仅用于调试可见性）
        import select
        try:
            if self.proc.stderr and select.select([self.proc.stderr], [], [], 0)[0]:
                self.proc.stderr.read(4096)
        except Exception:
            pass

    def _request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"MCP server '{self.name}' 已关闭连接")
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue  # 跳过非 JSON 行（理论上不该有）
            if resp.get("id") == self._id:
                if "error" in resp:
                    raise RuntimeError(f"MCP error: {resp['error']}")
                return resp

    def initialize(self) -> dict:
        return self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "desktop-agent", "version": "1.0.0"},
            },
        )

    def list_tools(self) -> list[dict]:
        resp = self._request("tools/list")
        tools = resp.get("result", {}).get("tools", [])
        # 转成 OpenAI 工具 schema 形状，方便直接塞进模型上下文
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                },
                "_mcp_server": self.name,  # 标记来源，loop 路由用
            }
            for t in tools
        ]

    def call_tool(self, name: str, arguments: dict) -> tuple[str, bool]:
        resp = self._request("tools/call", {"name": name, "arguments": arguments})
        result = resp.get("result", {})
        content = result.get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        is_error = bool(result.get("isError", False))
        return text, is_error

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


def load_mcp_servers(config_path: Path) -> list[MCPClient]:
    """读取 mcp.json，启动所有 server；单个失败不影响其余。"""
    import sys
    clients: list[MCPClient] = []
    if not config_path.exists():
        return clients
    try:
        # utf-8-sig：兼容带 BOM 的 mcp.json（记事本 / 部分 CI 脚本写出来的会带 BOM）
        cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"[MCP] 读取配置失败：{e}", file=sys.stderr)
        return clients

    for name, spec in cfg.get("mcpServers", {}).items():
        command = spec.get("command", "python")
        # 用当前解释器跑 server，避免 PATH 里的 python 与装了依赖的解释器不是同一个
        if command in ("python", "python3"):
            command = sys.executable
        # 相对路径的 command（打包版指向 example_server/weather_server.exe）同样
        # 相对 mcp.json 所在目录解析，否则会跟着启动时的 cwd 乱跑
        elif ("/" in command or "\\" in command) and not Path(command).is_absolute():
            cand = (config_path.parent / command).resolve()
            if cand.exists():
                command = str(cand)
        args = [str(a) for a in spec.get("args", [])]
        # 把相对路径解析到项目根，避免从不同 cwd 启动时找不到脚本
        resolved = []
        for a in args:
            looks_like_path = a.endswith(".py") or "/" in a or "\\" in a
            if looks_like_path and not Path(a).is_absolute():
                resolved.append(str((config_path.parent / a).resolve()))
            else:
                resolved.append(a)
        args = resolved
        try:
            client = MCPClient(name, command, args)
            client.initialize()
            clients.append(client)
            print(f"[MCP] 已连接 server: {name}", file=sys.stderr)
        except Exception as e:
            print(f"[MCP] 启动 server '{name}' 失败，已跳过：{e}", file=sys.stderr)
    return clients
