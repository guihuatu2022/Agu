"""
技术指标基础库。
所有函数纯函数式，输入 pandas Series/DataFrame，输出同形式。

设计原则：
- 不依赖数据库，只做计算
- 输入数据假定已经是前复权且时间正序
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ============ 基础均线 ============

def sma(series: pd.Series, period: int) -> pd.Series:
    """简单移动平均。min_periods=1 避免开头NaN，但前期数据不够时仍会失真。"""
    return series.rolling(window=period, min_periods=max(1, period // 2)).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """指数移动平均。"""
    return series.ewm(span=period, adjust=False).mean()


# ============ 周线聚合 ============

def to_weekly(df: pd.DataFrame, date_col: str = "trade_date") -> pd.DataFrame:
    """
    日线聚合成周线。需要 trade_date, open, high, low, close, vol 列。
    周线锚点：周五（W-FRI）。
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col)
    weekly = pd.DataFrame()
    weekly["open"] = df["open"].resample("W-FRI").first()
    weekly["high"] = df["high"].resample("W-FRI").max()
    weekly["low"] = df["low"].resample("W-FRI").min()
    weekly["close"] = df["close"].resample("W-FRI").last()
    weekly["vol"] = df["vol"].resample("W-FRI").sum()
    weekly = weekly.dropna().reset_index()
    return weekly


# ============ 控盘指标 ============

def kongpan(close: pd.Series, inner: int = 13, outer: int = 13) -> pd.Series:
    """
    控盘指标：双重EMA平滑后的当日变化率(乘1000)。
    
    意义：
    - > 0 且上升 → 主力推动中
    - > 0 且下降 → 主力放慢
    - < 0 且下降 → 主力撤退
    """
    smoothed = ema(ema(close, inner), outer)
    pct_change = (smoothed - smoothed.shift(1)) / smoothed.shift(1) * 1000
    return pct_change


# ============ 量价关系 ============

def volume_health_ratio(df: pd.DataFrame, window: int = 20) -> float | None:
    """
    近 window 日：上涨日均量 / 下跌日均量。
    
    > 1.3 = 主力承接强（健康）
    < 1.0 = 主力可能在出货
    
    数据不足返回 None（避免误判健康）。
    """
    recent = df.tail(window)
    if len(recent) < 5:
        return None

    up_days = recent[recent["close"] > recent["open"]]
    down_days = recent[recent["close"] < recent["open"]]

    if len(down_days) == 0:
        return 999.0
    if len(up_days) == 0:
        return 0.0

    up_avg = up_days["vol"].mean()
    down_avg = down_days["vol"].mean()

    if down_avg == 0 or pd.isna(down_avg):
        return 999.0
    if pd.isna(up_avg):
        return None
    return float(up_avg / down_avg)


def volume_stagnation(
    df: pd.DataFrame,
    window: int = 20,
    no_new_high_days: int = 3,
) -> bool:
    """
    放量滞涨判断（严格版，避免误判主升浪）。
    
    必须同时满足：
    - 近期成交量明显放大
    - 连续 no_new_high_days 日内未创新高
    - 当前价距前高已跌 5%+
    """
    if len(df) < window * 2:
        return False

    recent = df.tail(window)
    current_vol = recent["vol"].iloc[-5:].mean()
    earlier_vol = df["vol"].iloc[-window * 2:-window].mean()

    if earlier_vol == 0:
        return False

    vol_expanded = current_vol > earlier_vol * 1.5

    last_n = df.tail(no_new_high_days + 1)
    period_high = recent["high"].max()
    has_new_high_recently = bool(
        (last_n["high"].iloc[-no_new_high_days:] >= period_high * 0.999).any()
    )

    current_price = recent["close"].iloc[-1]
    far_from_high = current_price < period_high * 0.95

    return vol_expanded and not has_new_high_recently and far_from_high


# ============ MACD ============

def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """
    标准 MACD。
    返回 DataFrame: dif, dea, hist
    """
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    dif = ema_fast - ema_slow
    dea = ema(dif, signal)
    hist = (dif - dea) * 2
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": hist})


# ============ 振幅与波动率 ============

def daily_amplitude(df: pd.DataFrame, window: int = 30) -> float:
    """近 window 日的平均振幅 (high-low)/close。"""
    recent = df.tail(window)
    if len(recent) == 0:
        return 0.0
    amp = (recent["high"] - recent["low"]) / recent["close"]
    return float(amp.mean())


def extreme_day_count(df: pd.DataFrame, window: int = 30, threshold: float = 0.07) -> int:
    """近 window 日内涨跌幅绝对值超过 threshold 的天数。"""
    recent = df.tail(window)
    if len(recent) == 0:
        return 0
    abs_pct = recent["pct_chg"].abs() if "pct_chg" in recent.columns else (
        (recent["close"] - recent["pre_close"]) / recent["pre_close"] * 100
    ).abs()
    return int((abs_pct > threshold * 100).sum())


# ============ 资金多窗口分析 ============

