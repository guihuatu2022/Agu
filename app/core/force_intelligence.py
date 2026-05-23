"""
主力侦察核心模块：回答5个问题
1. 是否有主力？
2. 主力是机构还是游资？
3. 控盘程度多少？
4. 主力当前在干什么？（11个细分阶段）
5. 建议如何操作？

设计哲学：
- 不试图猜"主力心理"（玄学）
- 只识别"主力行为留下的客观痕迹"
- 每个判断都有明确的客观规则和阈值
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .indicators import (
    daily_amplitude,
    extreme_day_count,
    is_bearish_alignment,
    is_bullish_alignment,
    kongpan,
    sma,
    volume_health_ratio,
    volume_stagnation,
)


# ============ 阶段常量 ============

class Phase:
    """主阶段。"""
    ACCUMULATION = "吸筹期"
    STARTUP = "启动期"
    RALLY = "拉升期"
    SHAKEOUT = "洗盘期"
    DISTRIBUTION = "派发期"
    DECLINE = "杀跌期"
    BOTTOM_REVERSAL = "底部反转苗头"
    TRANSITION = "过渡期"


class SubPhase:
    """子阶段（11个细分）。"""
    ACCUMULATION_EARLY = "吸筹期-早期"
    ACCUMULATION_LATE = "吸筹期-后期"
    STARTUP = "启动期"
    RALLY_EARLY = "拉升期-初期"
    RALLY_MID = "拉升期-中期"
    RALLY_ACCEL = "拉升期-加速期"
    SHAKEOUT = "洗盘期"
    DISTRIBUTION_EARLY = "派发期-早期"
    DISTRIBUTION_MID = "派发期-中期"
    DECLINE = "杀跌期"
    BOTTOM_REVERSAL = "底部反转苗头"
    TRANSITION = "过渡期"


# 子阶段 → 主阶段的映射
SUB_TO_MAIN = {
    SubPhase.ACCUMULATION_EARLY: Phase.ACCUMULATION,
    SubPhase.ACCUMULATION_LATE: Phase.ACCUMULATION,
    SubPhase.STARTUP: Phase.STARTUP,
    SubPhase.RALLY_EARLY: Phase.RALLY,
    SubPhase.RALLY_MID: Phase.RALLY,
    SubPhase.RALLY_ACCEL: Phase.RALLY,
    SubPhase.SHAKEOUT: Phase.SHAKEOUT,
    SubPhase.DISTRIBUTION_EARLY: Phase.DISTRIBUTION,
    SubPhase.DISTRIBUTION_MID: Phase.DISTRIBUTION,
    SubPhase.DECLINE: Phase.DECLINE,
    SubPhase.BOTTOM_REVERSAL: Phase.BOTTOM_REVERSAL,
    SubPhase.TRANSITION: Phase.TRANSITION,
}

# 阶段动作描述（主力在干什么）
PHASE_ACTIONS = {
    SubPhase.ACCUMULATION_EARLY: {
        "action": "悄悄收集筹码",
        "details": "底部缩量震荡，主力小心翼翼建仓，避免引人注意",
        "next_likely": "继续震荡 1~3 个月直到筹码收集完成",
    },
    SubPhase.ACCUMULATION_LATE: {
        "action": "完成建仓，准备启动",
        "details": "筹码已基本收集完毕，控盘指标转正，开始小幅抬高股价",
        "next_likely": "随时可能突破启动",
    },
    SubPhase.STARTUP: {
        "action": "试盘、突破前期高点",
        "details": "主力开始主动拉升，测试上方抛压",
        "next_likely": "如果突破成功 → 进入拉升期",
    },
    SubPhase.RALLY_EARLY: {
        "action": "确立趋势，吸引跟风",
        "details": "持续放量上涨，制造赚钱效应，吸引散户和游资跟风",
        "next_likely": "回踩MA20洗盘 → 继续拉升",
    },
    SubPhase.RALLY_MID: {
        "action": "拉抬-洗盘-再拉抬，循环推进",
        "details": "通过有节奏的洗盘，剔除浮筹同时让股价稳步上行",
        "next_likely": "进入加速期或洗盘期",
    },
    SubPhase.RALLY_ACCEL: {
        "action": "拉升加速，吸引最后一批跟风盘",
        "details": "成交量放大，连续阳线，制造FOMO情绪。这是最甜也最危险的阶段",
        "next_likely": "顶部即将出现，警惕派发信号",
    },
    SubPhase.SHAKEOUT: {
        "action": "震仓洗盘，赶下车跟风者",
        "details": "故意制造下跌假象，让散户割肉，自己以更低成本接回",
        "next_likely": "洗盘成功 → 继续拉升 / 洗盘失败 → 趋势破坏",
    },
    SubPhase.DISTRIBUTION_EARLY: {
        "action": "悄悄出货",
        "details": "高位横盘震荡，每天少量减仓，制造'还在涨'的假象",
        "next_likely": "完成派发后开始杀跌",
    },
    SubPhase.DISTRIBUTION_MID: {
        "action": "加速出货",
        "details": "放量但股价不创新高，开始真正的派发。散户还在'抄底'",
        "next_likely": "进入杀跌期",
    },
    SubPhase.DECLINE: {
        "action": "已撤退，让散户自相踩踏",
        "details": "主力已经走了，剩下的下跌是散户互相砍仓",
        "next_likely": "等到极致缩量+恐慌见底",
    },
    SubPhase.BOTTOM_REVERSAL: {
        "action": "新主力开始试探",
        "details": "出现新的资金回流，但还不确定是真主力还是反弹",
        "next_likely": "如果资金持续 → 新一轮吸筹期",
    },
    SubPhase.TRANSITION: {
        "action": "信号混乱",
        "details": "各项指标矛盾，无法明确判断主力意图",
        "next_likely": "等明确信号出现",
    },
}


# ============ 数据类 ============

@dataclass
class ForceIntelligence:
    """主力侦察的完整结果。"""
    # Q1
    has_force: bool = False
    force_strength: int = 0   # 0-100
    force_strength_level: str = ""  # 强/中/弱

    # Q2
    force_type: str = ""      # 机构主导 / 游资主导 / 混战 / 散户为主
    inst_score: int = 0
    youzi_score: int = 0

    # Q3
    control_pct: float = 0.0  # 0-100
    control_level: str = ""

    # Q4
    main_phase: str = ""      # Phase 之一
    sub_phase: str = ""       # SubPhase 之一
    days_in_phase: int = 0
    phase_score: int = 0      # 阶段确定度 0-100
    phase_features: list[str] = field(default_factory=list)
    action_desc: dict = field(default_factory=dict)

    # 辅助指标
    kongpan_now: float = 0.0
    kongpan_trend: str = ""
    vol_ratio: float = 1.0


# ============ Q1: 是否有主力 ============

def has_main_force(
    df: pd.DataFrame,
    flow_df: Optional[pd.DataFrame] = None,
    basic_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Q1: 这只票是否有主力？
    
    评分维度（满分100）：
    - 维度1：换手率特征（30分）
    - 维度2：股价稳定性（30分）
    - 维度3：资金集中度（40分）
    
    结论：
    - 评分 >= 60 → 有主力
    - 80+ 强主力 / 60-79 中 / <60 弱或无
    """
    if len(df) < 30:
        return {"has_force": False, "score": 0, "level": "数据不足", "details": []}

    score = 0
    details = []

    # 维度1：换手率特征
    avg_turnover = None
    if basic_df is not None and not basic_df.empty and "turnover_rate" in basic_df.columns:
        avg_turnover = basic_df["turnover_rate"].tail(60).mean()
        if pd.isna(avg_turnover):
            avg_turnover = None

    if avg_turnover is not None:
        if 1.5 < avg_turnover < 8:
            score += 30
            details.append(f"换手率{avg_turnover:.2f}% 适度活跃 ✓")
        elif avg_turnover < 0.5:
            details.append(f"换手率{avg_turnover:.2f}% 极度冷清，无主力或已撤")
        elif avg_turnover > 15:
            score += 10
            details.append(f"换手率{avg_turnover:.2f}% 过高，散户为主")
        else:
            score += 20
            details.append(f"换手率{avg_turnover:.2f}% 正常")
    else:
        # 没有换手率数据，用成交量稳定性近似
        vol_std = df["vol"].tail(30).std() / df["vol"].tail(30).mean() if df["vol"].tail(30).mean() > 0 else 1
        if vol_std < 0.6:
            score += 20
            details.append("成交量稳定（无换手数据，估算）")
        else:
            score += 10

    # 维度2：股价稳定性
    avg_amp = daily_amplitude(df, window=60)
    if avg_amp < 0.04:
        score += 30
        details.append(f"日均振幅{avg_amp*100:.2f}% 克制 → 主力护盘 ✓")
    elif avg_amp < 0.06:
        score += 20
        details.append(f"日均振幅{avg_amp*100:.2f}% 适中")
    else:
        score += 5
        details.append(f"日均振幅{avg_amp*100:.2f}% 偏大 → 散户为主")

    # 维度3：资金集中度（大单占比）
    if flow_df is not None and not flow_df.empty:
        recent_flow = flow_df.tail(20)
        big_buy = (
            recent_flow["buy_lg_amount"].fillna(0)
            + recent_flow["buy_elg_amount"].fillna(0)
        ).sum()  # 万元
        # 同期成交额
        recent_amount = df.tail(20)["amount"].sum()  # 千元
        recent_amount_wan = recent_amount / 10  # 转万元

        if recent_amount_wan > 0:
            big_ratio = big_buy / recent_amount_wan
            if big_ratio > 0.35:
                score += 40
                details.append(f"大单买入占比{big_ratio*100:.1f}% 高度集中 ✓")
            elif big_ratio > 0.25:
                score += 25
                details.append(f"大单买入占比{big_ratio*100:.1f}% 中等")
            else:
                score += 10
                details.append(f"大单买入占比{big_ratio*100:.1f}% 偏低")

    score = max(0, min(100, score))

    if score >= 80:
        level = "强"
    elif score >= 60:
        level = "中"
    else:
        level = "弱"

    return {
        "has_force": score >= 60,
        "score": score,
        "level": level,
        "details": details,
    }


