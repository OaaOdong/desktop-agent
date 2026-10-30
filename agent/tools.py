"""四个核心工具：read / write / edit / bash。

语义严格对齐课程大作业规格（P36）：
- read   : 文本按行带行号返回；图片返回多模态内容块(base64)；超大文件分页。
- write  : 自动建父目录；临时文件 + rename 做原子写；覆盖时告知原/新行数。
- edit   : 精确字符串替换 + 唯一性检查（出现 2 次就报错，绝不猜）。
- bash   : 万能工具，返回 stdout+stderr+exit_code（非 0 也正常返回）；必须有 timeout。

所有文件操作都被 WORKSPACE 路径白名单拦住：模型可以“想”读任何文件，
但 resolve() + 前缀校验把它挡在目录外——这一行比任何提示词都可靠。
"""
import base64
import os
import re
import subprocess
from pathlib import Path

from .config import WORKSPACE

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

# 输出上限：超过就只留尾部 N 行（用代码截断，替代模型爱用的 | tail）
MAX_OUTPUT_LINES = 200

# Windows cmd 里根本不存在的 Unix 工具。模型（尤其照着 Unix 教程训练出来的）
# 很容易写 `... | tail -20`，在 cmd 里会直接报 "不是内部或外部命令"，
# 白白烧掉一个 step。这里主动拦下并给出可执行的替代方案。
_UNIX_ONLY = {
    "tail", "head", "grep", "egrep", "fgrep", "sed", "awk", "wc", "sort",
    "uniq", "find", "ls", "cat", "rm", "cp", "mv", "touch", "chmod",
    "which", "xargs", "tr", "tee", "du", "df", "ps", "kill",
}

# 命中 `| tail -20` / `| head -n 20` 这类纯截断管道时，直接去掉即可
_TRUNC_PIPE = re.compile(r"\|\s*(?:tail|head)\s+(?:-\w+\s+)*(?:-\d+|\d+)\s*$", re.I)

# 给中断逻辑用：记录当前正在跑的子进程，便于中断时杀掉
_current_proc = None


def _within(target: Path, root: Path) -> bool:
    """target 是否落在 root 之内。

    用 normcase 归一（Windows 路径大小写不敏感），用 commonpath 判断包含关系：
    字符串前缀法在工作区是盘符根（C:\\）时会漏判，跨盘符时应直接判否。
    """
    t, r = os.path.normcase(str(target)), os.path.normcase(str(root))
    try:
        return os.path.commonpath([t, r]) == r
    except ValueError:  # 不在同一个盘符
        return False


def _resolve(rel_path: str) -> Path:
    """把相对路径解析到 WORKSPACE 内，并做越界校验。

    两边都必须先 resolve 再比较。WORKSPACE 可能是未归一化的写法——
    含 8.3 短名（CI runner 的 TEMP 是 C:\\Users\\RUNNER~1\\...）或含 `..`——
    而 Path.resolve() 会把它展开成长名/规范路径。只 resolve 一边，
    前缀校验就会把合法路径判成越界（本地 TEMP 没有短名，所以只有 CI 复现）。
    """
    if not rel_path:
        raise ValueError("路径不能为空")
    root = Path(WORKSPACE).resolve()
    target = (root / rel_path).resolve()
    if target == root:
        return target
    if not _within(target, root):
        raise ValueError(f"路径越界：{rel_path} 不在工作区 {WORKSPACE} 内")
    return target


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------
def read_file(path: str, offset: int = 0, limit: int | None = None) -> str | dict:
    """读工作区内文件。
    文本：按行带行号；超大文件分页并提示剩余行数。
    图片：返回多模态内容块（base64），供有视觉能力的模型使用。
    """
    target = _resolve(path)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在：{path}（可用目录见工作区根）")
    if target.is_dir():
        children = sorted(p.name for p in target.iterdir())
        return f"{path} 是目录，内容：{children}"

    suffix = target.suffix.lower()
    if suffix in IMAGE_EXTS:
        b64 = base64.b64encode(target.read_bytes()).decode("ascii")
        mime = "image/" + ("jpeg" if suffix in (".jpg",) else suffix[1:])
        # 返回特殊结构，由 loop 转成 image_url 内容块
        return {"__image__": True, "mime": mime, "b64": b64, "path": path}

    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = max(0, int(offset))
    if limit is None:
        end = len(lines)
    else:
        end = min(len(lines), start + int(limit))
    out = []
    for i in range(start, end):
        out.append(f"{i + 1:>5}\t{lines[i]}")
    remaining = len(lines) - end
    if remaining > 0:
        out.append(f"... 还有 {remaining} 行（用 offset/limit 分页读取）")
    if not out:
        out.append("(空文件)")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------
def write_file(path: str, content: str) -> str:
    """创建或整体覆盖文件。原子写（临时文件 + rename），自动建父目录。"""
    target = _resolve(path)
    old_lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)  # 原子替换
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    new_lines = content.splitlines()
    if old_lines is None:
        return f"已创建 {path}（{len(new_lines)} 行）"
    return f"已覆盖 {path}（原 {len(old_lines)} 行 → 现 {len(new_lines)} 行）"


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """精确字符串替换。要求 old_string 在文件中唯一出现，否则报错（不猜）。"""
    target = _resolve(path)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    text = target.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        raise ValueError(f"未找到 old_string：{old_string!r}（请检查空格/换行是否完全一致）")
    if count > 1:
        raise ValueError(
            f"old_string 出现 {count} 次，不唯一，拒绝猜测替换。"
            f"请提供更多上下文让它唯一，或改用更精确的片段。"
        )
    new_text = text.replace(old_string, new_string, 1)
    target.write_text(new_text, encoding="utf-8")
    return f"已编辑 {path}：1 处替换成功"


