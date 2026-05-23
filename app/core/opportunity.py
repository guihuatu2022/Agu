"""
机会等级识别 + 综合评分。
基于阶段、板块、大盘、技术面综合判断。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .force_intelligence import (
    ForceIntelligence, Phase, SubPhase,
)


# 等级常量
LEVEL_A_RALLY_ADD = "A级·拉升加仓"
LEVEL_A_RIGHT_ENTRY = "A级·右侧建仓"
LEVEL_B_ACCUMULATION = "B级·吸筹试仓"
LEVEL_C_LEFT_WATCH = "C级·左侧观察"
LEVEL_NONE = "无机会"


LEVEL_INFO = {
    LEVEL_A_RALLY_ADD: {
        "color": "🟢",
        "css_class": "opp-a",
        "certainty": "高",
        "win_rate": "65~75%",
        "position": "加仓 30~50%",
        "stop_loss": "跌破MA20且3日不收复",
        "rationale": "已在拉升期，回踩是上车机会",
    },
    LEVEL_A_RIGHT_ENTRY: {
        "color": "🟢",
        "css_class": "opp-a",
        "certainty": "高",
        "win_rate": "55~65%",
        "position": "建仓 30~50%",
        "stop_loss": "跌破MA20且3日不收复",
        "rationale": "右侧确认+回踩，趋势票最佳介入点",
    },
    LEVEL_B_ACCUMULATION: {
        "color": "🟠",
        "css_class": "opp-b",
        "certainty": "中",
        "win_rate": "45~55%",
        "position": "试仓 20~30%",
        "stop_loss": "跌破吸筹平台下沿",
        "rationale": "吸筹后期，主力即将启动但未确认",
    },
    LEVEL_C_LEFT_WATCH: {
        "color": "🔵",
        "css_class": "opp-c",
        "certainty": "低",
        "win_rate": "35~45%",
        "position": "不入场，仅加入观察名单",
        "stop_loss": "—",
        "rationale": "底部预警≥3项，但趋势未反转",
    },
    LEVEL_NONE: {
        "color": "—",
        "css_class": "",
        "certainty": "—",
        "win_rate": "—",
        "position": "无操作",
        "stop_loss": "—",
        "rationale": "无明确机会",
    },
}


@dataclass
class OpportunityResult:
    level: str = LEVEL_NONE
    reason: str = ""
    matched_conditions: list[str] = None
    buy_zone_low: Optional[float] = None
    buy_zone_high: Optional[float] = None
    stop_loss: Optional[float] = None
    first_target: Optional[float] = None
    second_target: Optional[float] = None
    wait_for: list[str] = None

    def __post_init__(self):
        if self.matched_conditions is None:
            self.matched_conditions = []
        if self.wait_for is None:
            self.wait_for = []


def identify_opportunity(
    intelligence: ForceIntelligence,
    close: float,
    ma20: float,
    ma60: float,
    flow_5d_pos: bool = False,
    flow_10d_pos: bool = False,
    flow_20d_pos: bool = False,
    is_volume_shrinking: bool = False,
    sector_strong: bool = False,
    market_uptrend: bool = True,
) -> OpportunityResult:
    """
    综合判断当前机会等级。
    
    优先级：A级·拉升加仓 > A级·右侧建仓 > B级·吸筹试仓 > C级·左侧观察 > 无
    """
    if not intelligence:
        return OpportunityResult(level=LEVEL_NONE, reason="无侦察数据")

    phase = intelligence.main_phase
    sub_phase = intelligence.sub_phase
    days = intelligence.days_in_phase
    has_force = intelligence.has_force

    # 通用判断
    dist_ma20 = (close - ma20) / ma20 if ma20 > 0 else 0
    near_ma20 = abs(dist_ma20) < 0.05
    above_ma20 = close > ma20
    above_ma60 = close > ma60

    # ============ A级 - 拉升加仓 ============
    if phase == Phase.RALLY and days >= 5 and has_force:
        # 已在拉升期 5 天以上，正在回踩
        if near_ma20 and above_ma20 and is_volume_shrinking and \
           flow_5d_pos and flow_10d_pos and flow_20d_pos:
            return OpportunityResult(
                level=LEVEL_A_RALLY_ADD,
                reason="拉升期持续>5天+回踩MA20+缩量+资金健康",
                matched_conditions=[
                    f"拉升期已持续 {days} 个交易日",
                    f"距MA20 {dist_ma20*100:+.2f}%（回踩位）",
                    "近期缩量（无人卖）",
                    "资金三窗口均正",
                ] + ([f"板块强势"] if sector_strong else []),
                buy_zone_low=ma20 * 0.99,
                buy_zone_high=ma20 * 1.03,
                stop_loss=ma60 * 0.97,
                first_target=close * 1.10,
                second_target=close * 1.25,
            )

    # ============ A级 - 右侧建仓 ============
    if phase == Phase.RALLY and 1 <= days <= 8 and has_force:
        # 拉升期刚确立，第一次回踩或继续上行
        if (near_ma20 or sub_phase == SubPhase.RALLY_EARLY) and above_ma20 and \
           flow_5d_pos and flow_10d_pos:
            return OpportunityResult(
                level=LEVEL_A_RIGHT_ENTRY,
                reason="趋势刚切换为拉升期+回踩MA20+资金转正",
                matched_conditions=[
                    f"刚切换至拉升期 {days} 个交易日（早期）",
                    f"距MA20 {dist_ma20*100:+.2f}%",
                    "资金近10日累计转正",
                    f"控盘指标={intelligence.kongpan_now:.2f} {intelligence.kongpan_trend}",
                ] + ([f"板块强势"] if sector_strong else []),
                buy_zone_low=ma20 * 0.99,
                buy_zone_high=close * 1.02,
                stop_loss=ma60 * 0.97,
                first_target=close * 1.15,
                second_target=close * 1.30,
            )

    # ============ A级 - 启动期 ============
    if sub_phase == SubPhase.STARTUP and has_force and 1 <= days <= 5:
        if above_ma20 and (flow_5d_pos or intelligence.kongpan_now > 0):
            return OpportunityResult(
                level=LEVEL_A_RIGHT_ENTRY,
                reason="启动期早期+站稳MA20",
                matched_conditions=[
                    f"启动期第 {days} 天",
                    "刚突破前期平台",
                    "站稳MA20",
                ],
                buy_zone_low=close * 0.98,
                buy_zone_high=close * 1.02,
                stop_loss=ma20 * 0.97,
                first_target=close * 1.15,
                second_target=close * 1.30,
            )

    # ============ B级 - 吸筹试仓 ============
    if sub_phase == SubPhase.ACCUMULATION_LATE and has_force:
        if above_ma20 and (intelligence.kongpan_now > 0 or flow_5d_pos):
            return OpportunityResult(
                level=LEVEL_B_ACCUMULATION,
                reason="吸筹后期+控盘转正+站稳MA20",
                matched_conditions=[
                    f"吸筹期已持续 {days} 天",
                    "控盘指标转正",
                    "站稳MA20附近",
                ],
                buy_zone_low=close * 0.97,
                buy_zone_high=close * 1.02,
                stop_loss=ma60 * 0.97,
                first_target=close * 1.15,
                second_target=close * 1.30,
            )

    # ============ C级 - 左侧观察 ============
    if phase in (Phase.DECLINE, Phase.BOTTOM_REVERSAL):
        if sub_phase == SubPhase.BOTTOM_REVERSAL:
            return OpportunityResult(
                level=LEVEL_C_LEFT_WATCH,
                reason="底部反转苗头",
                matched_conditions=[
                    f"已在 {sub_phase}",
                    "仍在反转过程中，趋势未确认",
                ],
                wait_for=[
                    "阶段切换为吸筹期/拉升期",
                    "站回MA20且3日不破",
                    "主力资金5日累计稳定为正",
                ],
            )

    return OpportunityResult(level=LEVEL_NONE, reason="无明确机会")


def compute_score(
    intelligence: ForceIntelligence,
    opportunity: OpportunityResult,
    sector_strong: bool = False,
    market_uptrend: bool = True,
) -> int:
    """
    综合评分 0-100。
    
    基础分50 + 各维度调整
    """
    score = 50

    # 主力强度
    score += int(intelligence.force_strength * 0.15)  # 最多+15

    # 阶段评分（0-100缩放到-25到+25）
    phase_pts_map = {
        Phase.RALLY: 25,
        Phase.SHAKEOUT: 15,
        Phase.STARTUP: 20,
        Phase.ACCUMULATION: 5,
        Phase.BOTTOM_REVERSAL: 0,
        Phase.DISTRIBUTION: -15,
        Phase.DECLINE: -25,
        Phase.TRANSITION: 0,
    }
    score += phase_pts_map.get(intelligence.main_phase, 0)

    # 子阶段微调
    sub_phase_adjust = {
        SubPhase.RALLY_MID: 5,
        SubPhase.RALLY_EARLY: 5,
        SubPhase.RALLY_ACCEL: -5,  # 末期降权（接近顶部）
        SubPhase.SHAKEOUT: 5,      # 洗盘期机会
        SubPhase.DISTRIBUTION_MID: -10,
    }
    score += sub_phase_adjust.get(intelligence.sub_phase, 0)

    # 控盘度
    if intelligence.control_pct >= 70:
        score += 8
    elif intelligence.control_pct >= 50:
        score += 4

    # 主力性质
    if "机构主导" in intelligence.force_type:
        score += 5
    elif "游资主导" in intelligence.force_type:
        score += 2

    # 板块共振
    if sector_strong:
        score += 8

    # 大盘环境
    if not market_uptrend:
        score = int(score * 0.85)  # 大盘下行 × 0.85

    # 机会等级加成
    if opportunity.level.startswith("A级"):
        score += 5

    return max(0, min(100, score))
