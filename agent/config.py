"""配置与 .env 加载（纯标准库，无第三方依赖）。

路径分两个概念，这是 PyInstaller 打包后仍能正确工作的关键：

- APP_DIR    : 可写数据目录。源码运行时 = 项目根；打包后 = exe 所在目录。
                .env、workspace/、mcp.json 都从这里找（用户可改、可持久化）。
- BUNDLE_DIR : 只读资源目录。源码运行时 = APP_DIR；打包后 = PyInstaller 的
                临时解压目录（sys._MEIPASS）。ui/ 这类只读资源从这里找。

如果两者混用，打包版会出现「.env 读不到」「workspace 写进临时目录、
关窗口就丢」这类问题。
"""
import os
import sys
from pathlib import Path


def _app_dir() -> Path:
    """可写数据目录：打包后是 exe 所在目录，源码运行时是项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = _app_dir()


def _bundle_dir() -> Path:
    """只读资源目录：打包后是 sys._MEIPASS，源码运行时同 APP_DIR。"""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass).resolve() if meipass else APP_DIR


BUNDLE_DIR = _bundle_dir()

# 兼容旧名（源码模式下 ROOT == APP_DIR，行为与改动前一致）
ROOT = APP_DIR

# 工作区：智能体只允许读写这个目录
WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", APP_DIR / "workspace")).resolve()


def load_env(path: Path = APP_DIR / ".env") -> None:
    """极简 .env 解析：只 setdefault，绝不覆盖已存在的环境变量。

    用 utf-8-sig 读：Windows 记事本保存的 UTF-8 会带 BOM，用 utf-8 读会让第一个
    键名前面多出 \\ufeff，key 就带脏字符了。
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
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

# MCP 配置文件（放可写目录，用户可自行增删 server）
MCP_CONFIG = APP_DIR / "mcp.json"