# ---------------------------------------------------------------------------
# bash
# ---------------------------------------------------------------------------
def _decode(raw: bytes) -> str:
    """cmd 的输出编码不稳定：Python 自己打的是 UTF-8，老程序打的是 GBK。
    逐个试，别让一行乱码毁掉整段观测。"""
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _truncate(text: str, limit: int = MAX_OUTPUT_LINES) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    kept = "\n".join(lines[-limit:])
    return f"... 输出共 {len(lines)} 行，已截断，仅保留最后 {limit} 行 ...\n{kept}"


def _prepare_command(command: str) -> tuple[str, str]:
    """把模型写出的 Unix 风格命令改写成 cmd 能跑的样子。
    能安全改写的（纯截断管道）就改写；改不了的直接拒绝，省得烧 step。
    返回 (新命令, 改写说明)
    """
    cmd = command.strip()
    note = ""
    m = _TRUNC_PIPE.search(cmd)
    if m:
        cmd = cmd[: m.start()].rstrip()
        note = f"（已自动去掉 `{m.group(0).strip()}`：cmd 没有 tail/head，输出截断由工具负责）"

    # 逐段检查管道/串接命令的首个词
    for seg in re.split(r"\|\||&&|[|&;]", cmd):
        parts = seg.strip().split()
        if not parts:
            continue
        head = parts[0].lower().strip('"').strip("'")
        if head in _UNIX_ONLY:
            raise ValueError(
                f"命令里的 `{parts[0]}` 在 Windows cmd 中不存在，未执行。"
                f"请改用 cmd 等价命令（dir / type / findstr / del），"
                f"或者直接用 python -c \"...\" 完成，也可以直接去掉这段管道。"
            )
    return cmd, note


def bash(command: str, timeout: int = 60) -> str:
    """执行 shell 命令（Windows 下即 cmd /c），返回 exit_code + stdout + stderr。
    非 0 退出码也照常返回，绝不静默失败——模型需要看见错误才能自我纠正。
    timeout 是硬护栏：没有它，一条 pip install 就能把整个 agent 挂死。
    """
    global _current_proc
    cmd, note = _prepare_command(command)
    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=str(Path(WORKSPACE).resolve()),  # 与文件工具走同一个规范路径
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _current_proc = proc
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        _current_proc = None
        return (
            f"exit_code=124（超时 {timeout}s，进程已被杀）{note}\n"
            f"--- stdout ---\n{_truncate(_decode(out))}\n"
            f"--- stderr ---\n{_truncate(_decode(err))}"
        )
    finally:
        _current_proc = None
    code = proc.returncode
    return (
        f"exit_code={code}{note}\n"
        f"--- stdout ---\n{_truncate(_decode(out))}\n"
        f"--- stderr ---\n{_truncate(_decode(err))}"
    )


def kill_current_proc() -> bool:
    """中断时杀掉正在跑的 bash 子进程。返回是否真的杀到了。"""
    global _current_proc
    if _current_proc is not None and _current_proc.poll() is None:
        _current_proc.kill()
        _current_proc = None
        return True
    return False


# ---------------------------------------------------------------------------
# 工具注册表：函数 + 给模型的“说明书”（description 就是提示词）
# ---------------------------------------------------------------------------
TOOLS = {
    "read": read_file,
    "write": write_file,
    "edit": edit_file,
    "bash": bash,
}

# 工具来源标记：内置 vs MCP（loop 路由与 UI 展示都靠它区分）
tool_source: dict[str, str] = {name: "builtin" for name in TOOLS}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": (
                "读取工作区内的文本文件，按行返回并带行号，便于定位。"
                "超大文件请用 offset/limit 分页，工具会告诉你还有多少行未读。"
                "图片文件会作为多模态内容块返回。"
                "需要查看文件内容、确认代码现状时使用；不要猜测文件内容，先读。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "工作区内的文件路径，如 stats.py"},
                    "offset": {"type": "integer", "description": "起始行（从 0 开始），默认 0"},
                    "limit": {"type": "integer", "description": "读取行数，默认读到末尾"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": (
                "创建新文件或整体覆盖已有文件。会自动创建父目录，并用临时文件+rename 做原子写。"
                "覆盖已有文件时会告知原行数与新行数。"
                "仅在需要新建文件或整体重写时使用；局部改动请优先用 edit。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目标文件路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": (
                "对文件做精确字符串替换：把 old_string 整体替换为 new_string。"
                "要求 old_string 在文件中唯一出现；若出现多次会报错，绝不猜测。"
                "这是做局部修改的首选工具（对应 Claude Code 的核心 edit 能力）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目标文件路径"},
                    "old_string": {"type": "string", "description": "要被替换的唯一片段（含缩进/换行）"},
                    "new_string": {"type": "string", "description": "替换后的内容"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "在 Windows cmd 里执行命令（等价 cmd /c），返回 exit_code、stdout、stderr，"
                "非 0 退出码也照常返回，不会静默失败。用于搜索、Git、安装依赖、运行测试。"
                "注意：cmd 没有 tail/head/grep/sed/awk/ls/cat，管道只能用 cmd 自带命令；"
                "输出会自动截断尾部，不需要也不要用 tail 截取。"
                "务必设置 timeout（秒），避免命令卡死拖垮整个 agent。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 cmd 命令，如 python test_stats.py"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认 60"},
                },
                "required": ["command"],
            },
        },
    },
]
