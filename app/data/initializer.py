"""
一键初始化数据库：拉取全市场约500个交易日的历史数据。

【断点续传版】
- 已经拉取过的日期自动跳过（查 stock_daily 是否有该日期数据）
- 中途中断后再点"开始初始化"，从上次中断的地方继续
- 限频自动重试不抛异常
- 实时进度推送（SSE）

策略：
1. 按"日期模式"批量拉取（每天1次接口调用）
2. 总接口调用数 ≈ 拉取的交易日数 × 4个接口
3. 频控保证不超限，海外节点 30-50次/分钟
4. 进度通过 SystemStatus 表实时记录
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import AsyncIterator, Optional

import pandas as pd
from sqlalchemy import text

from ..config import settings
from ..database import session_scope, create_all_tables
from ..models import SystemStatus
from . import fetcher, storage

logger = logging.getLogger(__name__)


# 已存在数据的检查粒度
# A股 ≈ 5300 只股票，每日完整数据应该至少有 4000 条记录（部分停牌）
# 如果某天记录数 < 3000，视为"未完整"，需要重拉
EXIST_CHECK_THRESHOLD = 3000


def _get_existing_dates(table_name: str) -> set[date]:
    """查数据库里已经入库的日期集合（用于断点续传）。"""
    try:
        with session_scope() as s:
            sql = text(f"""
                SELECT trade_date, COUNT(*) AS cnt
                FROM {table_name}
                GROUP BY trade_date
                HAVING cnt > :threshold
            """)
            rows = s.execute(sql, {"threshold": EXIST_CHECK_THRESHOLD}).fetchall()
            return {r[0] for r in rows}
    except Exception as e:
        logger.warning(f"查 {table_name} 已有日期失败: {e}")
        return set()


async def initialize_database(skip_existing: bool = True) -> AsyncIterator[dict]:
    """
    一键初始化数据库（断点续传）。
    
    返回异步生成器，每步推送进度事件。
    事件格式: {"step": int, "total_steps": int, "msg": str, "progress": int(0-100)}
    """
    started_at = datetime.now()
    total_steps = 7
    api_calls = 0

    # 创建任务记录
    task_id = None
    try:
        with session_scope() as s:
            task = SystemStatus(
                task_type="init",
                status="running",
                started_at=started_at,
                progress=0,
                progress_msg="开始初始化",
            )
            s.add(task)
            s.flush()
            task_id = task.id
    except Exception as e:
        logger.error(f"创建任务记录失败: {e}")

    def update_status(progress: int, msg: str, status: str = "running"):
        if task_id is None:
            return
        try:
            with session_scope() as s:
                t_obj = s.get(SystemStatus, task_id)
                if t_obj:
                    t_obj.progress = progress
                    t_obj.progress_msg = msg[:500]
                    t_obj.status = status
                    t_obj.api_calls = api_calls
                    if status in ("success", "failed"):
                        t_obj.finished_at = datetime.now()
                        t_obj.duration_seconds = int(
                            (datetime.now() - started_at).total_seconds()
                        )
        except Exception as e:
            logger.error(f"更新任务状态失败: {e}")

    try:
        # ===== Step 1: 建表 =====
        yield {"step": 1, "total_steps": total_steps, "progress": 2,
               "msg": "📋 创建数据库表..."}
        create_all_tables()
        update_status(2, "表创建完成")
        await asyncio.sleep(0.1)

        # ===== Step 2: 拉股票元信息 =====
        yield {"step": 2, "total_steps": total_steps, "progress": 5,
               "msg": "📊 拉取股票元信息..."}
        try:
            df_meta = fetcher.fetch_stock_basic()
            api_calls += 1
            if not df_meta.empty:
                df_meta["market"] = df_meta.apply(
                    lambda r: fetcher.determine_market(r["symbol"], r["ts_code"]),
                    axis=1,
                )
                with session_scope() as s:
                    storage.save_stock_meta(s, df_meta)
                stock_count = len(df_meta)
                yield {"step": 2, "total_steps": total_steps, "progress": 8,
                       "msg": f"✓ 已入库 {stock_count} 只股票"}
            else:
                yield {"step": 2, "total_steps": total_steps, "progress": 8,
                       "msg": "⚠️ 股票元信息为空，跳过"}
        except Exception as e:
            logger.exception("拉股票元信息失败")
            yield {"step": 2, "error": True, "progress": 0,
                   "msg": f"❌ 失败: {e}"}
            update_status(0, f"失败: {e}", "failed")
            return

        # ===== Step 3: 拉指数历史数据 =====
        yield {"step": 3, "total_steps": total_steps, "progress": 10,
               "msg": "📈 拉取指数历史数据..."}
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=settings.history_days * 2)
                      ).strftime("%Y%m%d")

        index_failed = []
        for ts_code, name in fetcher.INDEX_LIST:
            try:
                df_idx = fetcher.fetch_index_daily(ts_code, start_date, end_date)
                api_calls += 1
                if not df_idx.empty:
                    with session_scope() as s:
                        storage.save_index_daily(s, df_idx)
                else:
                    index_failed.append(name)
            except Exception as e:
                logger.warning(f"拉取指数 {name}({ts_code}) 失败: {e}")
                index_failed.append(name)
        msg = f"✓ 指数数据已入库（{len(fetcher.INDEX_LIST) - len(index_failed)}/{len(fetcher.INDEX_LIST)}）"
        if index_failed:
            msg += f"，失败: {','.join(index_failed)}"
        yield {"step": 3, "total_steps": total_steps, "progress": 12, "msg": msg}

        # ===== Step 4: 获取交易日历 =====
        yield {"step": 4, "total_steps": total_steps, "progress": 15,
               "msg": "📅 获取交易日历..."}
        trading_days = fetcher.get_trading_days(start_date, end_date)
        api_calls += 1
        # 仅取最近 history_days 个交易日
        trading_days = trading_days[-settings.history_days:]

        # 断点续传：检查哪些日期已经有数据
        existing_daily = _get_existing_dates("stock_daily") if skip_existing else set()
        existing_basic = _get_existing_dates("stock_basic_daily") if skip_existing else set()
        existing_flow = _get_existing_dates("moneyflow_daily") if skip_existing else set()

        # 转换 trading_days 为 date 对象用于比较
        trading_dates = [datetime.strptime(td, "%Y%m%d").date() for td in trading_days]

        skipped_count = 0
        if existing_daily:
            skipped_count = len([d for d in trading_dates if d in existing_daily])

        msg = f"✓ 共 {len(trading_days)} 个交易日"
        if skipped_count > 0:
            msg += f"，已存在 {skipped_count} 天将跳过（断点续传）"
        yield {"step": 4, "total_steps": total_steps, "progress": 18, "msg": msg}

        # ===== Step 5: 按日期模式批量拉行情数据（4接口并发）=====
        progress_start = 18
        progress_end = 95
        progress_per_day = (progress_end - progress_start) / max(len(trading_days), 1)

        success_days = 0
        failed_days = []
        skipped_days = 0

        # 用线程池并发拉取（每个日期 4 个接口同时跑，多日期可以提前预热）
        executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="tushare")

        def _fetch_one_day(td_date_str: str, td_date_obj: date) -> dict:
            """并发拉一天的所有数据。返回 {daily, adj, basic, flow}"""
            futures = {}
            if td_date_obj not in existing_daily:
                futures["daily"] = executor.submit(fetcher.fetch_daily_market, td_date_str)
                futures["adj"] = executor.submit(fetcher.fetch_adj_factor_market, td_date_str)
            if td_date_obj not in existing_basic:
                futures["basic"] = executor.submit(fetcher.fetch_daily_basic_market, td_date_str)
            if td_date_obj not in existing_flow:
                futures["flow"] = executor.submit(fetcher.fetch_moneyflow_market, td_date_str)

            results = {}
            for k, fut in futures.items():
                try:
                    results[k] = fut.result(timeout=120)
                except Exception as e:
                    results[k] = e
            return results

        try:
            for i, td in enumerate(trading_days):
                day_progress = int(progress_start + (i + 1) * progress_per_day)
                td_date = trading_dates[i]

                # 断点续传：3类数据都已存在则整天跳过
                if (skip_existing and td_date in existing_daily
                        and td_date in existing_basic and td_date in existing_flow):
                    skipped_days += 1
                    if i % 50 == 0:
                        yield {
                            "step": 5, "total_steps": total_steps,
                            "progress": day_progress,
                            "msg": f"⏭ 跳过已有数据 {td} ({i+1}/{len(trading_days)})",
                        }
                    await asyncio.sleep(0)
                    continue

                try:
                    # 并发拉取
                    results = _fetch_one_day(td, td_date)
                    api_calls += len(results)

                    # 入库
                    df_daily = results.get("daily")
                    df_adj = results.get("adj")
                    df_basic = results.get("basic")
                    df_flow = results.get("flow")

                    with session_scope() as s:
                        if isinstance(df_daily, pd.DataFrame) and not df_daily.empty:
                            if isinstance(df_adj, pd.DataFrame) and not df_adj.empty \
                                    and "adj_factor" in df_adj.columns:
                                df_daily = df_daily.merge(
                                    df_adj[["ts_code", "trade_date", "adj_factor"]],
                                    on=["ts_code", "trade_date"], how="left",
                                )
                            if "change" in df_daily.columns:
                                df_daily["change_amt"] = df_daily["change"]
                            storage.save_stock_daily(s, df_daily)

                        if isinstance(df_basic, pd.DataFrame) and not df_basic.empty:
                            storage.save_stock_basic_daily(s, df_basic)

                        if isinstance(df_flow, pd.DataFrame) and not df_flow.empty:
                            storage.save_moneyflow(s, df_flow)

                    success_days += 1

                    # 每5个日期推一次进度
                    if i % 5 == 0 or i == len(trading_days) - 1:
                        yield {
                            "step": 5, "total_steps": total_steps,
                            "progress": day_progress,
                            "msg": (f"📥 进度 {i+1}/{len(trading_days)} ({td}) | "
                                    f"成功 {success_days} 跳过 {skipped_days} 失败 {len(failed_days)} | "
                                    f"API {api_calls} 次"),
                        }
                        update_status(day_progress,
                                      f"日期 {td} ({i+1}/{len(trading_days)})")

                except Exception as e:
                    failed_days.append(td)
                    logger.warning(f"日期 {td} 拉取失败: {e}")
                    yield {
                        "step": 5, "total_steps": total_steps,
                        "progress": day_progress,
                        "msg": f"⚠️ 日期 {td} 失败（已跳过，可重试）: {str(e)[:80]}",
                    }

                await asyncio.sleep(0)
        finally:
            executor.shutdown(wait=False)

        # ===== Step 6: 拉概念板块成分 =====
        yield {"step": 6, "total_steps": total_steps, "progress": 96,
               "msg": "🏷 拉取概念板块（可选，失败不影响主功能）..."}
        try:
            from . import sector_data
            with session_scope() as s:
                concept_result = sector_data.update_concepts(s)
            yield {"step": 6, "total_steps": total_steps, "progress": 98,
                   "msg": f"✓ 概念板块: {concept_result.get('msg', '完成')} "
                          f"({concept_result.get('concepts', 0)} 个概念，"
                          f"{concept_result.get('members', 0)} 条成分)"}
        except Exception as e:
            yield {"step": 6, "total_steps": total_steps, "progress": 98,
                   "msg": f"⚠️ 概念板块拉取失败（不影响主功能）: {e}"}

        # 完成
        msg_done = (f"✅ 初始化完成！"
                    f"成功 {success_days} 跳过 {skipped_days} 失败 {len(failed_days)} | "
                    f"共 API 调用 {api_calls} 次")
        if failed_days:
            msg_done += f"\n失败日期可重新点击初始化继续: {', '.join(failed_days[:10])}"
            if len(failed_days) > 10:
                msg_done += f" 等共 {len(failed_days)} 个"
        yield {"step": 6, "total_steps": total_steps, "progress": 100, "msg": msg_done}
        update_status(100, "初始化完成", "success")

    except Exception as e:
        logger.exception("初始化失败")
        yield {"step": -1, "error": True, "progress": 0,
               "msg": f"❌ 初始化失败: {e}"}
        update_status(0, f"失败: {e}", "failed")