# ============ Q2: 主力性质 ============

def identify_force_type(
    df: pd.DataFrame,
    flow_df: Optional[pd.DataFrame] = None,
    basic_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Q2: 主力性质 - 机构 / 游资 / 混战 / 散户。
    
    机构特征：
    - 振幅克制
    - 极端涨跌日少
    - 持续创新高+少暴涨（慢牛节奏）
    - 换手率适度
    
    游资特征：
    - 振幅剧烈
    - 频繁极端涨跌
    - 高换手
    - 脉冲式上涨
    """
    if len(df) < 30:
        return {
            "type": "数据不足",
            "inst_score": 0,
            "youzi_score": 0,
            "details": [],
        }

    inst_score = 0
    youzi_score = 0
    details = []

    # 维度1：振幅
    avg_amp = daily_amplitude(df, window=30)
    if avg_amp < 0.04:
        inst_score += 25
        details.append(f"振幅{avg_amp*100:.2f}% 平稳 → 机构特征")
    elif avg_amp > 0.07:
        youzi_score += 25
        details.append(f"振幅{avg_amp*100:.2f}% 剧烈 → 游资特征")
    else:
        details.append(f"振幅{avg_amp*100:.2f}% 居中")

    # 维度2：极端涨跌日
    extreme_count = extreme_day_count(df, window=30, threshold=0.07)
    if extreme_count >= 5:
        youzi_score += 30
        details.append(f"近30日有{extreme_count}个>7%涨跌 → 游资暴力")
    elif extreme_count <= 1:
        inst_score += 20
        details.append(f"近30日仅{extreme_count}个>7%涨跌 → 机构平稳")

    # 维度3：换手率
    if basic_df is not None and not basic_df.empty and "turnover_rate" in basic_df.columns:
        avg_turn = basic_df["turnover_rate"].tail(30).mean()
        if not pd.isna(avg_turn):
            if 1.5 < avg_turn < 4:
                inst_score += 25
                details.append(f"换手率{avg_turn:.2f}% 适度 → 机构")
            elif avg_turn > 8:
                youzi_score += 25
                details.append(f"换手率{avg_turn:.2f}% 偏高 → 游资")

    # 维度4：上涨节奏（机构=阶梯，游资=脉冲）
    recent_30 = df.tail(30)
    pct = recent_30.get("pct_chg")
    if pct is None:
        pct = (recent_30["close"] - recent_30["pre_close"]) / recent_30["pre_close"] * 100

    # 创新高的天数
    closes = recent_30["close"].values
    new_high_days = sum(
        closes[i] >= np.max(closes[:i + 1])
        for i in range(len(closes))
    )
    big_up_days = int((pct > 5).sum())

    if new_high_days > 8 and big_up_days < 3:
        inst_score += 20
        details.append(f"持续创新高({new_high_days}天)+少暴涨({big_up_days}天) → 慢牛节奏")
    elif big_up_days >= 3:
        youzi_score += 15
        details.append(f"近30日有{big_up_days}个>5%涨幅 → 脉冲式")

    # 综合判定
    if inst_score >= 60 and inst_score > youzi_score * 1.3:
        force_type = "机构主导"
    elif youzi_score >= 60 and youzi_score > inst_score * 1.3:
        force_type = "游资主导"
    elif abs(inst_score - youzi_score) < 20 and (inst_score + youzi_score) > 80:
        force_type = "机构+游资混战"
    else:
        force_type = "散户为主（无明显主力）"

    return {
        "type": force_type,
        "inst_score": inst_score,
        "youzi_score": youzi_score,
        "details": details,
    }


# ============ Q3: 控盘程度 ============

def control_level(
    df: pd.DataFrame,
    flow_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Q3: 主力控盘程度。
    
    用三个维度估算（非真实L2数据，是基于公开数据的近似）：
    - 大单占比稳定度（50%权重）
    - 控盘指标当前强度（30%权重）
    - 价格集中度近似（20%权重）
    """
    if len(df) < 30:
        return {"percent": 0.0, "level": "数据不足", "desc": ""}

    # 1. 大单占比平均（近似筹码集中）
    big_ratio_pct = 30.0  # 默认30%
    if flow_df is not None and not flow_df.empty:
        recent_flow = flow_df.tail(60)
        recent_amount = df.tail(60)["amount"].sum()  # 千元
        if recent_amount > 0:
            big_buy = (
                recent_flow["buy_lg_amount"].fillna(0)
                + recent_flow["buy_elg_amount"].fillna(0)
            ).sum()
            recent_amount_wan = recent_amount / 10
            big_ratio_pct = min(100.0, (big_buy / recent_amount_wan) * 100)

    # 2. 控盘指标强度（近期峰值的相对位置）
    kp_series = kongpan(df["close"])
    kp_now = kp_series.iloc[-1]
    kp_60_max = kp_series.tail(60).max()
    if kp_60_max > 0 and kp_now > 0:
        kp_strength = min(100.0, (kp_now / kp_60_max) * 100)
    else:
        kp_strength = 0.0

    # 3. 价格集中度近似：成交价集中区间的占比
    # 用近60日"收盘价集中在某10%区间"的天数比例
    recent_60 = df.tail(60)
    price_range = recent_60["close"].max() - recent_60["close"].min()
    if price_range > 0:
        # 找最常出现的价格区间
        bins = pd.cut(recent_60["close"], bins=10)
        max_bin_pct = bins.value_counts().iloc[0] / len(recent_60) * 100
    else:
        max_bin_pct = 50.0

    # 综合控盘度
    control_pct = (
        big_ratio_pct * 0.5
        + kp_strength * 0.3
        + max_bin_pct * 0.2
    )
    control_pct = max(0.0, min(100.0, control_pct))

    if control_pct >= 70:
        level = "高度控盘"
        desc = "主力高度控盘，散户筹码很少"
    elif control_pct >= 50:
        level = "中度控盘"
        desc = "主力控盘但散户仍有筹码"
    elif control_pct >= 30:
        level = "弱控盘"
        desc = "筹码分散，控盘度低"
    else:
        level = "无控盘"
        desc = "筹码混乱，主力难以推动"

    return {
        "percent": float(control_pct),
        "level": level,
        "desc": desc,
        "components": {
            "big_ratio": big_ratio_pct,
            "kongpan_strength": kp_strength,
            "price_concentration": max_bin_pct,
        },
    }


# ============ Q4: 主力在干什么（11个细分阶段）============

def identify_phase(
    df: pd.DataFrame,
    flow_df: Optional[pd.DataFrame] = None,
    circ_mv_yi: Optional[float] = None,
) -> dict:
    """
    Q4: 主力当前所处的细分阶段。
    
    返回：
      sub_phase: 11个细分阶段之一
      main_phase: 主阶段
      score: 该阶段的确定度 0-100
      features: 触发该判断的特征证据
    """
    if len(df) < 60:
        return {
            "sub_phase": SubPhase.TRANSITION,
            "main_phase": Phase.TRANSITION,
            "score": 0,
            "features": ["数据不足"],
        }

    df = df.copy()
    df["ma5"] = sma(df["close"], 5)
    df["ma20"] = sma(df["close"], 20)
    df["ma60"] = sma(df["close"], 60)
    df["kongpan"] = kongpan(df["close"])

    last = df.iloc[-1]
    close = last["close"]
    ma5 = last["ma5"]
    ma20 = last["ma20"]
    ma60 = last["ma60"]
    kp_now = last["kongpan"]

    # 通用变量
    period_high_60 = df["close"].tail(60).max()
    period_high_120 = df["close"].tail(120).max()
    period_low_60 = df["close"].tail(60).min()
    dist_ma20 = (close - ma20) / ma20 if ma20 > 0 else 0
    dist_ma60 = (close - ma60) / ma60 if ma60 > 0 else 0
    dist_high_60 = (close - period_high_60) / period_high_60 if period_high_60 > 0 else 0
    dist_high_120 = (close - period_high_120) / period_high_120 if period_high_120 > 0 else 0

    bullish = is_bullish_alignment(df)
    bearish = is_bearish_alignment(df)

    # 控盘趋势
    kp_5_ago = df["kongpan"].iloc[-6] if len(df) >= 6 else kp_now
    kp_rising = kp_now > kp_5_ago

    # 量能
    recent_5_vol = df["vol"].tail(5).mean()
    earlier_20_vol = df["vol"].iloc[-25:-5].mean() if len(df) >= 25 else recent_5_vol
    vol_expanding = earlier_20_vol > 0 and recent_5_vol > earlier_20_vol * 1.3
    vol_shrinking = earlier_20_vol > 0 and recent_5_vol < earlier_20_vol * 0.8

    # 是否近期创新高
    last_5 = df.tail(5)
    has_recent_high = bool((last_5["high"] >= period_high_60 * 0.999).any())

    # 振幅特征
    amp_30 = daily_amplitude(df, 30)

    # 60日内涨跌幅
    rise_60d = (close - df["close"].iloc[-60]) / df["close"].iloc[-60] if len(df) >= 60 else 0

    # 资金信号
    flow_5d_pos = flow_10d_pos = flow_20d_pos = False
    if flow_df is not None and not flow_df.empty and "net_mf_amount" in flow_df.columns:
        f5 = flow_df["net_mf_amount"].tail(5).sum()
        f10 = flow_df["net_mf_amount"].tail(min(10, len(flow_df))).sum()
        f20 = flow_df["net_mf_amount"].tail(min(20, len(flow_df))).sum()
        flow_5d_pos = f5 > 0
        flow_10d_pos = f10 > 0
        flow_20d_pos = f20 > 0

    # ============ 各阶段评分 ============
    scores = {}
    features_map = {}

    # ----- 拉升期-加速期 -----
    s = 0
    f = []
    if bullish and has_recent_high and dist_ma60 > 0.20:
        s += 25; f.append(f"距MA60 {dist_ma60*100:.1f}% 已远离")
    if vol_expanding and rise_60d > 0.30:
        s += 25; f.append(f"近60日上涨{rise_60d*100:.1f}%且放量")
    if kp_now > 0 and kp_rising:
        s += 20; f.append(f"控盘{kp_now:.2f}上升")
    pct_5d = (close - df["close"].iloc[-6]) / df["close"].iloc[-6] if len(df) >= 6 else 0
    if pct_5d > 0.10:
        s += 30; f.append(f"近5日涨{pct_5d*100:.1f}%")
    scores[SubPhase.RALLY_ACCEL] = s
    features_map[SubPhase.RALLY_ACCEL] = f

    # ----- 拉升期-中期 -----
    s = 0
    f = []
    if bullish and not bearish:
        s += 20; f.append("多头排列")
    if has_recent_high and 0.05 < dist_ma60 < 0.30:
        s += 25; f.append(f"距MA60 {dist_ma60*100:.1f}% 健康范围")
    if flow_5d_pos and flow_10d_pos and flow_20d_pos:
        s += 25; f.append("资金三窗口均正")
    if kp_now > 0 and kp_rising:
        s += 15; f.append("控盘指标>0且上升")
    _vh = volume_health_ratio(df, 20)
    if _vh is not None and 1.0 < _vh < 2.5:
        s += 15; f.append("量价健康")
    scores[SubPhase.RALLY_MID] = s
    features_map[SubPhase.RALLY_MID] = f

    # ----- 拉升期-初期 -----
    s = 0
    f = []
    # 刚突破前期高点不久
    if bullish and 0 < dist_ma60 < 0.10:
        s += 25; f.append(f"距MA60 {dist_ma60*100:.1f}% 刚突破")
    if 0 < dist_ma20 < 0.05:
        s += 20; f.append(f"距MA20 {dist_ma20*100:.1f}% 接近均线")
    if flow_5d_pos and flow_10d_pos:
        s += 20; f.append("近期资金转正")
    # 60日内见底反弹
    if dist_high_60 > -0.10:
        s += 15; f.append("接近60日新高")
    if kp_now > 0:
        s += 20; f.append("控盘转正")
    scores[SubPhase.RALLY_EARLY] = s
    features_map[SubPhase.RALLY_EARLY] = f

    # ----- 启动期 -----
    s = 0
    f = []
    # 突破前期平台
    last_30 = df.tail(30).iloc[:-3] if len(df) >= 33 else df.head(0)
    if len(last_30) > 0:
        platform_high = last_30["high"].max()
        if close > platform_high * 1.02 and close < platform_high * 1.08:
            s += 35; f.append(f"刚突破{len(last_30)}日平台")
        if vol_expanding and (close > platform_high):
            s += 25; f.append("放量突破")
    if kp_now > 0 and kp_rising and close > ma20:
        s += 20; f.append("控盘转正+站上MA20")
    if (flow_5d_pos and not flow_20d_pos) or (flow_5d_pos and flow_10d_pos):
        s += 20; f.append("近期资金转正")
    scores[SubPhase.STARTUP] = s
    features_map[SubPhase.STARTUP] = f

    # ----- 吸筹期-后期 -----
    s = 0
    f = []
    if dist_high_60 < -0.10 and dist_high_60 > -0.30:
        s += 20; f.append(f"距前高{dist_high_60*100:.1f}% 低位")
    if amp_30 < 0.06:
        s += 20; f.append(f"30日振幅仅{amp_30*100:.2f}% 横盘")
    if 0 < kp_now < 1.5 and kp_rising:
        s += 25; f.append("控盘指标刚转正")
    if abs(dist_ma20) < 0.05 and close > ma20:
        s += 15; f.append("站稳MA20附近")
    if vol_shrinking or (not vol_expanding):
        s += 10; f.append("量能温和")
    if flow_20d_pos and not flow_5d_pos:
        s += 10; f.append("20日累计正但近期反复")
    scores[SubPhase.ACCUMULATION_LATE] = s
    features_map[SubPhase.ACCUMULATION_LATE] = f

    # ----- 吸筹期-早期 -----
    s = 0
    f = []
    if dist_high_60 < -0.20:
        s += 25; f.append(f"距前高{dist_high_60*100:.1f}% 深度低位")
    if amp_30 < 0.05:
        s += 25; f.append(f"30日振幅仅{amp_30*100:.2f}% 极度横盘")
    if vol_shrinking:
        s += 20; f.append("地量")
    if kp_now < 0 or (0 < kp_now < 0.5):
        s += 15; f.append("控盘刚要转正")
    # 60日内涨跌幅小
    if abs(rise_60d) < 0.10:
        s += 15; f.append(f"60日涨跌仅{rise_60d*100:.1f}% 几乎横盘")
    scores[SubPhase.ACCUMULATION_EARLY] = s
    features_map[SubPhase.ACCUMULATION_EARLY] = f

    # ----- 洗盘期（拉升中段健康调整）-----
    s = 0
    f = []
    # 必要条件：之前涨过30%+且现在没破位
    if rise_60d > 0.15 and bullish and abs(dist_ma60) > 0.05:
        s += 30; f.append(f"60日涨{rise_60d*100:.1f}%后调整")
    # 当前从前高回撤5~15%
    if -0.15 < dist_high_60 < -0.05:
        s += 25; f.append(f"距前高{dist_high_60*100:.1f}% 健康回撤")
    # 缩量回调
    if vol_shrinking:
        s += 25; f.append("缩量回调（无人卖）")
    # 控盘仍正
    if kp_now > 0:
        s += 20; f.append("控盘仍为正（主力未撤）")
    scores[SubPhase.SHAKEOUT] = s
    features_map[SubPhase.SHAKEOUT] = f

    # ----- 派发期-早期 -----
    s = 0
    f = []
    if dist_high_60 > -0.05 and bullish:
        s += 15; f.append(f"在60日高点附近({dist_high_60*100:+.1f}%)")
    if vol_expanding and not has_recent_high:
        s += 25; f.append("放量但近5日未创新高")
    if flow_10d_pos and not flow_5d_pos:
        s += 25; f.append("10日仍正但5日转负")
    if kp_now > 0 and not kp_rising:
        s += 15; f.append("控盘高位但开始下降")
    if rise_60d > 0.30:
        s += 10; f.append("60日涨幅>30%（前期有拉升）")
    else:
        s = max(0, s - 30)  # 没拉升不算派发
    scores[SubPhase.DISTRIBUTION_EARLY] = s
    features_map[SubPhase.DISTRIBUTION_EARLY] = f

    # ----- 派发期-中期 -----
    s = 0
    f = []
    if -0.10 < dist_high_60 < -0.03:
        s += 20; f.append(f"距前高{dist_high_60*100:.1f}% 高位回落中")
    if volume_stagnation(df, 20):
        s += 30; f.append("放量滞涨（疑似派发）")
    if not flow_5d_pos and flow_20d_pos:
        s += 25; f.append("20日累计正但5日明显转负")
    if kp_now > 0 and not kp_rising:
        s += 15; f.append("控盘从高位下降")
    if rise_60d > 0.20:
        s += 10
    else:
        s = max(0, s - 20)
    scores[SubPhase.DISTRIBUTION_MID] = s
    features_map[SubPhase.DISTRIBUTION_MID] = f

    # ----- 杀跌期 -----
    s = 0
    f = []
    if bearish:
        s += 25; f.append("空头排列")
    if not flow_5d_pos and not flow_10d_pos and not flow_20d_pos:
        s += 25; f.append("资金三窗口均负")
    if kp_now < 0 and not kp_rising:
        s += 20; f.append("控盘<0且下降")
    if dist_ma60 < -0.05:
        s += 20; f.append(f"已跌破MA60 {dist_ma60*100:.1f}%")
    if vol_shrinking and bearish:
        s += 10; f.append("阴跌缩量（无承接）")
    scores[SubPhase.DECLINE] = s
    features_map[SubPhase.DECLINE] = f

    # ----- 底部反转苗头 -----
    s = 0
    f = []
    # 经过明显下跌后开始企稳
    if rise_60d < -0.10 and dist_high_120 < -0.20:
        s += 20; f.append(f"长期下跌后（60日{rise_60d*100:.1f}%）")
    if kp_now < 0 and kp_rising:
        s += 25; f.append("控盘<0但开始回升")
    if flow_5d_pos and not flow_10d_pos:
        s += 25; f.append("近5日资金转正")
    # 极致缩量后量能开始回升
    earlier_20 = df["vol"].iloc[-40:-20].mean() if len(df) >= 40 else 0
    if vol_expanding and earlier_20 > 0 and df["vol"].tail(5).mean() < earlier_20 * 1.5:
        s += 15; f.append("缩量后温和放量")
    # 长下影线
    last_3 = df.tail(3)
    for _, row in last_3.iterrows():
        body = abs(row["close"] - row["open"])
        lower_shadow = min(row["open"], row["close"]) - row["low"]
        if body > 0 and lower_shadow > body * 2:
            s += 15; f.append("近3日出现长下影K线"); break
    scores[SubPhase.BOTTOM_REVERSAL] = s
    features_map[SubPhase.BOTTOM_REVERSAL] = f

    # 选最高分
    max_phase = max(scores, key=scores.get)
    max_score = scores[max_phase]

    # 阈值：< 50 归为过渡期
    if max_score < 50:
        return {
            "sub_phase": SubPhase.TRANSITION,
            "main_phase": Phase.TRANSITION,
            "score": max_score,
            "features": ["信号混杂，无明确阶段特征"],
            "all_scores": scores,
        }

    return {
        "sub_phase": max_phase,
        "main_phase": SUB_TO_MAIN[max_phase],
        "score": max_score,
        "features": features_map[max_phase],
        "all_scores": scores,
    }


def estimate_days_in_phase(
    df: pd.DataFrame,
    target_phase: str,
    flow_df: Optional[pd.DataFrame] = None,
    circ_mv_yi: Optional[float] = None,
    max_lookback: int = 60,
) -> int:
    """
    估算当前阶段已经持续了多少个交易日。
    向前回溯，找到最近一次"不在该阶段"的日子。
    
    注意：这个函数会回溯调用 identify_phase，性能开销较大。
    扫描器场景应该用 stock_analysis 表里预计算的 days_in_phase。
    """
    if len(df) < 30:
        return 0

    days = 0
    for i in range(min(max_lookback, len(df) - 30)):
        # 取截至倒数第 i 天的数据
        sub_df = df.iloc[: len(df) - i]
        sub_flow = flow_df.iloc[: len(flow_df) - i] if flow_df is not None and not flow_df.empty else None

        result = identify_phase(sub_df, sub_flow, circ_mv_yi)
        if result["sub_phase"] != target_phase:
            return days
        days += 1
    return days


# ============ 主入口：完整侦察 ============

def full_intelligence(
    df: pd.DataFrame,
    flow_df: Optional[pd.DataFrame] = None,
    basic_df: Optional[pd.DataFrame] = None,
    circ_mv_yi: Optional[float] = None,
    days_in_phase: Optional[int] = None,
) -> ForceIntelligence:
    """
    完整主力侦察。返回 ForceIntelligence 对象。
    
    days_in_phase: 如果已经从数据库读取了"持续天数"，传入避免重复计算。
                   否则会本地估算（仅当前30个交易日内）。
    """
    result = ForceIntelligence()

    # Q1
    q1 = has_main_force(df, flow_df, basic_df)
    result.has_force = q1["has_force"]
    result.force_strength = q1["score"]
    result.force_strength_level = q1["level"]

    # Q2
    q2 = identify_force_type(df, flow_df, basic_df)
    result.force_type = q2["type"]
    result.inst_score = q2["inst_score"]
    result.youzi_score = q2["youzi_score"]

    # Q3
    q3 = control_level(df, flow_df)
    result.control_pct = q3["percent"]
    result.control_level = q3["level"]

    # Q4
    q4 = identify_phase(df, flow_df, circ_mv_yi)
    result.main_phase = q4["main_phase"]
    result.sub_phase = q4["sub_phase"]
    result.phase_score = q4["score"]
    result.phase_features = q4["features"]
    result.action_desc = PHASE_ACTIONS.get(result.sub_phase, {})

    if days_in_phase is not None:
        result.days_in_phase = days_in_phase
    else:
        # 仅做粗略估算，scanner 应该用预计算结果
        result.days_in_phase = 1

    # 辅助指标
    if len(df) >= 14:
        kp_series = kongpan(df["close"])
        result.kongpan_now = float(kp_series.iloc[-1])
        kp_5_ago = kp_series.iloc[-6] if len(kp_series) >= 6 else kp_series.iloc[-1]
        result.kongpan_trend = "上升" if result.kongpan_now > kp_5_ago else "下降"

    result.vol_ratio = volume_health_ratio(df, 20) or 1.0

    return result
