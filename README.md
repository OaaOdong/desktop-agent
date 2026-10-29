# 我的 Cursor · 桌面 AI 编程智能体

一个能**双击打开**的桌面 AI 编程智能体（自己的 Cursor）：接大模型，只有四个工具
（`read` / `write` / `edit` / `bash`），能接 MCP，三栏界面让工具调用**可见、失败标红、可中断**。

> 这是《Python 编程与案例实务 · 智能体专题》大作业的实现（对应 P35–P39 规格）。
> 核心设计全部来自课件：Agent = LLM + Tools + Loop；description 就是提示词；M×N → M+N。

## 目录结构

```
desktop-agent/
├── README.md          本文件（三步启动 + 截图说明）
├── .gitignore         .env / dist / __pycache__ 等
├── .env.example       仅 key 名，无值
├── pyproject.toml     依赖与版本
├── requirements.txt   便捷安装
├── mcp.json           MCP server 示例配置
├── run_desktop.py     桌面窗口启动器（pywebview）
├── start.bat          Windows 一键启动（装依赖 + 建 .env + 开窗口）
├── reset_demo.bat     一键还原演示现场（把 stats.py 的 bug 改回去 + 清缓存）
├── reset_demo.py      上面那个 .bat 实际调用的脚本
├── agent/             智能体循环 + 四个工具 + LLM + MCP 客户端
│   ├── config.py
│   ├── llm.py         OpenAI 兼容客户端（纯标准库）
│   ├── tools.py       read / write / edit / bash
│   ├── mcp_client.py  MCP stdio 客户端
│   └── loop.py        ReAct 循环 + 事件流 + 中断 + 护栏
├── server/            FastAPI + WebSocket 后端
│   └── app.py
├── ui/                三栏前端（index.html / app.js）
├── example_server/    手写示例 MCP server（get_weather）
├── workspace/         智能体工作区（stats.py 故意留了 bug 供演示）
├── docs/
│   ├── trace.md       一次完整运行记录（含失败与恢复）
│   └── build.md       打包成安装包说明
└── tests/             自测与服务器冒烟测试
```

## 三步启动（换台机器也成立）

### 方式 A：双击 `start.bat`（推荐）

直接双击工程根目录的 **`start.bat`**：它会自动切到工程目录、装缺失的依赖、首次运行时
从模板生成 `.env` 并用记事本打开让你填 Key，最后启动桌面窗口。全自动，不用敲命令。

### 方式 B：手敲命令

在 **Windows 终端（cmd / PowerShell）** 里执行。注意第一步：**跨盘符必须用 `cd /d`**，
只用 `cd` 不会切换盘符，后面的 `pip` 仍会在 C 盘找文件（典型报错
`Could not open requirements file: ... No such file or directory: 'requirements.txt'`）。

```bat
:: 1) 进工程目录（/d 表示连盘符一起切，别省略）
cd /d "D:\研究生作业\Python编程与案例实务\desktop-agent"

:: 2) 装依赖
pip install -r requirements.txt
pip install pywebview==5.2        :: 桌面窗口；不装则自动降级到浏览器

:: 3) 配 Key（cmd 用 copy，不是 cp）
copy .env.example .env
::  然后编辑 .env：OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
::  默认 OpenAI 兼容接口，可填 DeepSeek / 通义 / 本地 Ollama 等

:: 4) 启动
python run_desktop.py
```

应弹出一个**原生窗口**（没有浏览器地址栏），左侧资源管理器、中间对话/工具调用、右侧终端。

> 环境要求：Python 3.10+（已在 3.14 上验证：fastapi/uvicorn/websockets/pywebview 均有现成 wheel）。

- 想先验证后端：`python run_desktop.py --no-window`，再用浏览器开 `http://127.0.0.1:8765/`。
- 想看事件流：`curl -N` 连 `/ws`（课件要求：关掉前端也能看到事件流）。

## 演示现场：跑坏了怎么还原

智能体成功一次，`stats.py` 的 bug 就没了，再演示就没得修。双击 **`reset_demo.bat`**
即可把 bug 改回去并清掉 `__pycache__` / `.pytest_cache`（等价命令 `python reset_demo.py`）。

