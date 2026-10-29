# workspace

这是智能体的**工作区**——它只能读/写这个目录里的文件（路径越界会被拒绝）。

- `stats.py`：示例模块，故意留了一个 bug（`mean([])` 应抛 `ValueError`，却返回 0）。
- `test_stats.py`：对应测试，可直接 `python test_stats.py` 运行。

把你的课程项目文件放进这个目录，智能体就能在上面改代码、跑测试。
