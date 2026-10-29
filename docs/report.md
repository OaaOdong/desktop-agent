# 桌面 AI 编程智能体 · 提交报告

**项目名**：desktop-agent（"我的 Cursor"）
**仓库**：https://github.com/OaaOdong/desktop-agent
**交付形态**：Windows 桌面应用（pywebview 原生窗口）+ 自动构建的 Release 安装包

---

## 一、做了什么

一个可运行的桌面 AI 编程智能体：用户在窗口里用自然语言下达任务，智能体通过四个工具（`read` / `write` / `edit` / `bash`）自主读写本地工作区文件、执行命令，并把每一步的工具调用可见地展示在界面上。

技术栈刻意保持薄：

| 层 | 选型 | 理由 |
|---|---|---|
| 桌面窗口 | pywebview 5.2（WebView2） | 原生窗口、无浏览器地址栏，满足"桌面应用"而非"localhost 网页"的判定 |
| 后端 | FastAPI + WebSocket | 事件流式推送，工具调用逐步可见 |
| 大模型 | OpenAI 兼容 `/chat/completions`（标准库 urllib 实现） | 不绑定厂商，DeepSeek / 通义 / OpenAI / 本地 Ollama 均可 |
| 工具 | 手写，严格对齐规格 | 不引第三方 agent 框架，每一步行为可控、可解释 |
| MCP | 手写 JSON-RPC over stdio 客户端 | 看清协议本质，只依赖标准库 |

前端是单页原生 HTML/CSS/JS，无构建步骤、无前端框架——降低演示时的环境风险。

---

## 二、需求对照

### 2.1 桌面应用形态

`run_desktop.py` 先在本机起 FastAPI 服务，再用 `webview.create_window()` 打开一个 1280×820 的原生窗口，加载 `http://127.0.0.1:8765/`。

**关键点**：窗口没有地址栏、没有浏览器标签页、没有前进后退按钮。用户看到的是一个独立应用窗口，不是"用浏览器打开的网页"。这是"桌面应用"与"localhost 网页"的分界线。

无 pywebview 环境时自动降级为浏览器打开，并打印提示——降级形态带地址栏，**不算交付形态**，仅用于本地开发。

### 2.2 四个工具（严格按课件规格）

| 工具 | 规格要求 | 实现 |
|---|---|---|
| `read` | 带行号、分页、支持图片多模态 | 返回 `行号│内容`；`offset`/`limit` 分页并提示"共 N 行，已读 X-Y"；图片走 base64 转 `image_url` 内容块回灌给模型 |
| `write` | 原子写、自动建父目录、报告行数 | 写临时文件再 `os.replace` 原子替换（避免写一半断电留半截文件）；`mkdir(parents=True)`；返回"已写入 N 行" |
| `edit` | 精确替换、**唯一性检查**、不猜 | `old_string` 出现 0 次 → 报错并提示用 `read` 确认；出现 ≥2 次 → 报错并告知出现次数，**绝不替用户猜改哪一处** |
| `bash` | 返回 exit_code + stdout + stderr、**强制 timeout** | `exit_code` 原样返回（非 0 也正常返回，不静默失败）；默认 30s 超时，超时杀进程并返回 `exit_code=124`；正在运行的子进程可被"中断"按钮杀掉 |

三者之外的安全边界：所有路径经 `_resolve_in_workspace()` 校验，`../` 越界或绝对路径指向工作区外一律拒绝。

### 2.3 MCP 接入

- 客户端：`agent/mcp_client.py`，手写 JSON-RPC over stdio，实现 `initialize` → `tools/list` → `tools/call` 三段。协议日志全部写 stderr，不污染 stdout 的 JSON 通道。
- 配置：`mcp.json`，格式与主流 MCP 客户端一致（`mcpServers` → `command` / `args`），加一个 server 只需改这个文件，不动代码。
- 示例 server：`example_server/weather_server.py`，手写、零依赖、约 100 行，用来演示协议本身而非套用 SDK。

**验证证据**：运行日志里出现 `[MCP] 已连接 server: weather`，且 `build_agent()` 返回值中 MCP 客户端列表为 `['weather']`，模型可调用的工具集里包含 `get_weather`。

### 2.4 三栏界面

| 栏 | 内容 |
|---|---|
| 左 | 资源管理器：工作区目录树，点文件在下方预览（受工作区边界约束） |
| 中 | 对话 + 工具调用卡片：`🔧 read` / `🔧 edit` / `🔧 bash`，每次调用折叠展示参数与结果 |
| 右 | 终端：`bash` 的原始 stdout/stderr，带 `exit_code` |

