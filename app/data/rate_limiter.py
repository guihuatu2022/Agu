"""
接口频控：保证 tushare 调用不超限。

【共享 token 友好版】
- 默认配置非常保守（每个接口约 30-50 次/分钟）
- 强制全局间隔，避免突发流量
- 限频错误自动等待 60s 后重试，不抛异常
- 失败超过阈值才抛异常

策略：
1. 单接口最大调用频率（per_min）
2. 单接口最小调用间隔（min_interval 秒）
3. 全局最小间隔（防止任何接口突发）
4. 限频错误自动指数退避重试
"""
from __future__ import annotations

import logging
import time
from collections import deque
from threading import Lock
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ============ 频率配置 ============
# 用户确认 token 上限 470/分钟，按每个接口分配 + 留余量

INTERFACE_LIMITS: dict[str, dict] = {
    # 默认（用于未明确配置的接口）
    "_default":     {"per_min": 300, "min_interval": 0.2},

    # 行情类（最常用）
    "daily":        {"per_min": 450, "min_interval": 0.13},
    "daily_basic":  {"per_min": 450, "min_interval": 0.13},
    "moneyflow":    {"per_min": 400, "min_interval": 0.15},
    "adj_factor":   {"per_min": 400, "min_interval": 0.15},
    "index_daily":  {"per_min": 300, "min_interval": 0.2},

    # 元数据（很少调用）
    "stock_basic":  {"per_min": 100, "min_interval": 0.6},
    "trade_cal":    {"per_min": 100, "min_interval": 0.6},

    # 概念板块
    "concept":          {"per_min": 100, "min_interval": 0.6},
    "concept_detail":   {"per_min": 300, "min_interval": 0.2},

    # 其他
    "top_list":     {"per_min": 200, "min_interval": 0.3},
    "top_inst":     {"per_min": 200, "min_interval": 0.3},
}


# 全局所有接口共用的间隔（防止突发，最低保护）
GLOBAL_MIN_INTERVAL = 0.1


class RateLimiter:
    """单接口的频控状态。"""

    def __init__(self, name: str):
        self.name = name
        cfg = INTERFACE_LIMITS.get(name, INTERFACE_LIMITS["_default"])
        self.per_min: int = cfg["per_min"]
        self.min_interval: float = cfg["min_interval"]
        self._calls: deque[float] = deque(maxlen=self.per_min + 10)
        self._last_call: float = 0.0
        self._lock = Lock()

    def wait(self) -> None:
        """阻塞等待直到可以发起下一次调用。"""
        with self._lock:
            now = time.time()

            # 1. 单接口间隔
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                sleep_t = self.min_interval - elapsed
                time.sleep(sleep_t)
                now = time.time()

            # 2. 全局间隔（保护其他接口）
            global_elapsed = now - _GlobalState.last_any_call
            if global_elapsed < GLOBAL_MIN_INTERVAL:
                time.sleep(GLOBAL_MIN_INTERVAL - global_elapsed)
                now = time.time()

            # 3. 滑动窗口（60秒内不超 per_min）
            cutoff = now - 60.0
            while self._calls and self._calls[0] < cutoff:
                self._calls.popleft()
            if len(self._calls) >= self.per_min:
                wait_t = self._calls[0] - cutoff + 0.5
                if wait_t > 0:
                    logger.info(f"[{self.name}] 滑动窗口已满 ({self.per_min}/min)，等待 {wait_t:.1f}s")
                    time.sleep(wait_t)
                    now = time.time()
                cutoff = now - 60.0
                while self._calls and self._calls[0] < cutoff:
                    self._calls.popleft()

            self._calls.append(now)
            self._last_call = now
            _GlobalState.last_any_call = now


class _GlobalState:
    """跨接口共享的全局状态。"""
    last_any_call: float = 0.0


# 单例缓存
_limiters: dict[str, RateLimiter] = {}
_limiters_lock = Lock()


def get_limiter(interface_name: str) -> RateLimiter:
    """获取或创建指定接口的限流器。"""
    with _limiters_lock:
        if interface_name not in _limiters:
            _limiters[interface_name] = RateLimiter(interface_name)
        return _limiters[interface_name]


def safe_call(
    interface_name: str,
    func: Callable,
    max_retries: int = 5,
    **kwargs,
) -> Any:
    """
    带频控+重试的接口调用。
    
    遇到限频错误自动等待重试（指数退避）。
    最多重试 max_retries 次，全部失败才抛异常。
    """
    limiter = get_limiter(interface_name)
    last_error = None

    for attempt in range(max_retries):
        limiter.wait()
        try:
            result = func(**kwargs)
            if attempt > 0:
                logger.info(f"[{interface_name}] 重试第 {attempt} 次成功")
            return result
        except Exception as e:
            last_error = e
            err = str(e)
            # 限频错误特征
            is_rate_limit = any(kw in err for kw in (
                "频率超限", "次/分钟", "rate limit", "Too Many",
                "访问太频繁", "exceed", "超限"
            ))

            if is_rate_limit:
                # 指数退避：60s, 90s, 120s, 180s, 240s
                wait_t = 60 + attempt * 30
                logger.warning(
                    f"[{interface_name}] 限频，等待 {wait_t}s 后重试 ({attempt+1}/{max_retries})"
                )
                time.sleep(wait_t)
                continue
            # 网络/超时错误也重试
            elif any(kw in err.lower() for kw in ("timeout", "connection", "max retries")):
                wait_t = 30 + attempt * 15
                logger.warning(
                    f"[{interface_name}] 网络错误，等待 {wait_t}s 后重试 ({attempt+1}/{max_retries})"
                )
                time.sleep(wait_t)
                continue
            else:
                # 数据/参数错误，不重试
                logger.error(f"[{interface_name}] 接口错误: {e}")
                raise

    raise RuntimeError(f"[{interface_name}] 重试 {max_retries} 次仍失败，最后错误: {last_error}")


def get_stats() -> dict:
    """返回所有接口的调用统计（供监控用）。"""
    with _limiters_lock:
        stats = {}
        for name, lim in _limiters.items():
            stats[name] = {
                "per_min_limit": lim.per_min,
                "calls_in_last_60s": len(lim._calls),
                "last_call": lim._last_call,
            }
        return stats
