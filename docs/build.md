# 打包说明（build）

目标：交一个能装的包（`.exe` / `.dmg`），双击出窗口，不是 `python app.py` 也不是 zip。

## 一、安装 pywebview（桌面窗口依赖）

```bash
pip install pywebview==5.2
```
Windows 上 pywebview 用系统自带 WebView2（Win10/11 一般已自带）；若缺失会提示安装 Edge WebView2 Runtime。

## 二、本地先验证能跑

```bash
pip install -r requirements.txt   # 或按 pyproject 安装
cp .env.example .env              # 填入 OPENAI_API_KEY / BASE_URL / MODEL
python run_desktop.py             # 应弹出原生窗口（无地址栏）
```

## 三、PyInstaller 打 Windows 安装包（--windowed 无控制台）

```bash
pip install pyinstaller
pyinstaller --windowed --name "我的Cursor" ^
  --add-data "ui;ui" --add-data "workspace;workspace" --add-data "example_server;example_server" ^
  --add-data "mcp.json;." ^
  run_desktop.py
```

要点（P38 踩坑提示）：
- **资源找不到 ui/ 是正常现象**：打包后路径变成 `sys._MEIPASS`，代码里凡是读 `ui/`、`workspace/` 都要用 `ROOT`
  （本项目 `agent/config.py` 已用 `__file__` 解析，无需改）。
- **可写目录用 `Path.home()`**：不要把用户数据写进程序目录。
- 打出来的 `dist/我的Cursor/` 就是一个文件夹，用 Inno Setup / NSIS 再包一层 `.exe` 安装向导即可。

## 四、其他平台的等价命令（可选）

- macOS（Tauri / electron-builder）：`tauri build` 或 `electron-builder --mac`
- 或直接 `python run_desktop.py --no-window` 起服务 + 任意前端打包方案。

## 五、交付清单核对

- [ ] `git tag v1.0.0`，Release 附件挂安装包
- [ ] 仓库 public，≥15 commit，跨度 ≥7 天
- [ ] `.env` 未入库（.gitignore 已含）；`.env.example` 只有 key 名
- [ ] `clone` 下来 `README` 三步内出窗口
- [ ] Release 里的安装包双击能开、能配 Key、能跑通一次任务