演示用的那句话（已写入 `reset_demo.py` 的末尾，复制即可）：

```
读一下 stats.py，mean 对空列表的处理有问题，把它改对，然后运行 python test_stats.py 验证
```

> 提示：让模型跑 `python test_stats.py` 而不是 `python -m pytest -q | tail -20`。
> 后者虽然也能跑（工具会自动去掉 `| tail`），但前者输出更短、更适合投屏。

## 四个工具的语义（评分重点，P36）

| 工具 | 关键点 | 最容易做错 |
|---|---|---|
| `read` | 文本按行带行号；图片返回多模态内容块；超大文件分页 | 把图片 base64 塞进 text 字段 |
| `write` | 自动建父目录；临时文件+rename 原子写；覆盖时报告原/新行数 | 忘建目录→FileNotFoundError；写一半崩→文件损坏 |
| `edit` | 精确字符串替换 + **唯一性检查**（出现 2 次就报错，绝不猜） | 做成模糊匹配/整文件重写 |
| `bash` | 返回 exit_code+stdout+stderr（非 0 也正常返回，但会标红）；**必须有 timeout**；Windows cmd 下自动处理 Unix 管道 | 无超时→pip install 卡死；照抄 `\| tail` 导致 `不是内部或外部命令` |

## 空转护栏（真机跑出来的问题）

真实模型跑这条任务时曾经在验证环节死循环，最后撞上步数上限。三处都改在代码里，不靠提示词祈祷：

| 问题 | 修法 |
|---|---|
| 模型写 `python -m pytest -q 2>&1 \| tail -20`，cmd 里没有 `tail` | 纯截断管道自动去掉，截断改由工具在 Python 侧做；其他 Unix 命令直接拒绝并给出 cmd 等价写法 |
| 环境里没有 pytest，模型反复重试 | 预装 pytest；把 OS / shell / cwd / 解释器 / 文件清单动态拼进 system prompt，模型不再按 Linux 习惯猜 |
| 同一条失败命令被反复执行 | 同一调用签名失败过且期间文件未改动 → 拒绝执行；连续失败 3 次要求模型收敛、6 次直接停 |

> 注意护栏只拦"失败过的同一调用"：改完文件再跑同一条测试是允许的（这才是正常工作流）。
> 细节见 `docs/trace.md` 末尾的"接入真实模型时的失败"一节。

## 评分项自检（对照 P39）

- [x] 桌面窗口（pywebview，无地址栏）
- [x] 四个工具语义正确（自测见 `tests/self_test.py`）
- [x] 工具调用可见 + 失败标红 + 可中断（前端三栏 + 中断按钮）
- [x] MCP 真接上（`example_server/weather_server.py` 已连通，`mcp.json` 配置即挂载）
- [x] trace 真实（`docs/trace.md`，含一次 edit 不唯一失败与恢复）
- [x] 报告与取舍（见本 README「如果只能再加一个工具」）

### 如果只能再加一个工具，你加什么？为什么？

加 `glob`/`find`（按文件名/通配符定位文件）。理由：当前 `read` 需要先知道路径，
而真实编程任务第一步往往是"这个函数在哪个文件"。把"定位文件"也交给模型，
能显著减少它靠猜路径导致的 `read` 失败，且不会增加工具选择难度
（仍远少于 20 个工具的崩溃阈值）。这与"粒度往粗里做、数量要少"的原则一致。

## 自测

```bash
python tests/self_test.py      # 四工具 + MCP + 循环端到端（mock LLM，无需 Key）
python tests/verify_guard.py   # bash 的 Windows 改写/拦截 + 重复调用刹车
python tests/verify_server.py  # 后端静态页 + /api/tree 冒烟
```

> 自测与 trace 都在临时副本里跑，不会动交付用的 `workspace/stats.py`（bug 始终保留）。

## 已知边界

- 图片识别依赖视觉模型；非视觉模型下 `read` 图片只回文字说明。
- MCP server 是在你机器上跑的进程，装第三方 server = 装一个有权限的依赖（P34）：看源码、限权限。
- 本仓库 `workspace/stats.py` 故意留了 bug，方便现场演示"发现→修复→跑测试"。
