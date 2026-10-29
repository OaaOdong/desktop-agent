"""FastAPI + WebSocket 后端。

职责（P38 目录结构：server/ FastAPI + WebSocket）：
- 提供 UI 静态文件（ui/），桌面窗口 pywebview 直接加载本服务地址。
- /ws：跑智能体，把每一步（action / observation / final）流式推给前端。
- /api/tree、/api/file：给左侧资源管理器用，同样受 WORKSPACE 边界约束。

后端先跑通、再做界面——这是两周唯一做得完的顺序（P35）。
"""
import asyncio
import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from agent.config import ROOT, WORKSPACE, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, MAX_STEPS, MCP_CONFIG
from agent.llm import OpenAICompatibleLLM
from agent.loop import Agent
from agent.mcp_client import load_mcp_servers
from agent.tools import read_file

UI_DIR = ROOT / "ui"
app = FastAPI(title="desktop-agent")


def build_agent():
    if not LLM_API_KEY:
        raise RuntimeError("未配置 OPENAI_API_KEY：请复制 .env.example 为 .env 并填入 Key")
    llm = OpenAICompatibleLLM(LLM_API_KEY, LLM_BASE_URL, LLM_MODEL)
    mcp = load_mcp_servers(MCP_CONFIG)
    return Agent(llm, mcp_clients=mcp, max_steps=MAX_STEPS), mcp


@app.get("/api/tree")
def api_tree():
    """返回工作区目录树（受 WORKSPACE 边界约束）。"""
    nodes = []

    def walk(folder: Path):
        entries = []
        for p in sorted(folder.iterdir()):
            if p.name.startswith(".") or p.name == "__pycache__":
                continue
            if p.is_dir():
                entries.append({"name": p.name, "path": str(p.relative_to(WORKSPACE)),
                                "type": "dir", "children": walk(p)})
            else:
                entries.append({"name": p.name, "path": str(p.relative_to(WORKSPACE)),
                                "type": "file"})
        return entries

    if WORKSPACE.exists():
        nodes = walk(WORKSPACE)
    return {"root": str(WORKSPACE), "children": nodes}


@app.get("/api/file")
def api_file(path: str, offset: int = 0, limit: int = 400):
    """读取单个文件内容（带行号），供前端预览；越界会被拒。"""
    try:
        content = read_file(path, offset=offset, limit=limit)
        if isinstance(content, dict) and content.get("__image__"):
            return {"type": "image", "path": path}
        return {"type": "text", "content": content}
    except Exception as e:
        return {"type": "error", "content": str(e)}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        init = await websocket.receive_json()
    except Exception:
        await websocket.close()
        return
    if init.get("type") != "run":
        await websocket.close()
        return

    task = init.get("task", "")
    try:
        agent, mcp = build_agent()
    except Exception as e:
        await websocket.send_json({"type": "error", "text": str(e)})
        await websocket.close()
        return

    loop_q: queue.Queue = queue.Queue()
    interrupt = threading.Event()

    def emit(ev):
        loop_q.put(ev)

    thread = threading.Thread(target=agent.run, args=(task, emit, interrupt), daemon=True)
    thread.start()

    async def sender():
        while True:
            try:
                ev = loop_q.get_nowait()
            except queue.Empty:
                if not thread.is_alive():
                    try:
                        await websocket.send_json({"type": "done"})
                    except Exception:
                        pass
                    return
                await asyncio.sleep(0.05)
                continue
            try:
                await websocket.send_json(ev)
            except Exception:
                return

    async def receiver():
        while True:
            try:
                msg = await websocket.receive_json()
            except (WebSocketDisconnect, Exception):
                return
            if isinstance(msg, dict) and msg.get("type") == "interrupt":
                interrupt.set()

    try:
        await asyncio.gather(sender(), receiver())
    finally:
        interrupt.set()
        for c in mcp:
            c.close()
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


# 静态文件放在最后挂载：优先匹配上面的 API 路由与 /ws，剩下的才交给 UI。
app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
