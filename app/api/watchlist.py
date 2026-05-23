"""
自选股 API：增删改查 + 状态变化检查。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Watchlist

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


# ============ 请求模型 ============

class AddWatchRequest(BaseModel):
    ts_code: str
    name: str
    sector: Optional[str] = None
    cost_price: Optional[float] = Field(None, ge=0, le=100000)
    shares: Optional[int] = Field(None, ge=0)
    position_pct: Optional[float] = Field(None, ge=0, le=100)
    is_holding: bool = False


class UpdateWatchRequest(BaseModel):
    cost_price: Optional[float] = None
    shares: Optional[int] = None
    position_pct: Optional[float] = None
    status: Optional[str] = None


# ============ 路由 ============

@router.get("")
async def list_watchlist(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """列出自选股。"""
    where = []
    params = {}
    if status:
        where.append("w.status = :status")
        params["status"] = status
    else:
        where.append("w.status != 'removed'")

    where_clause = " AND ".join(where) if where else "1=1"

    rows = db.execute(text(f"""
        SELECT w.*,
               a.score, a.opportunity_level, a.phase, a.sub_phase,
               a.close, a.pct_chg, a.force_type, a.control_pct,
               a.is_sector_resonant
        FROM watchlist w
        LEFT JOIN stock_analysis a ON w.ts_code = a.ts_code
            AND a.trade_date = (SELECT MAX(trade_date) FROM stock_analysis)
        WHERE {where_clause}
        ORDER BY a.score DESC, w.added_at DESC
    """), params).fetchall()

    return [dict(r._mapping) for r in rows]


@router.post("")
async def add_to_watchlist(req: AddWatchRequest, db: Session = Depends(get_db)):
    """加入自选。"""
    # 检查是否已存在
    existing = db.execute(text("""
        SELECT id FROM watchlist
        WHERE ts_code = :ts_code AND status != 'removed'
    """), {"ts_code": req.ts_code}).scalar()

    if existing:
        raise HTTPException(400, f"{req.ts_code} 已在自选股中")

    # 取当前阶段、评分用作"加入时快照"
    snapshot = db.execute(text("""
        SELECT phase, score
        FROM stock_analysis
        WHERE ts_code = :ts_code
        ORDER BY trade_date DESC
        LIMIT 1
    """), {"ts_code": req.ts_code}).first()

    item = Watchlist(
        ts_code=req.ts_code,
        name=req.name,
        sector=req.sector,
        cost_price=req.cost_price,
        shares=req.shares,
        position_pct=req.position_pct,
        status="holding" if req.is_holding else "watching",
        added_at=datetime.now(),
        added_phase=snapshot.phase if snapshot else None,
        added_score=snapshot.score if snapshot else None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "ts_code": item.ts_code,
        "name": item.name,
        "added_at": item.added_at.isoformat(),
    }


@router.delete("/{watch_id}")
async def remove_from_watchlist(watch_id: int, db: Session = Depends(get_db)):
    """移除自选股（软删除）。"""
    item = db.get(Watchlist, watch_id)
    if not item:
        raise HTTPException(404, "自选不存在")
    item.status = "removed"
    item.removed_at = datetime.now()
    db.commit()
    return {"ok": True}


@router.put("/{watch_id}")
async def update_watchlist(
    watch_id: int, req: UpdateWatchRequest, db: Session = Depends(get_db),
):
    """更新自选股。"""
    item = db.get(Watchlist, watch_id)
    if not item:
        raise HTTPException(404, "自选不存在")

    update_data = req.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(item, k, v)
    db.commit()
    return {"ok": True}


@router.get("/changes")
async def watchlist_changes(db: Session = Depends(get_db)):
    """
    自选股状态变化提醒：
    - 阶段从 拉升期 切换到派发期 → 警告
    - 评分大幅下降 → 警告
    - 触发A级机会 → 提示
    """
    # 简化：今天和昨天的对比
    rows = db.execute(text("""
        SELECT
          w.ts_code, w.name,
          a_today.phase AS phase_today,
          a_today.score AS score_today,
          a_today.opportunity_level AS opp_today,
          a_yest.phase AS phase_yesterday,
          a_yest.score AS score_yesterday,
          a_yest.opportunity_level AS opp_yesterday
        FROM watchlist w
        LEFT JOIN stock_analysis a_today
          ON w.ts_code = a_today.ts_code
          AND a_today.trade_date = (SELECT MAX(trade_date) FROM stock_analysis)
        LEFT JOIN stock_analysis a_yest
          ON w.ts_code = a_yest.ts_code
          AND a_yest.trade_date = (
              SELECT MAX(trade_date) FROM stock_analysis
              WHERE trade_date < (SELECT MAX(trade_date) FROM stock_analysis)
          )
        WHERE w.status IN ('watching', 'holding')
    """)).fetchall()

    changes = []
    for r in rows:
        d = dict(r._mapping)
        changed = False
        msgs = []

        if d["phase_today"] and d["phase_yesterday"] and d["phase_today"] != d["phase_yesterday"]:
            changed = True
            msgs.append(f"阶段切换: {d['phase_yesterday']} → {d['phase_today']}")

        if d["score_today"] and d["score_yesterday"]:
            score_diff = d["score_today"] - d["score_yesterday"]
            if abs(score_diff) >= 15:
                changed = True
                msgs.append(f"评分剧变: {d['score_yesterday']} → {d['score_today']} ({score_diff:+d})")

        if d["opp_today"] and d["opp_today"].startswith("A级") and \
           d["opp_yesterday"] and not d["opp_yesterday"].startswith("A级"):
            changed = True
            msgs.append(f"⭐ 升级到 {d['opp_today']}")

        if changed:
            d["change_messages"] = msgs
            changes.append(d)

    return changes
