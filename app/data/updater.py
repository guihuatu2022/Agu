"""
每日增量更新：每天 17:30 / 19:00 / 19:30 三批跑。

关键设计：
- 不指定日期时，自动用最近的交易日（手动触发也能跑出结果）
- 指定日期时，严格检查（避免误传非交易日）
- 失败的接口标记重试
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd

from ..database import session_scope
from ..models import SystemStatus
from . import fetcher, storage

logger = logging.getLogger(__name__)


def _today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def _resolve_date(date_str: Optional[str]) -> tuple[Optional[str], str]:
    """
    解析要使用的日期。
    
    返回 (date_str, info_msg):
      - date_str=None: 跳过任务（非交易日且没历史交易日）
      - date_str=具体日期: 实际要处理的交易日
    """
    if date_str:
        # 用户指定了日期，必须是交易日
        if fetcher.is_trading_day(date_str):
            return date_str, f"使用指定日期 {date_str}"
        return None, f"指定日期 {date_str} 非交易日"

    # 未指定 → 优先用今天，否则最近交易日
    today = _today_str()
    if fetcher.is_trading_day(today):
        return today, f"今天 {today} 是交易日"

    prev = fetcher.get_previous_trading_day(today)
    if prev:
        return prev, f"今天非交易日，自动使用最近交易日 {prev}"
    return None, "找不到任何交易日"


def _record_task(task_type: str, task_date: date,
                 status: str, msg: str = "",
                 api_calls: int = 0, error: Optional[str] = None) -> None:
    """记录任务执行情况到 system_status 表。"""
    try:
        with session_scope() as s:
            task = SystemStatus(
                task_type=task_type,
                task_date=task_date,
                status=status,
                started_at=datetime.now(),
                finished_at=datetime.now(),
                progress_msg=msg[:500],
                api_calls=api_calls,
                error_msg=error,
            )
            s.add(task)
    except Exception as e:
        logger.error(f"记录任务失败: {e}")


def daily_update_first_batch(date_str: Optional[str] = None) -> dict:
    """
    第一批：行情 + 基本面 + 指数 + 复权因子。
    """
    date_str, info = _resolve_date(date_str)
    logger.info(f"[第一批] {info}")

    if date_str is None:
        _record_task("daily_first", date.today(), "skipped", info, 0)
        return {"status": "skipped", "reason": "no_trading_day", "msg": info}

    api_calls = 0
    errors = []
    started = datetime.now()

    # 1. 日线 + 复权因子
    try:
        df_daily = fetcher.fetch_daily_market(date_str)
        api_calls += 1
        df_adj = fetcher.fetch_adj_factor_market(date_str)
        api_calls += 1

        if not df_daily.empty:
            if not df_adj.empty and "adj_factor" in df_adj.columns:
                df_daily = df_daily.merge(
                    df_adj[["ts_code", "trade_date", "adj_factor"]],
                    on=["ts_code", "trade_date"], how="left",
                )
            if "change" in df_daily.columns:
                df_daily["change_amt"] = df_daily["change"]
            with session_scope() as s:
                storage.save_stock_daily(s, df_daily)
            logger.info(f"日线入库: {len(df_daily)} 条")
        else:
            errors.append("daily 返回空")
    except Exception as e:
        logger.exception("日线拉取失败")
        errors.append(f"daily: {e}")

    # 2. 基本面
    try:
        df_basic = fetcher.fetch_daily_basic_market(date_str)
        api_calls += 1
        if not df_basic.empty:
            with session_scope() as s:
                storage.save_stock_basic_daily(s, df_basic)
            logger.info(f"基本面入库: {len(df_basic)} 条")
    except Exception as e:
        logger.exception("基本面拉取失败")
        errors.append(f"daily_basic: {e}")

    # 3. 指数
    for ts_code, name in fetcher.INDEX_LIST:
        try:
            df_idx = fetcher.fetch_index_daily(ts_code, date_str, date_str)
            api_calls += 1
            if not df_idx.empty:
                with session_scope() as s:
                    storage.save_index_daily(s, df_idx)
        except Exception as e:
            errors.append(f"index_{name}: {e}")

    duration = (datetime.now() - started).total_seconds()
    status = "success" if not errors else ("partial" if api_calls > 5 else "failed")
    msg = f"日期={date_str}，API调用={api_calls}，错误={len(errors)}"
    _record_task("daily_first", date.today(), status, msg, api_calls,
                 error="\n".join(errors[:5]) if errors else None)

    return {
        "status": status,
        "date": date_str,
        "api_calls": api_calls,
        "duration_seconds": duration,
        "errors": errors[:10],
    }


def daily_update_second_batch(date_str: Optional[str] = None) -> dict:
    """
    第二批：资金流向。
    """
    date_str, info = _resolve_date(date_str)
    logger.info(f"[第二批] {info}")

    if date_str is None:
        _record_task("daily_second", date.today(), "skipped", info, 0)
        return {"status": "skipped", "reason": "no_trading_day", "msg": info}

    api_calls = 0
    errors = []
    started = datetime.now()

    try:
        df_flow = fetcher.fetch_moneyflow_market(date_str)
        api_calls += 1
        if not df_flow.empty:
            with session_scope() as s:
                storage.save_moneyflow(s, df_flow)
            logger.info(f"资金流入库: {len(df_flow)} 条")
    except Exception as e:
        logger.exception("资金流拉取失败")
        errors.append(f"moneyflow: {e}")

    duration = (datetime.now() - started).total_seconds()
    status = "success" if not errors else "failed"
    _record_task("daily_second", date.today(), status,
                 f"日期={date_str}，API={api_calls}", api_calls,
                 error="\n".join(errors) if errors else None)

    return {
        "status": status,
        "date": date_str,
        "api_calls": api_calls,
        "duration_seconds": duration,
        "errors": errors,
    }


def daily_update_third_batch(date_str: Optional[str] = None) -> dict:
    """
    第三批：分析计算。
    本地计算（不调 API）：
    - 概念板块每日热度
    - 全市场个股阶段+机会等级
    """
    date_str, info = _resolve_date(date_str)
    logger.info(f"[第三批] {info}")

    if date_str is None:
        _record_task("daily_third", date.today(), "skipped", info, 0)
        return {"status": "skipped", "reason": "no_trading_day", "msg": info}

    started = datetime.now()
    end_date = datetime.strptime(date_str, "%Y%m%d").date()

    # 1. 计算概念板块每日热度
    try:
        from . import sector_data
        with session_scope() as s:
            sector_result = sector_data.compute_concept_daily(s, end_date)
        logger.info(f"概念板块热度计算: {sector_result}")
    except Exception as e:
        logger.warning(f"概念板块热度计算失败（不阻断）: {e}")

    # 2. 个股分析
    try:
        from ..core.analyzer import analyze_market_for_date
        result = analyze_market_for_date(date_str)
    except Exception as e:
        logger.exception("分析计算失败")
        _record_task("daily_third", date.today(), "failed",
                     f"分析失败: {e}", 0, error=str(e))
        return {"status": "failed", "error": str(e), "date": date_str}

    duration = (datetime.now() - started).total_seconds()
    msg = f"日期={date_str}，分析={result.get('analyzed_count', 0)} 只"
    _record_task("daily_third", date.today(), "success", msg, 0)

    return {
        "status": "success",
        "date": date_str,
        "duration_seconds": duration,
        "result": result,
    }
