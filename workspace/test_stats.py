"""stats 模块的测试。可直接 `python test_stats.py` 运行，无需 pytest。

演示链路（P19）：
  未修复前：mean([]) 返回 0  → AssertionError: mean([]) should raise ValueError（exit=1）
  修复后  ：mean([]) 抛 ValueError → Ran 3 tests … OK（exit=0）
"""
import sys

from stats import mean, variance


def test_mean_basic():
    assert mean([1, 2, 3]) == 2.0
    assert mean([10]) == 10.0


def test_mean_empty_raises():
    try:
        mean([])
        raise AssertionError("mean([]) should raise ValueError")
    except ValueError:
        pass


def test_variance_basic():
    assert abs(variance([2, 4, 4, 4, 5, 5, 7, 9]) - 4.0) < 1e-9


def main():
    tests = [test_mean_basic, test_mean_empty_raises, test_variance_basic]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ok  {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {e}")
    print(f"Ran {len(tests)} tests … {'OK' if passed == len(tests) else 'FAIL'}")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
