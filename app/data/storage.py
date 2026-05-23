"""
数据库存储层：把 DataFrame 高效写入 MySQL。

要点：
- 用 INSERT ... ON DUPLICATE KEY UPDATE 实现幂等
- 大批量分块写入（每批 1000 行）
- DataFrame 列名要和 ORM 字段对齐
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


CHUNK_SIZE = 1000


def upsert_dataframe(
    session: Session,
    table_name: str,
    df: pd.DataFrame,
    primary_keys: list[str],
    columns: list[str],
    chunk_size: int = CHUNK_SIZE,
) -> int:
    """
    通用 UPSERT：INSERT ... ON DUPLICATE KEY UPDATE
    
    参数：
      session: SQLAlchemy session
      table_name: 表名
      df: 数据
      primary_keys: 主键列名（ON DUPLICATE 时排除这些列）
      columns: 要写入的列（必须包括主键列）
      chunk_size: 分块大小
    
    返回：成功写入的行数
    """
    if df.empty:
        return 0

    df = df[columns].copy()
    # 把 NaN 替换为 None（MySQL 接受 NULL）
    df = df.where(pd.notna(df), None)

    update_cols = [c for c in columns if c not in primary_keys]

    cols_str = ", ".join(f"`{c}`" for c in columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    update_str = ", ".join(f"`{c}`=VALUES(`{c}`)" for c in update_cols)

    sql = (
        f"INSERT INTO `{table_name}` ({cols_str}) "
        f"VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_str}"
    )

    total = 0
    rows = df.to_dict(orient="records")

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        try:
            session.execute(text(sql), chunk)
            session.commit()
            total += len(chunk)
        except Exception as e:
            session.rollback()
            logger.error(f"upsert {table_name} 块{i}~{i+len(chunk)} 失败: {e}")
            raise

    return total


def save_stock_meta(session: Session, df: pd.DataFrame) -> int:
    """保存股票元信息。"""
    if df.empty:
        return 0
    from datetime import datetime
    df = df.copy()
    df["updated_at"] = datetime.now()
    cols = ["ts_code", "symbol", "name", "area", "industry",
            "list_date", "market", "is_st", "delisted", "updated_at"]
    return upsert_dataframe(session, "stock_meta", df, ["ts_code"], cols)


def save_stock_daily(session: Session, df: pd.DataFrame) -> int:
    """保存日线数据。"""
    if df.empty:
        return 0
    cols = [
        "ts_code", "trade_date",
        "open", "high", "low", "close", "pre_close",
        "change_amt", "pct_chg", "vol", "amount",
        "open_qfq", "high_qfq", "low_qfq", "close_qfq",
        "adj_factor", "is_suspended", "is_ex_dividend",
    ]
    # 缺失列补 None
    for c in cols:
        if c not in df.columns:
            if c in ("is_suspended", "is_ex_dividend"):
                df[c] = False
            else:
                df[c] = None
    # tushare 的 change 字段 → change_amt
    if "change" in df.columns and "change_amt" not in df.columns:
        df["change_amt"] = df["change"]
    return upsert_dataframe(session, "stock_daily", df,
                            ["ts_code", "trade_date"], cols)


def save_stock_basic_daily(session: Session, df: pd.DataFrame) -> int:
    """保存每日基本面。"""
    if df.empty:
        return 0
    cols = [
        "ts_code", "trade_date",
        "turnover_rate", "turnover_rate_f", "volume_ratio",
        "pe", "pe_ttm", "pb",
        "total_share", "float_share", "free_share",
        "total_mv", "circ_mv",
    ]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return upsert_dataframe(session, "stock_basic_daily", df,
                            ["ts_code", "trade_date"], cols)


def save_moneyflow(session: Session, df: pd.DataFrame) -> int:
    """保存资金流向。"""
    if df.empty:
        return 0
    cols = [
        "ts_code", "trade_date",
        "buy_lg_amount", "sell_lg_amount",
        "buy_elg_amount", "sell_elg_amount",
        "buy_md_amount", "sell_md_amount",
        "buy_sm_amount", "sell_sm_amount",
        "net_mf_amount", "net_elg_amount",
    ]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return upsert_dataframe(session, "moneyflow_daily", df,
                            ["ts_code", "trade_date"], cols)


def save_index_daily(session: Session, df: pd.DataFrame) -> int:
    """保存指数日线。"""
    if df.empty:
        return 0
    cols = ["ts_code", "trade_date", "open", "high", "low", "close",
            "pct_chg", "vol", "amount"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return upsert_dataframe(session, "index_daily", df,
                            ["ts_code", "trade_date"], cols)


# ============ 查询助手 ============

def get_latest_trade_date(session: Session) -> date | None:
    """从数据库查最新的交易日。"""
    row = session.execute(
        text("SELECT MAX(trade_date) FROM stock_daily")
    ).scalar()
    return row


def get_db_stats(session: Session) -> dict:
    """获取数据库统计信息（设置页用）。"""
    stats = {}
    queries = {
        "stock_count": "SELECT COUNT(*) FROM stock_meta WHERE delisted=0",
        "daily_count": "SELECT COUNT(*) FROM stock_daily",
        "moneyflow_count": "SELECT COUNT(*) FROM moneyflow_daily",
        "index_count": "SELECT COUNT(*) FROM index_daily",
        "concept_count": "SELECT COUNT(DISTINCT concept_code) FROM concept_member",
        "watchlist_count": "SELECT COUNT(*) FROM watchlist WHERE status='watching' OR status='holding'",
    }
    for k, sql in queries.items():
        try:
            stats[k] = int(session.execute(text(sql)).scalar() or 0)
        except Exception:
            stats[k] = 0

    latest = get_latest_trade_date(session)
    stats["latest_date"] = latest.isoformat() if latest else None
    return stats
