"""
概念板块数据：抓取 + 入库 + 每日热度计算。

策略：
1. 概念列表和成分映射变化慢，每周更新一次即可
2. 每日热度（涨跌幅、排名）每天计算一次，不调用接口（用本地股票数据计算）
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import fetcher, storage

logger = logging.getLogger(__name__)


# ============ 概念列表 + 成分股入库 ============

def update_concepts(session: Session) -> dict:
    """
    更新概念板块列表和成分股映射。
    
    建议每周一次（数据变化慢），不需要每天调用。
    """
    api_calls = 0
    failed_concepts = []

    # 1. 拉概念列表
    try:
        df_concepts = fetcher.fetch_concepts()
        api_calls += 1
    except Exception as e:
        logger.error(f"拉取概念列表失败: {e}")
        return {"status": "failed", "msg": str(e)}

    if df_concepts.empty:
        return {"status": "skipped", "msg": "概念接口返回为空（可能权限不足）"}

    # 兼容字段名
    code_col = "code" if "code" in df_concepts.columns else "ts_code"
    name_col = "name" if "name" in df_concepts.columns else "concept_name"

    total_concepts = len(df_concepts)
    success_concepts = 0
    total_members = 0

    # 2. 逐个拉成分
    for _, row in df_concepts.iterrows():
        cc = row[code_col]
        cn = row[name_col]

        try:
            df_members = fetcher.fetch_concept_detail(cc)
            api_calls += 1
        except Exception as e:
            logger.warning(f"概念 {cn}({cc}) 成分拉取失败: {e}")
            failed_concepts.append(cn)
            continue

        if df_members.empty:
            continue

        # 准备入库数据
        member_col = "ts_code" if "ts_code" in df_members.columns else "con_code"
        records = [{
            "concept_code": cc,
            "concept_name": cn,
            "ts_code": str(m).strip(),
            "src": "ts",
            "updated_at": datetime.now(),
        } for m in df_members[member_col].dropna().unique()]

        if records:
            cols = ["concept_code", "concept_name", "ts_code", "src", "updated_at"]
            try:
                _ = storage.upsert_dataframe(
                    session, "concept_member",
                    pd.DataFrame(records),
                    primary_keys=["concept_code", "ts_code"],
                    columns=cols,
                )
                success_concepts += 1
                total_members += len(records)
            except Exception as e:
                logger.warning(f"概念 {cn} 成分入库失败: {e}")
                failed_concepts.append(cn)

    return {
        "status": "success",
        "concepts": success_concepts,
        "total_concepts": total_concepts,
        "members": total_members,
        "failed_count": len(failed_concepts),
        "api_calls": api_calls,
    }


# ============ 概念每日热度计算（本地，不调接口）============

def compute_concept_daily(session: Session, trade_date: date) -> dict:
    """
    计算指定交易日的概念板块热度。
    
    思路：
    1. 对每个概念，用其成分股的等权平均涨跌幅作为板块涨跌幅
    2. 计算 5/10/20 日累计
    3. 排名
    4. 多窗口持续度
    
    完全本地计算，不调用 tushare 接口。
    """
    # 1. 找到所有概念
    concepts = session.execute(text("""
        SELECT DISTINCT concept_code, concept_name
        FROM concept_member
    """)).fetchall()

    if not concepts:
        return {"status": "skipped", "msg": "无概念数据，请先 update_concepts"}

    results = []

    for cc, cn in concepts:
        # 取成员
        members = session.execute(text("""
            SELECT ts_code FROM concept_member WHERE concept_code = :cc
        """), {"cc": cc}).scalars().all()

        if len(members) < 3:
            continue

        # 取成员近 25 天的日线
        codes_placeholder = ", ".join(f":c{i}" for i in range(len(members)))
        params = {f"c{i}": code for i, code in enumerate(members)}
        params["start"] = trade_date - timedelta(days=40)
        params["end"] = trade_date

        rows = session.execute(text(f"""
            SELECT ts_code, trade_date, close
            FROM stock_daily
            WHERE ts_code IN ({codes_placeholder})
              AND trade_date BETWEEN :start AND :end
            ORDER BY ts_code, trade_date
        """), params).fetchall()

        if not rows:
            continue

        df = pd.DataFrame(rows, columns=["ts_code", "trade_date", "close"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["trade_date"] = pd.to_datetime(df["trade_date"])

        # 透视：每只票一列
        pivot = df.pivot(index="trade_date", columns="ts_code", values="close")
        if pivot.empty or len(pivot) < 5:
            continue

        # 等权平均（标准化每只票到 100）
        normalized = pivot.div(pivot.iloc[0]).fillna(method="ffill") * 100
        sector_index = normalized.mean(axis=1)

        if pd.isna(sector_index.iloc[-1]):
            continue

        # 计算各窗口涨跌
        last_v = sector_index.iloc[-1]

        def pct_n(n):
            if len(sector_index) < n + 1:
                return None
            v0 = sector_index.iloc[-(n + 1)]
            if pd.isna(v0) or v0 == 0:
                return None
            return float((last_v - v0) / v0 * 100)

        results.append({
            "concept_code": cc,
            "concept_name": cn,
            "trade_date": trade_date,
            "pct_chg": pct_n(1),
            "pct_chg_5d": pct_n(5),
            "pct_chg_10d": pct_n(10),
            "pct_chg_20d": pct_n(20),
        })

    if not results:
        return {"status": "skipped", "msg": "无任何有效概念数据"}

    df_result = pd.DataFrame(results)

    # 排名
    for col, rank_col in [("pct_chg", "rank_today"), ("pct_chg_5d", "rank_5d"),
                          ("pct_chg_10d", "rank_10d"), ("pct_chg_20d", "rank_20d")]:
        df_result[rank_col] = df_result[col].rank(ascending=False, method="min").astype("Int64")

    # 持续度（在 TOP10 / TOP20 的窗口数）
    def count_persistence(row, rank_cols, threshold):
        return sum(1 for c in rank_cols
                   if pd.notna(row[c]) and row[c] <= threshold)
    rank_cols = ["rank_today", "rank_5d", "rank_10d", "rank_20d"]
    df_result["persistence_top10"] = df_result.apply(
        lambda r: count_persistence(r, rank_cols, 10), axis=1)
    df_result["persistence_top20"] = df_result.apply(
        lambda r: count_persistence(r, rank_cols, 20), axis=1)

    # 强度评级
    def rate_strength(row):
        p = row["persistence_top10"]
        c5 = row["pct_chg_5d"]
        c20 = row["pct_chg_20d"]
        if p >= 4 or (c5 and c5 > 5 and c20 and c20 > 10):
            return "🔥 强势主线"
        elif p >= 3 or (c5 and c5 > 2 and c20 and c20 > 5):
            return "🟢 持续走强"
        elif c5 and c5 > 0 and c20 and c20 > 0:
            return "🟡 温和向上"
        elif c5 and c5 < -3 and c20 and c20 < -5:
            return "🔴 退潮"
        elif c5 and c5 < 0:
            return "⚪ 弱势调整"
        else:
            return "⚪ 震荡"
    df_result["strength_rating"] = df_result.apply(rate_strength, axis=1)

    # 入库
    cols = ["concept_code", "concept_name", "trade_date",
            "pct_chg", "pct_chg_5d", "pct_chg_10d", "pct_chg_20d",
            "rank_today", "rank_5d", "rank_10d", "rank_20d",
            "persistence_top10", "persistence_top20", "strength_rating"]

    saved = storage.upsert_dataframe(
        session, "concept_daily", df_result,
        primary_keys=["concept_code", "trade_date"],
        columns=cols,
    )

    return {
        "status": "success",
        "concept_count": len(results),
        "saved": saved,
    }


# ============ 板块查询助手 ============

def get_top_concepts(
    session: Session, trade_date: date,
    window: str = "today", top_n: int = 5,
) -> list[dict]:
    """
    获取指定窗口的TOP板块。
    window: today / 5d / 10d / 20d
    """
    rank_col = {
        "today": "rank_today",
        "5d": "rank_5d",
        "10d": "rank_10d",
        "20d": "rank_20d",
    }.get(window, "rank_today")

    pct_col = {
        "today": "pct_chg",
        "5d": "pct_chg_5d",
        "10d": "pct_chg_10d",
        "20d": "pct_chg_20d",
    }.get(window, "pct_chg")

    rows = session.execute(text(f"""
        SELECT concept_code, concept_name, {pct_col} AS pct, {rank_col} AS rnk,
               persistence_top10, strength_rating
        FROM concept_daily
        WHERE trade_date = :td AND {rank_col} IS NOT NULL
        ORDER BY {rank_col}
        LIMIT :limit
    """), {"td": trade_date, "limit": top_n}).fetchall()

    return [dict(r._mapping) for r in rows]
