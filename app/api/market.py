"""
大盘 API。
"""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/latest")
async def get_latest_market(db: Session = Depends(get_db)):
    """获取最新的大盘分析。"""
    row = db.execute(text("""
        SELECT * FROM market_analysis
        ORDER BY trade_date DESC
        LIMIT 1
    """)).first()
    if not row:
        return {"error": "暂无大盘分析数据"}

    data = dict(row._mapping)
    # detail_json 反序列化
    if data.get("detail_json"):
        try:
            data["details"] = json.loads(data["detail_json"])
            del data["detail_json"]
        except Exception:
            pass
    return data


@router.get("/by-date/{date_str}")
async def get_market_by_date(date_str: str, db: Session = Depends(get_db)):
    """按日期查询大盘分析。date_str 格式 YYYY-MM-DD"""
    row = db.execute(text("""
        SELECT * FROM market_analysis
        WHERE trade_date = :d
    """), {"d": date_str}).first()
    if not row:
        return {"error": f"无 {date_str} 的大盘数据"}
    data = dict(row._mapping)
    if data.get("detail_json"):
        try:
            data["details"] = json.loads(data["detail_json"])
            del data["detail_json"]
        except Exception:
            pass
    return data