def main_flow_trend(
    flow_df: pd.DataFrame,
    circ_mv_yi: float | None = None,
) -> dict | None:
    """
    多窗口主力资金趋势分析。
    
    输入：tushare moneyflow 返回的DataFrame，已计算 net_mf_amount 列（万元）
    返回：5/10/20日累计 + 方向判断 + 节奏
    """
    if flow_df is None or flow_df.empty or "net_mf_amount" not in flow_df.columns:
        return None

    n = len(flow_df)
    if n < 5:
        return None

    flow_5d = flow_df["net_mf_amount"].tail(5).sum() / 10000  # 万元 → 亿
    flow_10d = flow_df["net_mf_amount"].tail(min(10, n)).sum() / 10000
    flow_20d = flow_df["net_mf_amount"].tail(min(20, n)).sum() / 10000

    ratio_5d = (flow_5d / circ_mv_yi * 100) if circ_mv_yi else None
    ratio_10d = (flow_10d / circ_mv_yi * 100) if circ_mv_yi else None
    ratio_20d = (flow_20d / circ_mv_yi * 100) if circ_mv_yi else None

    p5, p10, p20 = flow_5d > 0, flow_10d > 0, flow_20d > 0

    if p5 and p10 and p20:
        direction, rating = "持续流入（三窗口均正）", "强"
    elif (not p5) and p10 and p20:
        direction, rating = "近期撤退（前期流入近5日转负）", "警惕"
    elif p5 and (not p10) and (not p20):
        direction, rating = "短线反弹（5日流入但中长期仍负）", "弱"
    elif (not p5) and (not p10) and (not p20):
        direction, rating = "持续流出（三窗口均负）", "撤退"
    elif p5 and p10 and (not p20):
        direction, rating = "由空转多（近期流入修复中）", "改善中"
    else:
        direction, rating = "震荡（无明确方向）", "中性"

    # 节奏判断
    avg_5d = flow_5d / 5
    avg_20d = flow_20d / 20 if n >= 20 else None
    momentum = "—"
    if avg_20d is not None and avg_20d != 0:
        if avg_5d > avg_20d * 1.5:
            momentum = "加速流入"
        elif avg_5d < avg_20d * 0.5 and avg_20d > 0:
            momentum = "流入放缓"
        elif avg_5d < 0 and avg_20d > 0:
            momentum = "由进转撤"
        else:
            momentum = "节奏稳定"

    return {
        "flow_5d_yi": float(flow_5d),
        "flow_10d_yi": float(flow_10d),
        "flow_20d_yi": float(flow_20d),
        "ratio_5d_pct": ratio_5d,
        "ratio_10d_pct": ratio_10d,
        "ratio_20d_pct": ratio_20d,
        "direction": direction,
        "rating": rating,
        "momentum": momentum,
    }


# ============ 大单占比 ============

def big_order_ratio(flow_df: pd.DataFrame, total_amount_series: pd.Series, window: int = 20) -> float:
    """
    大单+超大单占总成交的比例。
    flow_df 需要 buy_lg_amount, buy_elg_amount 列。
    """
    if flow_df is None or flow_df.empty:
        return 0.0
    recent_flow = flow_df.tail(window)
    big_amount = (
        recent_flow["buy_lg_amount"].fillna(0)
        + recent_flow["buy_elg_amount"].fillna(0)
    ).sum()
    recent_total = total_amount_series.tail(window).sum()
    if recent_total == 0:
        return 0.0
    # tushare moneyflow 单位是万元，amount 单位是千元，需转换
    return float(big_amount / (recent_total / 10))  # 千元转万元后比较


# ============ 趋势判断辅助 ============

def is_bullish_alignment(df: pd.DataFrame) -> bool:
    """日线多头排列：MA5 > MA20 > MA60。"""
    if len(df) < 60:
        return False
    close = df["close"]
    return bool(
        sma(close, 5).iloc[-1] > sma(close, 20).iloc[-1] > sma(close, 60).iloc[-1]
    )


def is_bearish_alignment(df: pd.DataFrame) -> bool:
    """日线空头排列：MA5 < MA20 < MA60。"""
    if len(df) < 60:
        return False
    close = df["close"]
    return bool(
        sma(close, 5).iloc[-1] < sma(close, 20).iloc[-1] < sma(close, 60).iloc[-1]
    )


def days_since_break(df: pd.DataFrame, ma_period: int = 60) -> int:
    """
    从最近一次跌破 MA{period} 到现在过了多少天。
    如果一直在均线上方，返回 999。
    """
    if len(df) < ma_period:
        return 0
    close = df["close"]
    ma_line = sma(close, ma_period)
    below = close < ma_line
    if not below.iloc[-1]:
        # 现在在均线上方，找最近一次跌破
        for i in range(len(df) - 1, -1, -1):
            if below.iloc[i]:
                return len(df) - 1 - i
        return 999
    else:
        # 现在在均线下方
        for i in range(len(df) - 1, -1, -1):
            if not below.iloc[i]:
                return -(len(df) - 1 - i)
        return -999
