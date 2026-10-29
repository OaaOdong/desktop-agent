"""示例模块：故意留一个 bug——mean([]) 应该抛 ValueError，这里却返回 0。

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
