"""配置与 .env 加载（纯标准库，无第三方依赖）。"""
import os
from pathlib import Path

# 项目根目录（desktop-agent/）
ROOT = Path(__file__).resolve().parent.parent

# 工作区：智能体只允许读写这个目录
WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", ROOT / "workspace")).resolve()


def load_env(path: Path = ROOT / ".env") -> None:
    """极简 .env 解析：只 setdefault，绝不覆盖已存在的环境变量。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


load_env()

LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "20"))

# MCP 配置文件
MCP_CONFIG = ROOT / "mcp.json"
