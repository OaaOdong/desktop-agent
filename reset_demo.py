"""一键还原演示现场：把 workspace/stats.py 改回“带 bug”的版本，并清掉缓存。

为什么需要它：智能体演示成功一次，bug 就被它修掉了；再演示就没有“故障”可修。
双击 reset_demo.bat（或 `python reset_demo.py`）即可恢复现场。
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "workspace" / "stats.py"

BUGGY = '''"""示例模块：故意留一个 bug——mean([]) 应该抛 ValueError，这里却返回 0。

大作业演示场景（P19/P35）：让智能体发现并修掉这个 bug，再跑测试验证。
"""


def mean(nums):
    if not nums:
        return 0.0  # BUG（演示用）：空列表应该抛 ValueError，这里却返回 0
    total = 0
    for n in nums:
        total += n
    return total / len(nums)


def variance(nums):
    m = mean(nums)
    return sum((n - m) ** 2 for n in nums) / len(nums)
'''


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(BUGGY, encoding="utf-8")

    removed = []
    for cache in (ROOT / "workspace" / "__pycache__", ROOT / "workspace" / ".pytest_cache"):
        if cache.exists():
            shutil.rmtree(cache, ignore_errors=True)
            removed.append(cache.name)

    print(f"[OK] 已还原 {TARGET}")
    print(f"     mean([]) 现在返回 0.0（bug 已就位）")
    if removed:
        print(f"[OK] 已清理缓存：{', '.join(removed)}")
    print()
    print("下一步：双击 start.bat，在对话框输入")
    print("  读一下 stats.py，mean 对空列表的处理有问题，把它改对，然后运行 python test_stats.py 验证")
    return 0


if __name__ == "__main__":
    sys.exit(main())
