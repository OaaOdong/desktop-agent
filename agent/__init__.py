"""agent 包：智能体循环 + 四个工具 + LLM 客户端 + MCP 客户端。

设计原则（全部来自课程 PPT）：
- 模型只输出结构化意图（调哪个工具、传什么参数），真正的执行权永远在代码手里。
- 工具是写给模型看的接口：description 就是提示词，粒度往粗里做，数量要少。
- 路径白名单 + 只读边界 + 步数上限 + 超时，是可靠性的全部来源。
"""

from .config import WORKSPACE, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, MAX_STEPS
from .tools import TOOLS, TOOL_SCHEMAS, tool_source
from .llm import OpenAICompatibleLLM
from .loop import Agent

__all__ = [
    "WORKSPACE", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "MAX_STEPS",
    "TOOLS", "TOOL_SCHEMAS", "tool_source", "OpenAICompatibleLLM", "Agent",
]
