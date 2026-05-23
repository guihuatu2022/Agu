"""
大盘形态识别：13种细分形态 + 市场风格判断。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .indicators import sma, ema, to_weekly, daily_amplitude


# 形态常量
PATTERN_BOTTOM_REVERSAL_START = "底部反转启动期"
PATTERN_RALLY_EARLY = "主升浪初期"
PATTERN_RALLY_MID = "主升浪中期"
PATTERN_RALLY_ACCEL = "主升浪加速期"
PATTERN_RALLY_END = "主升浪末期"
PATTERN_TOP_BUILD = "顶部构筑期"
PATTERN_TOP_CONFIRM = "顶部确立"
PATTERN_DECLINE = "趋势下跌期"
PATTERN_DECLINE_ACCEL = "加速杀跌期"
PATTERN_DECLINE_END = "杀跌末期"
PATTERN_BOTTOM_BUILD = "底部构筑期"
PATTERN_INTERMEDIATE = "中级整理"
PATTERN_OSCILLATION = "大箱体震荡"


@dataclass
class MarketPattern:
    """大盘形态识别结果。"""
    pattern: str
    duration_weeks: int  # 当前形态已持续多少周
    weekly_rise_pct: float  # 周线累计涨跌幅
    drawdown_from_high: float  # 距前高回撤
    description: str = ""


def identify_market_pattern(daily_df: pd.DataFrame) -> MarketPattern:
    """
    识别大盘当前形态。
    输入：日线数据，至少200天
    """
    if len(daily_df) < 60:
        return MarketPattern(
            pattern=PATTERN_OSCILLATION,
            duration_weeks=0,
            weekly_rise_pct=0,
            drawdown_from_high=0,
            description="数据不足",
        )

    # 转周线
    weekly = to_weekly(daily_df.copy())
    if len(weekly) < 20:
        return MarketPattern(
            pattern=PATTERN_OSCILLATION,
            duration_weeks=0,
            weekly_rise_pct=0,
            drawdown_from_high=0,
            description="数据不足",
        )

    # 周线指标
    weekly["ma20"] = sma(weekly["close"], 20)
    weekly["ma60"] = sma(weekly["close"], 60)

    last = weekly.iloc[-1]
    close = last["close"]
    ma20 = last["ma20"]
    ma60 = last["ma60"]

    # 关键参考点
    period_high = weekly["close"].tail(52).max()
    period_low = weekly["close"].tail(52).min()
    drawdown = (close - period_high) / period_high if period_high > 0 else 0

    # 周线MA60趋势
    if len(weekly) >= 70:
        ma60_5_ago = weekly["ma60"].iloc[-6]
        ma60_rising = ma60 > ma60_5_ago
    else:
        ma60_rising = True

    # 多头/空头排列
    above_ma20 = close > ma20
    above_ma60 = close > ma60
    bullish_weekly = above_ma20 and above_ma60 and ma20 > ma60
    bearish_weekly = (close < ma20) and (close < ma60) and (ma20 < ma60)

    # 近期累计涨跌
    weekly_rise_4w = (close - weekly["close"].iloc[-5]) / weekly["close"].iloc[-5] \
        if len(weekly) >= 5 else 0
    weekly_rise_12w = (close - weekly["close"].iloc[-13]) / weekly["close"].iloc[-13] \
        if len(weekly) >= 13 else 0
    weekly_rise_26w = (close - weekly["close"].iloc[-27]) / weekly["close"].iloc[-27] \
        if len(weekly) >= 27 else 0

    # 距前高/前低
    near_high = drawdown > -0.03
    deep_drop = drawdown < -0.20

    # 持续多少周在某种状态（粗略估算）
    duration = _estimate_pattern_duration(weekly)

    # ============ 判断形态 ============

    # 1. 顶部构筑：在前高附近 + MA20还往上 + 振幅放大
    if near_high and ma20 > ma60 and weekly_rise_4w < 0.02 and weekly_rise_12w > 0.10:
        return MarketPattern(
            pattern=PATTERN_TOP_BUILD,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_4w * 100,
            drawdown_from_high=drawdown * 100,
            description="高位横盘震荡，警惕反转",
        )

    # 2. 主升浪加速期：陡峭上升 + 持续创新高
    if bullish_weekly and weekly_rise_4w > 0.10 and near_high:
        return MarketPattern(
            pattern=PATTERN_RALLY_ACCEL,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_4w * 100,
            drawdown_from_high=drawdown * 100,
            description="陡峭上升，量能配合，但需警惕末期",
        )

    # 3. 主升浪末期：高位 + MACD等动能衰竭迹象
    # 简化：高位 + 4周涨幅放缓
    if bullish_weekly and near_high and weekly_rise_4w < 0.05 and weekly_rise_12w > 0.15:
        return MarketPattern(
            pattern=PATTERN_RALLY_END,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_4w * 100,
            drawdown_from_high=drawdown * 100,
            description="主升浪末期，动能衰竭",
        )

    # 4. 主升浪中期：稳定多头 + 持续上升
    if bullish_weekly and ma60_rising and 8 <= duration <= 24 and weekly_rise_12w > 0.10:
        return MarketPattern(
            pattern=PATTERN_RALLY_MID,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_12w * 100,
            drawdown_from_high=drawdown * 100,
            description="中期主升浪，最舒服阶段",
        )

    # 5. 主升浪初期：刚突破 + 上升<8周
    if bullish_weekly and ma60_rising and duration < 8:
        return MarketPattern(
            pattern=PATTERN_RALLY_EARLY,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_4w * 100,
            drawdown_from_high=drawdown * 100,
            description="趋势刚确立",
        )

    # 6. 中级整理：上升趋势中的健康回调
    if (above_ma60 and ma60_rising and -0.10 < drawdown < -0.03 and not near_high
            and weekly_rise_26w > 0.10):
        return MarketPattern(
            pattern=PATTERN_INTERMEDIATE,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_4w * 100,
            drawdown_from_high=drawdown * 100,
            description="拉升中途休息，健康回踩",
        )

    # 7. 顶部确立：跌破上升趋势线
    if not above_ma20 and ma20 > ma60 and -0.15 < drawdown < -0.05 and weekly_rise_26w > 0.10:
        return MarketPattern(
            pattern=PATTERN_TOP_CONFIRM,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_4w * 100,
            drawdown_from_high=drawdown * 100,
            description="跌破上升趋势线，反转确认",
        )

    # 8. 趋势下跌期：跌破年线（MA60周线）+ 持续下行
    if bearish_weekly and not ma60_rising and drawdown < -0.10:
        # 加速杀跌特征：陡峭
        if weekly_rise_4w < -0.08:
            return MarketPattern(
                pattern=PATTERN_DECLINE_ACCEL,
                duration_weeks=duration,
                weekly_rise_pct=weekly_rise_4w * 100,
                drawdown_from_high=drawdown * 100,
                description="加速下跌，恐慌氛围",
            )
        return MarketPattern(
            pattern=PATTERN_DECLINE,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_4w * 100,
            drawdown_from_high=drawdown * 100,
            description="趋势下跌中，避免抄底",
        )

    # 9. 杀跌末期：深度下跌 + 缩量
    daily_amp = daily_amplitude(daily_df, 30)
    if deep_drop and daily_amp < 0.025 and weekly_rise_4w > -0.03:
        return MarketPattern(
            pattern=PATTERN_DECLINE_END,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_4w * 100,
            drawdown_from_high=drawdown * 100,
            description="缩量见底，恐慌退潮",
        )

    # 10. 底部构筑期：低位横盘
    if drawdown < -0.15 and abs(weekly_rise_12w) < 0.05 and daily_amp < 0.03:
        return MarketPattern(
            pattern=PATTERN_BOTTOM_BUILD,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_4w * 100,
            drawdown_from_high=drawdown * 100,
            description="底部蓄势，等待启动",
        )

    # 11. 底部反转启动：刚突破年线
    if (above_ma20 and not above_ma60 or
            (above_ma60 and not ma60_rising and weekly_rise_4w > 0.05)):
        return MarketPattern(
            pattern=PATTERN_BOTTOM_REVERSAL_START,
            duration_weeks=duration,
            weekly_rise_pct=weekly_rise_4w * 100,
            drawdown_from_high=drawdown * 100,
            description="底部反转启动，等待确认",
        )

    # 默认：大箱体震荡
    return MarketPattern(
        pattern=PATTERN_OSCILLATION,
        duration_weeks=duration,
        weekly_rise_pct=weekly_rise_4w * 100,
        drawdown_from_high=drawdown * 100,
        description="多空僵持",
    )


def _estimate_pattern_duration(weekly: pd.DataFrame) -> int:
    """
    粗略估算当前形态持续多少周。
    用 close 和 MA20 的关系判断转折点。
    """
    if len(weekly) < 4:
        return 0
    # 当前是上方还是下方
    cur_above = weekly["close"].iloc[-1] > weekly["ma20"].iloc[-1]
    count = 0
    for i in range(len(weekly) - 1, -1, -1):
        is_above = weekly["close"].iloc[i] > weekly["ma20"].iloc[i] \
            if pd.notna(weekly["ma20"].iloc[i]) else cur_above
        if is_above == cur_above:
            count += 1
        else:
            break
    return count


# ============ 市场风格判断 ============

def identify_market_style(index_data: dict[str, pd.DataFrame]) -> dict:
    """
    判断当前市场风格。
    
    输入：dict, key=指数代码, value=该指数日线DataFrame
    
    返回：
      style: 风格名称（小盘成长牛/大盘价值牛/题材投机牛/...）
      details: 各对比指标
    """
    def pct_chg_n(df: pd.DataFrame, n: int) -> float | None:
        if len(df) < n + 1:
            return None
        recent = df.iloc[-1]["close"]
        earlier = df.iloc[-(n+1)]["close"]
        return (recent - earlier) / earlier * 100 if earlier else None

    sh50 = index_data.get("000016.SH")  # 上证50（大盘）
    csi300 = index_data.get("000300.SH")
    csi1000 = index_data.get("000852.SH")  # 中证1000（中小盘）
    csi2000 = index_data.get("932000.CSI")  # 中证2000（小微盘）
    chinext = index_data.get("399006.SZ")  # 创业板
    star50 = index_data.get("000688.SH")   # 科创50

    # 近20日表现
    perf = {}
    for code, df in index_data.items():
        if df is not None and not df.empty:
            perf[code] = pct_chg_n(df, 20)

    big = perf.get("000016.SH", 0) or 0
    mid = perf.get("000300.SH", 0) or 0
    small = perf.get("000852.SH", 0) or 0
    micro = perf.get("932000.CSI", 0) or 0
    growth = perf.get("399006.SZ", 0) or 0
    star = perf.get("000688.SH", 0) or 0

    # 判断
    big_avg = big
    small_avg = (small + micro) / 2 if micro else small
    growth_avg = (growth + star) / 2 if star else growth
    value_avg = big

    if small_avg > big_avg + 3 and growth_avg > value_avg + 2:
        style = "小盘成长牛"
        desc = "资金偏好小盘成长，机构票相对落后"
    elif small_avg > big_avg + 3:
        style = "小盘活跃"
        desc = "小微盘强势，关注题材机会"
    elif big_avg > small_avg + 3 and big_avg > 0:
        style = "大盘价值牛"
        desc = "蓝筹白马为主，机构抱团"
    elif growth_avg > value_avg + 3:
        style = "成长占优"
        desc = "成长股相对强势"
    elif all(v < -2 for v in [big, mid, small, growth]):
        style = "全面下跌"
        desc = "系统性风险，规避"
    elif all(abs(v) < 2 for v in [big, mid, small, growth] if v is not None):
        style = "横盘震荡"
        desc = "结构性行情，看主线板块"
    else:
        style = "题材轮动"
        desc = "无明显主线，板块快速轮动"

    return {
        "style": style,
        "description": desc,
        "performance_20d": perf,
    }