三个可见性要求逐条落实：

- **工具调用可见**：每次调用先推 `action` 事件（工具名 + 参数 + 来源是内置还是 MCP），再推 `observation` 事件。
- **失败标红**：`is_error` 为真的观测卡片整块变红；`bash` 的 `exit_code != 0` 同样判定为失败并标红。
- **可中断**：中断按钮先置中断标志，再杀掉正在运行的 `bash` 子进程（Windows 用 `taskkill /F /T` 连子进程树一起杀），避免 `pip install` 这类命令把界面卡死。

### 2.5 护栏

1. **步数上限**：默认 20 步（`MAX_STEPS`），到顶输出"达到步数上限，转人工"。
2. **重复调用拦截**：同一工具 + 同一参数连续调用超过 3 次且期间没有产生写操作，直接终止并回报卡点。
3. **连续失败熔断**：连续 3 次工具失败即停止，不再让模型空转烧 token。
4. **路径白名单**：所有文件操作限制在工作区内。
5. **命令超时**：`bash` 强制 timeout，超时杀进程。

---

## 三、一次真实运行（摘自 trace）

完整记录见 `docs/trace.md`，此处摘关键片段。任务：

> 跑一下 workspace 的测试，把失败的修好

智能体的实际行为序列：

1. `bash` → `python -m pytest -q`，返回 `exit_code=1`，`FAILED workspace/test_stats.py::test_mean_empty_raises`
2. `read` → `stats.py`，看到第 9 行 `return 0.0`
3. `edit` → `return 0.0` 替换为 `raise ValueError("mean() arg is an empty sequence")`
4. `bash` → `python -m pytest -q`，返回 `exit_code=0`，`3 passed in 0.04s`
5. 输出完成总结

**值得注意的两点**：

- 它**先复现再修**（第 1 步跑测试拿到失败），而不是看到代码就猜着改。这是提示词里"测试是提示词的一部分"那条在起作用。
- 修改后**自己回头验证**（第 4 步），不是改完就宣布完成。

---

## 四、踩过的坑（真实复盘）

这一节不是凑数，每条都是实际跑出来的故障。

### 4.1 `edit` 的唯一性检查在真实演示里救了一次

第一次演示时，智能体试图把 `return 0` 替换掉，但该字符串在文件里出现了两次（`mean()` 和 `variance()` 各一处）。工具直接报错"出现 2 次，请提供更长上下文"，模型随后补足上下文重新提交，改对了位置。

**如果当时工具选择"猜第一个"**，它会改错函数，而测试恰好可能仍然通过（因为两个函数逻辑相似）——这种静默错误在代码智能体里是最危险的。唯一性检查的价值就在这。

### 4.2 空转到步数上限

早期版本出现过：模型修完代码后反复跑 `pytest`，每次都拿到同样的结果，却不肯收尾，直到 20 步耗尽，界面显示"达到步数上限，转人工"。

根因有三层：`pytest` 未安装导致命令持续报错；`bash` 的失败信号（`exit_code != 0`）没有在观测文本里被足够醒目地呈现；以及没有任何防空转机制。

修法对应三条：安装 pytest；观测文本把 `exit_code` 顶到第一行；加重复调用拦截与连续失败熔断（见 2.5）。

### 4.3 打包后的路径陷阱

`config.py` 原本用 `Path(__file__).parent.parent` 定位项目根。源码运行没问题，但 PyInstaller 打包后 `__file__` 指向临时解压目录，后果是：`.env` 读不到（用户填了 Key 却报未配置）、`workspace/` 写到临时目录（关窗口即丢）。

修法是拆成两个概念：

- `APP_DIR`：可写数据目录，打包后是 exe 所在目录 —— `.env`、`workspace/`、`mcp.json` 从这里找；
- `BUNDLE_DIR`：只读资源目录，打包后是 `sys._MEIPASS` —— `ui/` 从这里找。

这个坑不修，Release 安装包就是"能装不能跑"。

### 4.4 安装包的机器可能没有 Python

MCP server 原本由 `command: "python"` 拉起。装到没有 Python 的机器上，MCP 必然起不来。

解法：CI 里把 `weather_server.py` 也打成独立的 `weather_server.exe`，安装目录附带一份指向该 exe 的 `mcp.json`。这样安装包不依赖系统 Python。

---

## 五、测试与验证

