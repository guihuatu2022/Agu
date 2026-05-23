"""
扫描器 API。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ScanHistory
from ..schemas.scanner import ScanRequest, PRESETS
from ..core.force_intelligence import SUB_TO_MAIN

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scan", tags=["scanner"])


@router.post("")
async def scan(req: ScanRequest, db: Session = Depends(get_db)):
    """执行全市场扫描。"""
    started = time.time()

    # 找到最新交易日
    latest_date = db.execute(
        text("SELECT MAX(trade_date) FROM stock_analysis")
    ).scalar()

    if not latest_date:
        return {
            "total": 0,
            "shown": 0,
            "results": [],
            "scan_time_ms": 0,
            "message": "暂无分析数据，请先完成数据初始化和分析计算",
        }

    # 构建SQL
    sql, params = _build_scan_sql(req, latest_date)
    rows = db.execute(text(sql), params).fetchall()

    # 应用排序+分页（已在SQL内）
    results = [dict(r._mapping) for r in rows]

    # 记录历史
    try:
        history = ScanHistory(
            params_json=req.model_dump_json(),
            result_count=len(results),
            result_codes_json=json.dumps([r["ts_code"] for r in results[:100]]),
            duration_ms=int((time.time() - started) * 1000),
        )
        db.add(history)
        db.commit()
    except Exception as e:
        logger.warning(f"扫描历史记录失败: {e}")

    return {
        "total": len(results),
        "shown": len(results),
        "results": results,
        "trade_date": latest_date.isoformat() if latest_date else None,
        "scan_time_ms": int((time.time() - started) * 1000),
    }


@router.get("/preview-count")
async def preview_count(req: ScanRequest = Depends(), db: Session = Depends(get_db)):
    """预估匹配数（不返回详细结果，仅给数字）。"""
    latest_date = db.execute(
        text("SELECT MAX(trade_date) FROM stock_analysis")
    ).scalar()
    if not latest_date:
        return {"count": 0}

    sql, params = _build_scan_sql(req, latest_date, count_only=True)
    cnt = db.execute(text(sql), params).scalar()
    return {"count": int(cnt or 0)}


@router.get("/presets")
async def list_presets():
    """列出所有预设方案。"""
    return {
        key: {
            "name": v["name"],
            "description": v["description"],
        }
        for key, v in PRESETS.items()
    }


@router.get("/presets/{name}")
async def get_preset(name: str):
    """获取某个预设的详细参数。"""
    if name not in PRESETS:
        raise HTTPException(404, f"预设 {name} 不存在")
    return PRESETS[name]


def _build_scan_sql(
    req: ScanRequest,
    latest_date,
    count_only: bool = False,
) -> tuple[str, dict]:
    """
    根据请求参数构建SQL。
    """
    where = ["a.trade_date = :trade_date"]
    params = {"trade_date": latest_date}

    # 1. 主力情况
    if req.has_force == "required":
        where.append("a.has_main_force = 1")
    elif req.has_force == "forbidden":
        where.append("a.has_main_force = 0")

    if req.force_types:
        placeholders = ", ".join(f":ft{i}" for i in range(len(req.force_types)))
        where.append(f"a.force_type IN ({placeholders})")
        for i, ft in enumerate(req.force_types):
            params[f"ft{i}"] = ft

    where.append("a.control_pct BETWEEN :ctrl_min AND :ctrl_max")
    params["ctrl_min"] = req.control_min
    params["ctrl_max"] = req.control_max

    # 2. 阶段
    if req.sub_phases:
        placeholders = ", ".join(f":sp{i}" for i in range(len(req.sub_phases)))
        where.append(f"a.sub_phase IN ({placeholders})")
        for i, p in enumerate(req.sub_phases):
            params[f"sp{i}"] = p
    elif req.phases:
        placeholders = ", ".join(f":p{i}" for i in range(len(req.phases)))
        where.append(f"a.phase IN ({placeholders})")
        for i, p in enumerate(req.phases):
            params[f"p{i}"] = p

    where.append("a.days_in_phase BETWEEN :day_min AND :day_max")
    params["day_min"] = req.days_in_phase_min
    params["day_max"] = req.days_in_phase_max

    where.append("a.phase_score >= :phase_score")
    params["phase_score"] = req.phase_score_min

    # 3. 板块共振
    if req.require_sector_resonance:
        where.append("a.is_sector_resonant = 1")

    # 5. 技术面
    where.append("a.dist_ma20 BETWEEN :ma20_min AND :ma20_max")
    params["ma20_min"] = req.dist_ma20_min / 100
    params["ma20_max"] = req.dist_ma20_max / 100

    if req.dist_high_max < 100:
        where.append("a.dist_high_120 >= :high_max")
        params["high_max"] = -req.dist_high_max / 100  # 距前高 -50% 表示比前高低50%

    where.append("(a.vol_ratio IS NULL OR a.vol_ratio >= :vol_ratio)")
    params["vol_ratio"] = req.vol_ratio_min

    # 6. 资金
    if req.flow_trend == "all_positive":
        where.append("a.flow_5d > 0 AND a.flow_10d > 0 AND a.flow_20d > 0")
    elif req.flow_trend == "two_positive":
        where.append(
            "((a.flow_5d > 0 AND a.flow_10d > 0) OR "
            " (a.flow_10d > 0 AND a.flow_20d > 0) OR "
            " (a.flow_5d > 0 AND a.flow_20d > 0))"
        )

    where.append("(a.flow_5d IS NULL OR a.flow_5d >= :flow_5d_min)")
    params["flow_5d_min"] = req.flow_5d_min_yi

    # 7. 质地
    where.append("(a.circ_mv IS NULL OR a.circ_mv / 10000 BETWEEN :mv_min AND :mv_max)")
    params["mv_min"] = req.market_cap_min
    params["mv_max"] = req.market_cap_max

    if req.exclude_st:
        where.append("(m.is_st = 0 OR m.is_st IS NULL)")
    if req.exclude_new:
        # 上市超过1年的票
        from datetime import timedelta as _td
        cutoff_dt = latest_date - _td(days=365) if hasattr(latest_date, 'year') else None
        if cutoff_dt:
            where.append("(m.list_date IS NOT NULL AND m.list_date <= :list_cutoff)")
            params["list_cutoff"] = cutoff_dt
    if req.exclude_boards:
        placeholders = ", ".join(f":b{i}" for i in range(len(req.exclude_boards)))
        where.append(f"(m.market IS NULL OR m.market NOT IN ({placeholders}))")
        for i, b in enumerate(req.exclude_boards):
            params[f"b{i}"] = b

    # 8. 机会
    if req.opportunity_levels:
        placeholders = ", ".join(f":opp{i}" for i in range(len(req.opportunity_levels)))
        where.append(f"a.opportunity_level IN ({placeholders})")
        for i, l in enumerate(req.opportunity_levels):
            params[f"opp{i}"] = l

    where.append("a.score >= :score_min")
    params["score_min"] = req.score_min

    where_clause = " AND ".join(where)

    if count_only:
        sql = f"""
            SELECT COUNT(*)
            FROM stock_analysis a
            LEFT JOIN stock_meta m ON a.ts_code = m.ts_code
            WHERE {where_clause}
        """
        return sql, params

    # 排序
    sort_field_map = {
        "score": "a.score",
        "phase_days": "a.days_in_phase",
        "control_pct": "a.control_pct",
        "flow_5d": "a.flow_5d",
        "pct_chg": "a.pct_chg",
    }
    sort_field = sort_field_map.get(req.sort_by, "a.score")
    sort_order = "DESC" if req.sort_order == "desc" else "ASC"

    sql = f"""
        SELECT
          a.ts_code, m.name AS stock_name, m.market, m.industry, m.is_st,
          a.trade_date, a.close, a.pct_chg,
          a.has_main_force, a.force_strength, a.force_type, a.control_pct, a.control_level,
          a.phase, a.sub_phase, a.days_in_phase, a.phase_score,
          a.opportunity_level, a.score,
          a.ma5, a.ma20, a.ma60,
          a.dist_ma20, a.dist_ma60, a.dist_high_120,
          a.flow_5d, a.flow_10d, a.flow_20d, a.flow_5d_ratio, a.flow_direction,
          a.vol_ratio, a.kongpan, a.kongpan_trend,
          a.primary_sector, a.is_sector_resonant,
          a.circ_mv, a.turnover_rate
        FROM stock_analysis a
        LEFT JOIN stock_meta m ON a.ts_code = m.ts_code
        WHERE {where_clause}
        ORDER BY {sort_field} {sort_order}, a.ts_code
        LIMIT :limit
    """
    params["limit"] = req.limit
    return sql, params
