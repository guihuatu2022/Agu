"""
管理 API：数据库初始化、状态查询、手动触发更新等。
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db, test_connection
from ..data.initializer import initialize_database
from ..data.storage import get_db_stats
from ..data import updater

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    """健康检查 + DB状态。"""
    db_ok, db_msg = test_connection()
    stats = {}
    if db_ok:
        try:
            stats = get_db_stats(db)
        except Exception as e:
            stats = {"error": str(e)}
    return {
        "ok": True,
        "database": {"ok": db_ok, "info": db_msg},
        "stats": stats,
    }


@router.get("/stats")
async def db_stats(db: Session = Depends(get_db)):
    """数据库统计信息。"""
    try:
        stats = get_db_stats(db)
        return stats
    except Exception as e:
        return {"error": str(e)}


@router.post("/init")
async def trigger_init():
    """
    一键初始化数据库 - 流式响应。
    返回 SSE（Server-Sent Events）流，前端实时显示进度。
    """
    async def event_stream():
        try:
            async for event in initialize_database():
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': True, 'msg': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/update/first")
async def trigger_first_batch():
    """手动触发第一批更新。"""
    return updater.daily_update_first_batch()


@router.post("/update/second")
async def trigger_second_batch():
    """手动触发第二批更新。"""
    return updater.daily_update_second_batch()


@router.post("/update/third")
async def trigger_third_batch():
    """手动触发第三批更新（分析计算）。"""
    return updater.daily_update_third_batch()


@router.get("/tasks/recent")
async def recent_tasks(db: Session = Depends(get_db), limit: int = 20):
    """最近的任务执行记录。"""
    rows = db.execute(text("""
        SELECT id, task_type, task_date, status,
               started_at, finished_at, duration_seconds,
               progress, progress_msg, api_calls, error_msg
        FROM system_status
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()
    return [dict(r._mapping) for r in rows]