| 测试 | 内容 | 结果 |
|---|---|---|
| `tests/self_test.py` | 四工具规格（含原子写、唯一性检查、超时、路径越界）+ MCP 客户端 + Agent 循环端到端，用 mock LLM 替代真实模型 | 全过 |
| `tests/verify_guard.py` | 重复调用拦截、连续失败熔断专项 | 全过 |
| `tests/verify_server.py` | 后端静态页 + `/api/tree` 冒烟 | 通过 |
| `tests/generate_trace.py` | 生成 `docs/trace.md` 的真实运行记录（含一次 `edit` 不唯一失败与恢复） | 通过 |
| CI（GitHub Actions） | 每次 push 自动跑 self_test，通过后才打包 | 见 Actions 页 |

`self_test.py` 与 `generate_trace.py` 都在**临时副本**上运行，不会污染交付用的 `workspace/`——这一点是刻意设计的：演示需要 `stats.py` 保留 bug 作为"靶子"，测试不能把它改掉。

---

## 六、局限与后续

诚实说明当前边界：

1. **单轮任务，无长期记忆**：每次对话从空白消息列表开始，不跨会话记住上下文。工程上可通过落盘 message history 解决，不在本次范围。
2. **无 diff 预览与人工确认**：`write` / `edit` 直接落盘。生产级智能体应在写操作前展示 diff 并等待确认——这是我认为最该补的一项。
3. **`bash` 无沙箱隔离**：命令以当前用户权限执行，只靠工作区路径约束文件类工具，`bash` 本身可以访问工作区外。真要防注入需要容器级隔离。
4. **单智能体，无并行子任务**：复杂任务无法拆给多个 agent 并行。

---

## 七、如果只能再加一个工具

**加 `glob`（按 pattern 找文件路径）**，而不是 `grep` 或 `tree`。

理由是本项目的实际卡点是"定位"。给智能体的任务往往是一句话（"修复测试失败"），它需要先从一句话收敛到具体文件，再 `read`、再 `edit`。`read` 只能按已知路径读，`bash` 虽然能 `dir /s`，但输出无结构、易淹没上下文，还多一层 shell 依赖与超时风险。

`glob` 用一个 `**/*.py` 就能把"有哪些文件"压成一份干净清单，且不执行任何外部命令。有了它，`read` → `edit` → `bash` 这条主链的入口才真正闭合。

`grep` 排在第二：它解决"文件内定位"，但前提是已经知道去哪个目录找。先有 `glob` 缩小范围，`grep` 才高效。

---

## 八、评分项自查

| 要求 | 状态 | 证据 |
|---|---|---|
| 桌面应用（非 localhost 网页） | ✅ | `run_desktop.py` + pywebview 原生窗口，无地址栏 |
| 接入大模型 | ✅ | `agent/llm.py`，OpenAI 兼容接口，实测连通（DeepSeek） |
| `read`（行号/分页/图片） | ✅ | `agent/tools.py` |
| `write`（原子写/建目录/行数） | ✅ | 同上 |
| `edit`（唯一性检查） | ✅ | 同上，并有真实失败-恢复记录 |
| `bash`（exit_code/超时） | ✅ | 同上，超时返回 124 |
| MCP（stdio，至少一个 server） | ✅ | `mcp_client.py` + `weather_server.py`，日志确认 `已连接 server: weather` |
| 三栏界面 | ✅ | `ui/index.html` |
| 工具调用可见 | ✅ | `action` / `observation` 事件流 |
| 失败标红 | ✅ | `is_error` 与 `exit_code != 0` 双重判定 |
| 可中断 | ✅ | 中断标志 + 杀子进程树 |
| public 仓库 | ✅ | https://github.com/OaaOdong/desktop-agent |
| Release 安装包 | ✅ | GitHub Actions 自动构建，见 Releases 页 |
| trace | ✅ | `docs/trace.md`（真实运行记录） |
| report | ✅ | 本文件 |

---

## 九、运行方式

源码运行：

```bash
pip install -r requirements.txt
pip install pywebview==5.2
copy .env.example .env     # 填入 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
python run_desktop.py
```

安装包运行：从 Releases 下载 `DesktopAgent-Setup.exe` 安装，首次启动前把安装目录下的 `.env.example` 复制为 `.env` 并填入 Key。

演示前的复位：双击 `reset_demo.bat`，把 `workspace/stats.py` 还原成带 bug 的初始状态——演示成功一次 bug 就被修掉了，复位脚本解决"第二次演示没靶子"的问题。
