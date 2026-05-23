"""
扫描器请求参数 + 校验。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ScanRequest(BaseModel):
    """全市场扫描的筛选参数。所有字段都有默认值，可部分提交。"""

    # ============ 1. 主力情况 ============
    has_force: Literal["required", "optional", "forbidden"] = "required"
    force_types: list[str] = Field(default_factory=lambda: ["机构主导"])
    control_min: float = Field(0, ge=0, le=100)
    control_max: float = Field(100, ge=0, le=100)

    # ============ 2. 主力阶段 ============
    phases: list[str] = Field(default_factory=list)
    sub_phases: list[str] = Field(default_factory=list)
    days_in_phase_min: int = Field(1, ge=1, le=365)
    days_in_phase_max: int = Field(365, ge=1, le=365)
    phase_score_min: int = Field(50, ge=0, le=100)

    # ============ 3. 板块联动 ============
    sectors: list[str] = Field(default_factory=list)
    sector_strength: Literal["strong", "persistent", "mild", "any"] = "any"
    require_sector_resonance: bool = False

    # ============ 4. 大盘环境 ============
    require_market_uptrend: bool = True

    # ============ 5. 技术面 ============
    weekly_uptrend: bool = False
    daily_alignment: bool = False
    dist_ma20_min: float = Field(-50, ge=-50, le=200)
    dist_ma20_max: float = Field(200, ge=-50, le=200)
    dist_high_max: float = Field(50, ge=0, le=100)
    vol_ratio_min: float = Field(0, ge=0, le=10)

    # ============ 6. 资金维度 ============
    flow_trend: Literal["all_positive", "two_positive", "any"] = "any"
    flow_5d_min_yi: float = Field(-1000, ge=-1000, le=1000)
    flow_5d_ratio_min: float = Field(-100, ge=-100, le=100)

    # ============ 7. 质地过滤 ============
    market_cap_min: float = Field(0, ge=0, le=100000)
    market_cap_max: float = Field(100000, ge=0, le=100000)
    exclude_st: bool = True
    exclude_new: bool = True
    exclude_boards: list[str] = Field(default_factory=list)

    # ============ 8. 机会等级 ============
    opportunity_levels: list[str] = Field(default_factory=list)
    score_min: int = Field(0, ge=0, le=100)

    # ============ 排序与分页 ============
    sort_by: Literal["score", "phase_days", "control_pct", "flow_5d", "pct_chg"] = "score"
    sort_order: Literal["desc", "asc"] = "desc"
    limit: int = Field(200, ge=1, le=1000)

    # ============ 校验：范围必须正确 ============

    @field_validator("force_types", "phases", "sub_phases", "sectors",
                     "exclude_boards", "opportunity_levels", mode="before")
    @classmethod
    def normalize_lists(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return list(v)

    @model_validator(mode="after")
    def check_ranges(self):
        if self.control_max < self.control_min:
            raise ValueError("控盘上限必须 ≥ 下限")
        if self.days_in_phase_max < self.days_in_phase_min:
            raise ValueError("阶段天数上限必须 ≥ 下限")
        if self.dist_ma20_max < self.dist_ma20_min:
            raise ValueError("距MA20上限必须 ≥ 下限")
        if self.market_cap_max < self.market_cap_min:
            raise ValueError("市值上限必须 ≥ 下限")
        return self


# ============ 5个内置预设 ============

PRESETS: dict[str, dict] = {
    "high_certainty": {
        "name": "最高确定性",
        "description": "机构主导+拉升中期+板块强势",
        "params": {
            "has_force": "required",
            "force_types": ["机构主导"],
            "control_min": 60,
            "phases": ["拉升期"],
            "sub_phases": ["拉升期-中期", "拉升期-初期"],
            "days_in_phase_min": 3,
            "days_in_phase_max": 15,
            "sector_strength": "strong",
            "require_sector_resonance": True,
            "require_market_uptrend": True,
            "flow_trend": "all_positive",
            "score_min": 75,
        },
    },
    "fast_entry": {
        "name": "最快右侧介入",
        "description": "拉升期第1-3天，最锐利的右侧买点",
        "params": {
            "has_force": "required",
            "force_types": ["机构主导", "机构+游资混战"],
            "phases": ["拉升期"],
            "sub_phases": ["拉升期-初期"],
            "days_in_phase_min": 1,
            "days_in_phase_max": 3,
            "control_min": 50,
            "sector_strength": "strong",
            "flow_trend": "two_positive",
            "score_min": 70,
        },
    },
    "accumulation": {
        "name": "吸筹后期布局",
        "description": "主力建仓完成待启动，中线埋伏",
        "params": {
            "has_force": "required",
            "phases": ["吸筹期"],
            "sub_phases": ["吸筹期-后期"],
            "days_in_phase_min": 10,
            "days_in_phase_max": 365,
            "control_min": 40,
            "sector_strength": "any",
            "score_min": 55,
        },
    },
    "dragon_return": {
        "name": "龙头回马枪",
        "description": "洗盘后再次启动，短中结合",
        "params": {
            "has_force": "required",
            "force_types": ["游资主导", "机构+游资混战"],
            "phases": ["洗盘期", "拉升期"],
            "sub_phases": ["洗盘期", "拉升期-中期"],
            "days_in_phase_min": 1,
            "days_in_phase_max": 10,
            "sector_strength": "strong",
            "dist_ma20_min": -3,
            "dist_ma20_max": 3,
            "score_min": 60,
        },
    },
    "left_watch": {
        "name": "左侧观察名单",
        "description": "跌透+反转苗头，仅观察不入场",
        "params": {
            "phases": ["底部反转苗头"],
            "sub_phases": ["底部反转苗头"],
            "control_min": 30,
            "opportunity_levels": ["C级·左侧观察"],
            "require_market_uptrend": False,
            "score_min": 40,
        },
    },
}
