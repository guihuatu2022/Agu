"""
每日增量更新：每天 17:30 / 19:00 / 19:30 三批跑。

特点：
- 只拉当天数据（5次接口调用搞定）
- 自动判断是否交易日
- 失败的接口标记重试
- 全部完成后触发分析计算
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
    第一批（17:30）：行情 + 基本面 + 指数 + 复权因子。
    """
    date_str = date_str or _today_str()
    api_calls = 0
    errors = []

    # 检查是否交易日
    try:
        if not fetcher.is_trading_day(date_str):
            msg = f"非交易日 {date_str}，跳过"
            logger.info(msg)
            _record_task("daily_first", date.today(), "success", msg, 1)
            return {"status": "skipped", "reason": "non_trading_day", "date": date_str}
        api_calls += 1
    except Exception as e:
        logger.error(f"检查交易日失败: {e}")

    started = datetime.now()

    # 1. 日线
    try:
        df_daily = fetcher.fetch_daily_market(date_str)
        api_calls += 1
        # 复权因子
        df_adj = fetcher.fetch_adj_factor_market(date_str)
        api_calls += 1

        if not df_daily.empty:
            if not df_adj.empty:
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
        logger.exception(f"日线拉取失败")
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
        logger.exception(f"基本面拉取失败")
        errors.append(f"daily_basic: {e}")

    # 3. 指数
    end_date = date_str
    start_date = date_str
    for ts_code, name in fetcher.INDEX_LIST:
        try:
            df_idx = fetcher.fetch_index_daily(ts_code, start_date, end_date)
            api_calls += 1
            if not df_idx.empty:
                with session_scope() as s:
                    storage.save_index_daily(s, df_idx)
        except Exception as e:
            errors.append(f"index_{name}: {e}")

    duration = (datetime.now() - started).total_seconds()
    status = "success" if not errors else ("partial" if api_calls > 5 else "failed")
    msg = f"完成。API调用 {api_calls} 次, 错误 {len(errors)} 个"
    _record_task("daily_first", date.today(), status, msg, api_calls,
                 error="\n".join(errors[:5]) if errors else None)

    return {
        "status": status,
        "date": date_str,
        "api_calls": api_calls,
        "duration_seconds": duration,
        "errors": errors,
    }


def daily_update_second_batch(date_str: Optional[str] = None) -> dict:
    """
    第二批（19:00）：资金流向（晚到的接口）。
    """
    date_str = date_str or _today_str()
    api_calls = 0
    errors = []

    try:
        if not fetcher.is_trading_day(date_str):
            return {"status": "skipped", "reason": "non_trading_day"}
        api_calls += 1
    except Exception as e:
        logger.error(e)

    started = datetime.now()

    try:
        df_flow = fetcher.fetch_moneyflow_market(date_str)
        api_calls += 1
        if not df_flow.empty:
            with session_scope() as s:
                storage.save_moneyflow(s, df_flow)
            logger.info(f"资金流入库: {len(df_flow)} 条")
    except Exception as e:
        logger.exception(f"资金流拉取失败")
        errors.append(f"moneyflow: {e}")

    duration = (datetime.now() - started).total_seconds()
    status = "success" if not errors else "failed"
    _record_task("daily_second", date.today(), status,
                 f"完成。API调用 {api_calls} 次", api_calls,
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
    第三批（19:30）：分析计算 + 报告生成。
    
    本地计算：
    - 计算概念板块每日热度（不调接口）
    - 计算每只股票的阶段、机会等级
    - 生成大盘日报
    """
    date_str = date_str or _today_str()
    started = datetime.now()

    try:
        if not fetcher.is_trading_day(date_str):
            return {"status": "skipped", "reason": "non_trading_day"}
    except Exception:
        pass

    end_date = datetime.strptime(date_str, "%Y%m%d").date()

    # 1. 计算概念板块每日热度
    try:
        from . import sector_data
        from ..database import session_scope
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
        return {"status": "failed", "error": str(e)}

    duration = (datetime.now() - started).total_seconds()
    msg = f"分析完成: {result.get('analyzed_count', 0)} 只股票"
    _record_task("daily_third", date.today(), "success", msg, 0)

    return {
        "status": "success",
        "date": date_str,
        "duration_seconds": duration,
        "result": result,
    }
