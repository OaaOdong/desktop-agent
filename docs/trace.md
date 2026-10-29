# Trace：一次完整运行记录

> 以下输出由本项目的真实代码（`agent/loop.py` + 四个工具）在 `MockLLM` 驱动下产生，
> 仅把模型换成脚本化回复，工具执行、循环、事件流全是真实逻辑。
> 演示场景：修复 `workspace/stats.py` 里 `mean([])` 的 bug，并跑测试验证。
> 其中**故意先犯一个"old_string 太短不唯一"的错**，再纠正——展示失败与自我恢复。

```
[system] 智能体就绪 · 工作区 .../desktop-agent/workspace · 最多 8 步
[system] 已挂载工具：bash, edit, read, write

--- 第 1 步 ---
[action] 🔧 read  {"path": "stats.py"}  (builtin)
[observation/ok] ↳ read:
    1	"""示例模块：故意留一个 bug——mean([]) 应该抛 ValueError，这里却返回 0。
    2	
    3	大作业演示场景（P19/P35）：让智能体发现并修掉这个 bug，再跑测试验证。
    4	"""
    5	
    6	
    7	def mean(nums):
    8	    if not nums:
    9	        return 0.0  # BUG（演示用）：空列表应该抛 ValueError，这里却返回 0
   10	    total = 0
   11	    for n in nums:
   12	        total += n
   13	    return total / len(nums)
   14	
   15	
   16	def variance(nums):
   17	    m = mean(nums)
   18	    return sum((n - m) ** 2 for n in nums) / len(nums)

--- 第 2 步 ---
[action] 🔧 edit  {"path": "stats.py", "old_string": "n", "new_string": "X"}  (builtin)
[observation/ERROR] ↳ edit:
工具执行出错：old_string 出现 24 次，不唯一，拒绝猜测替换。请提供更多上下文让它唯一，或改用更精确的片段。

--- 第 3 步 ---
[action] 🔧 edit  {"path": "stats.py", "old_string": "        return 0.0  # BUG（演示用）：空列表应该抛 ValueError，这里却返回 0", "new_string": "        raise ValueError(\"mean() arg is an empty sequence\")"}  (builtin)
[observation/ok] ↳ edit:
已编辑 stats.py：1 处替换成功

--- 第 4 步 ---
[action] 🔧 bash  {"command": "python test_stats.py"}  (builtin)
[observation/ok] ↳ bash:
exit_code=0
--- stdout ---
  ok  test_mean_basic
  ok  test_mean_empty_raises
  ok  test_variance_basic
Ran 3 tests … OK

--- stderr ---


--- 第 5 步 ---
[assistant] 已修复 mean([]) 的 bug：空列表现在抛 ValueError，3 个测试全部通过。
[final] ✅ 已修复 mean([]) 的 bug：空列表现在抛 ValueError，3 个测试全部通过。
```

## 这段 trace 说明了什么

1. **工具调用全部可见**：读了哪个文件、改了哪一行、命令输出、测试结果，UI 里一步一步都能看到。
2. **失败不静默**：第 2 步 edit 因"不唯一"被工具拒绝（标红 ERROR），模型拿到错误信息后自我纠正——这正是评分里"一次真实恢复"要的东西。
3. **改完真的验证**：第 4 步用 bash 跑测试，exit_code=0、Ran 3 tests … OK，而不是嘴上说"已修复"。
4. **循环有出口**：没有工具调用即收工（final），步数到上限则转人工——三道护栏之一。

> 接入真实模型后，输出形态完全一致，只是 `action` 的 `old_string/new_string/command` 由模型生成。
> 复现：`python tests/generate_trace.py`（在临时副本里跑，不会改动交付用的 `workspace/stats.py`）。

## 附：接入真实模型时踩到的一次失败（已修）

用 DeepSeek 真实跑同一条任务时，智能体在"验证"环节原地打转，最终撞上步数上限：

```
[action] 🔧 bash  {"command": "python -m pytest -q 2>&1 | tail -20"}
[observation/ERROR] ↳ bash:
exit_code=255
--- stderr ---
'tail' is not recognized as an internal or external command, operable program or batch file.

[action] 🔧 bash  {"command": "python -m pytest -q"}
[observation/ERROR] ↳ bash:
exit_code=1
--- stderr ---
python.exe: No module named pytest

... （重复同一命令，直到 max_steps）
[system] 达到步数上限，转人工。
```

三个根因，都在代码里修掉了，而不是靠提示词祈祷：

| 根因 | 修法 | 位置 |
| --- | --- | --- |
| 模型按 Unix 习惯写 `\| tail -20`，Windows cmd 没有该命令 | 纯截断管道自动去掉，输出截断改由 Python 侧负责；其余 Unix 命令直接拒绝并提示 cmd 等价写法 | `agent/tools.py` `_prepare_command` |
| 环境里没装 pytest，模型反复重试同一命令 | 预装 pytest；运行环境（OS/shell/cwd/解释器/文件清单）动态拼进 system prompt；测试脚本本身是 unittest 风格，`python test_stats.py` 即可 | `agent/loop.py` `_env_block` + `.env` |
| 同一条失败命令被反复执行，直到耗尽步数 | 重复调用拦截（同一签名失败过且期间文件未改动 → 拒绝执行）+ 连续失败 3 次要求模型收敛、6 次直接停止 | `agent/loop.py` `run()` |
