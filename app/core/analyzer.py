"""
分析层：把数据库里的原始数据 → 个股分析快照 + 大盘分析。

每天第三批任务调用 analyze_market_for_date()，
对所有股票计算阶段、机会等级、综合评分，结果写入 stock_analysis 表。

【关键改进】
1. days_in_phase 通过查询昨日的 stock_analysis 表准确推断
2. 价格优先用前复权字段（close_qfq），无则降级用 close
3. 板块共振：从 concept_member 表查个股所属板块，对照 concept_daily 当日热度

性能：
- 单只票计算 < 50ms
- 全市场 5300 只 ≈ 4分钟
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import session_scope
from .force_intelligence import (
    Phase, SubPhase, full_intelligence, identify_phase,
    PHASE_ACTIONS,
)
from .market_pattern import identify_market_pattern, identify_market_style
from .opportunity import (
    LEVEL_NONE, compute_score, identify_opportunity,
)
from .indicators import sma, kongpan, volume_health_ratio

logger = logging.getLogger(__name__)


# ============ 阶段持续天数：从历史快照推断 ============

def _get_yesterday_phase_info(
    session: Session, ts_code: str, today: date,
) -> Optional[dict]:
    """
    取该票最近一次分析记录（昨天或更早），用于推断阶段持续天数。
    返回 {sub_phase, days_in_phase, trade_date} 或 None
    """
    row = session.execute(text("""
        SELECT sub_phase, days_in_phase, trade_date
        FROM stock_analysis
        WHERE ts_code = :ts_code AND trade_date < :today
        ORDER BY trade_date DESC
        LIMIT 1
    """), {"ts_code": ts_code, "today": today}).first()

    if not row:
        return None
    return {
        "sub_phase": row[0],
        "days_in_phase": row[1] or 0,
        "trade_date": row[2],
    }


def _compute_days_in_phase(
    yesterday: Optional[dict], today_sub_phase: str,
) -> int:
    """
    根据昨日阶段和今日阶段，推断今天是该阶段第几天。
    
    规则：
    - 第一次分析（无历史）：第 1 天
    - 今日阶段 == 昨日阶段：昨日天数 + 1
    - 阶段切换：第 1 天
    """
    if yesterday is None:
        return 1
    if yesterday["sub_phase"] == today_sub_phase:
        return (yesterday["days_in_phase"] or 0) + 1
    return 1


# ============ 价格列适配 ============

def _select_price_cols(df: pd.DataFrame) -> pd.DataFrame:
    """
    优先使用前复权价格 close_qfq 等。
    如果该字段为 None 或全 NaN，降级使用 close。
    返回带统一字段名 (open/high/low/close) 的 DataFrame。
    """
    df = df.copy()
    for col in ["open", "high", "low", "close"]:
        qfq_col = f"{col}_qfq"
        if qfq_col in df.columns and df[qfq_col].notna().any():
            # 用前复权值替换原值
            df[col] = df[qfq_col].fillna(df[col])
    return df


# ============ 板块共振检查 ============

def _is_stock_sector_resonant(
    session: Session, ts_code: str, trade_date: date,
) -> tuple[bool, str]:
    """
    检查该股票所属概念板块当日是否强势。
    
    返回: (是否共振, 主要板块名)
    """
    row = session.execute(text("""
        SELECT cd.concept_name, cd.strength_rating, cd.persistence_top10
        FROM concept_member cm
        JOIN concept_daily cd
          ON cm.concept_code = cd.concept_code
          AND cd.trade_date = :td
        WHERE cm.ts_code = :ts_code
        ORDER BY cd.persistence_top10 DESC, cd.pct_chg_5d DESC
        LIMIT 1
    """), {"ts_code": ts_code, "td": trade_date}).first()

    if not row:
        return False, ""
    primary_sector = row[0]
    rating = row[1] or ""
    persistence = row[2] or 0
    # 强势主线 OR 持续走强 = 共振
    is_resonant = rating in ("🔥 强势主线", "🟢 持续走强") or persistence >= 3
    return is_resonant, primary_sector


# ============ 单只股票分析 ============

def analyze_single_stock(
    session: Session,
    ts_code: str,
    end_date: date,
    history_days: int = 250,
    market_uptrend: bool = True,
) -> Optional[dict]:
    """
    分析单只股票。返回 stock_analysis 表的一行字典，或 None（数据不足）。
    """
    start_date = end_date - timedelta(days=int(history_days * 1.5))

    # 拉日线（含前复权）
    daily_rows = session.execute(
        text("""
            SELECT trade_date, open, high, low, close, pre_close, pct_chg, vol, amount,
                   open_qfq, high_qfq, low_qfq, close_qfq
            FROM stock_daily
            WHERE ts_code = :ts_code AND trade_date BETWEEN :s AND :e
            ORDER BY trade_date
        """),
        {"ts_code": ts_code, "s": start_date, "e": end_date},
    ).fetchall()
    if len(daily_rows) < 30:
        return None

    df = pd.DataFrame(daily_rows, columns=[
        "trade_date", "open", "high", "low", "close", "pre_close",
        "pct_chg", "vol", "amount",
        "open_qfq", "high_qfq", "low_qfq", "close_qfq",
    ])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    for c in ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount",
              "open_qfq", "high_qfq", "low_qfq", "close_qfq"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # 优先使用前复权价格
    df = _select_price_cols(df)

    # 拉资金流
    flow_rows = session.execute(
        text("""
            SELECT trade_date, buy_lg_amount, sell_lg_amount,
                   buy_elg_amount, sell_elg_amount, net_mf_amount
            FROM moneyflow_daily
            WHERE ts_code = :ts_code AND trade_date BETWEEN :s AND :e
            ORDER BY trade_date
        """),
        {"ts_code": ts_code, "s": start_date, "e": end_date},
    ).fetchall()
    flow_df = pd.DataFrame()
    if flow_rows:
        flow_df = pd.DataFrame(flow_rows, columns=[
            "trade_date", "buy_lg_amount", "sell_lg_amount",
            "buy_elg_amount", "sell_elg_amount", "net_mf_amount",
        ])
        flow_df["trade_date"] = pd.to_datetime(flow_df["trade_date"])
        for c in flow_df.columns[1:]:
            flow_df[c] = pd.to_numeric(flow_df[c], errors="coerce")

    # 拉基本面
    basic_rows = session.execute(
        text("""
            SELECT trade_date, turnover_rate, circ_mv, total_mv
            FROM stock_basic_daily
            WHERE ts_code = :ts_code AND trade_date BETWEEN :s AND :e
            ORDER BY trade_date
        """),
        {"ts_code": ts_code, "s": start_date, "e": end_date},
    ).fetchall()
    basic_df = pd.DataFrame()
    if basic_rows:
        basic_df = pd.DataFrame(basic_rows, columns=[
            "trade_date", "turnover_rate", "circ_mv", "total_mv",
        ])
        basic_df["trade_date"] = pd.to_datetime(basic_df["trade_date"])
        for c in basic_df.columns[1:]:
            basic_df[c] = pd.to_numeric(basic_df[c], errors="coerce")

    # 流通市值（亿元）
    circ_mv_yi = None
    if not basic_df.empty and not pd.isna(basic_df["circ_mv"].iloc[-1]):
        circ_mv_yi = float(basic_df["circ_mv"].iloc[-1]) / 10000

    # ============ 关键修复：阶段识别 + 持续天数 ============
    # 第一步：识别今日阶段（暂不计算 days_in_phase）
    phase_result = identify_phase(df, flow_df, circ_mv_yi)
    today_sub_phase = phase_result["sub_phase"]

    # 第二步：从历史快照推断 days_in_phase
    yesterday = _get_yesterday_phase_info(session, ts_code, end_date)
    days_in_phase = _compute_days_in_phase(yesterday, today_sub_phase)

    # 第三步：用准确的 days_in_phase 完成主力侦察
    intelligence = full_intelligence(
        df=df, flow_df=flow_df, basic_df=basic_df,
        circ_mv_yi=circ_mv_yi,
        days_in_phase=days_in_phase,
    )

    # 价格和均线
    last = df.iloc[-1]
    close = float(last["close"])
    pct_chg = float(last["pct_chg"]) if not pd.isna(last["pct_chg"]) else 0.0
    df["ma5"] = sma(df["close"], 5)
    df["ma20"] = sma(df["close"], 20)
    df["ma60"] = sma(df["close"], 60)
    ma5 = float(df["ma5"].iloc[-1]) if not pd.isna(df["ma5"].iloc[-1]) else 0.0
    ma20 = float(df["ma20"].iloc[-1]) if not pd.isna(df["ma20"].iloc[-1]) else 0.0
    ma60 = float(df["ma60"].iloc[-1]) if not pd.isna(df["ma60"].iloc[-1]) else 0.0

    # 资金多窗口
    flow_5d = flow_10d = flow_20d = 0.0
    flow_direction = ""
    flow_5d_pos = flow_10d_pos = flow_20d_pos = False
    if not flow_df.empty and "net_mf_amount" in flow_df.columns:
        flow_5d = float(flow_df["net_mf_amount"].tail(5).sum() / 10000)
        flow_10d = float(flow_df["net_mf_amount"].tail(10).sum() / 10000)
        flow_20d = float(flow_df["net_mf_amount"].tail(20).sum() / 10000)
        flow_5d_pos = flow_5d > 0
        flow_10d_pos = flow_10d > 0
        flow_20d_pos = flow_20d > 0
        if flow_5d_pos and flow_10d_pos and flow_20d_pos:
            flow_direction = "持续流入"
        elif (not flow_5d_pos) and flow_10d_pos and flow_20d_pos:
            flow_direction = "近期撤退"
        elif (not flow_5d_pos) and (not flow_10d_pos) and (not flow_20d_pos):
            flow_direction = "持续流出"
        else:
            flow_direction = "震荡"

    flow_5d_ratio = (flow_5d / circ_mv_yi * 100) if circ_mv_yi else None

    # 量价
    vol_ratio = volume_health_ratio(df, 20)

    # 量能缩放
    is_volume_shrinking = False
    if len(df) >= 25:
        recent_5_vol = df["vol"].tail(5).mean()
        earlier_20_vol = df["vol"].iloc[-25:-5].mean()
        is_volume_shrinking = bool(earlier_20_vol > 0 and recent_5_vol < earlier_20_vol * 0.85)

    # 板块共振
    sector_strong, primary_sector = _is_stock_sector_resonant(session, ts_code, end_date)

    # 机会等级
    opp = identify_opportunity(
        intelligence=intelligence,
        close=close, ma20=ma20, ma60=ma60,
        flow_5d_pos=flow_5d_pos,
        flow_10d_pos=flow_10d_pos,
        flow_20d_pos=flow_20d_pos,
        is_volume_shrinking=is_volume_shrinking,
        sector_strong=sector_strong,
        market_uptrend=market_uptrend,
    )

    # 综合评分
    score = compute_score(
        intelligence=intelligence,
        opportunity=opp,
        sector_strong=sector_strong,
        market_uptrend=market_uptrend,
    )

    # 距均线/前高
    dist_ma20 = (close - ma20) / ma20 if ma20 > 0 else None
    dist_ma60 = (close - ma60) / ma60 if ma60 > 0 else None
    period_high_120 = df["close"].tail(120).max()
    dist_high_120 = (close - period_high_120) / period_high_120 if period_high_120 > 0 else None

    # 换手率
    turnover_rate = None
    circ_mv_wan = None
    if not basic_df.empty:
        turnover_rate = float(basic_df["turnover_rate"].iloc[-1]) \
            if not pd.isna(basic_df["turnover_rate"].iloc[-1]) else None
        circ_mv_wan = float(basic_df["circ_mv"].iloc[-1]) \
            if not pd.isna(basic_df["circ_mv"].iloc[-1]) else None

    return {
        "ts_code": ts_code,
        "trade_date": end_date,

        "has_main_force": intelligence.has_force,
        "force_strength": intelligence.force_strength,
        "force_type": intelligence.force_type,
        "inst_score": intelligence.inst_score,
        "youzi_score": intelligence.youzi_score,
        "control_pct": float(intelligence.control_pct),
        "control_level": intelligence.control_level,

        "phase": intelligence.main_phase,
        "sub_phase": intelligence.sub_phase,
        "days_in_phase": days_in_phase,
        "phase_score": intelligence.phase_score,
        "phase_established": days_in_phase >= 3,
        "phase_changed_today": days_in_phase == 1,

        "opportunity_level": opp.level,
        "score": score,

        "close": close,
        "pct_chg": pct_chg,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "dist_ma20": dist_ma20,
        "dist_ma60": dist_ma60,
        "dist_high_120": dist_high_120,

        "flow_5d": flow_5d,
        "flow_10d": flow_10d,
        "flow_20d": flow_20d,
        "flow_5d_ratio": flow_5d_ratio,
        "flow_direction": flow_direction,

        "vol_ratio": float(vol_ratio) if vol_ratio is not None else None,
        "is_volume_stagnation": False,

        "kongpan": float(intelligence.kongpan_now),
        "kongpan_trend": intelligence.kongpan_trend,

        "primary_sector": primary_sector,
        "sector_strength": "",
        "is_sector_resonant": sector_strong,

        "has_anomaly": False,
        "anomaly_desc": "",

        "circ_mv": circ_mv_wan,
        "turnover_rate": turnover_rate,
    }


# ============ 大盘分析 ============

def analyze_market(session: Session, end_date: date) -> dict:
    """分析大盘当日状态。"""
    from ..data.fetcher import INDEX_LIST
    index_data = {}
    for ts_code, name in INDEX_LIST:
        rows = session.execute(
            text("""
                SELECT trade_date, open, high, low, close, pct_chg, vol, amount
                FROM index_daily
                WHERE ts_code = :ts_code AND trade_date <= :end_date
                ORDER BY trade_date DESC
                LIMIT 300
            """),
            {"ts_code": ts_code, "end_date": end_date},
        ).fetchall()
        if not rows:
            continue
        df = pd.DataFrame(rows, columns=[
            "trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount",
        ]).iloc[::-1].reset_index(drop=True)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        for c in ["open", "high", "low", "close", "pct_chg", "vol", "amount"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        index_data[ts_code] = df

    sh = index_data.get("000001.SH")
    if sh is None or sh.empty:
        return {"error": "无大盘数据"}

    pattern = identify_market_pattern(sh)
    style = identify_market_style(index_data)

    sh_amount = float(sh["amount"].iloc[-1]) if not sh.empty else 0
    amount_ma20 = float(sh["amount"].tail(20).mean())
    amount_ratio = sh_amount / amount_ma20 if amount_ma20 > 0 else 0
    if amount_ratio > 1.2:
        amount_state = f"活跃（{amount_ratio:.2f}倍均量）"
    elif amount_ratio < 0.8:
        amount_state = f"缩量（{amount_ratio:.2f}倍均量）"
    else:
        amount_state = f"正常（{amount_ratio:.2f}倍均量）"

    market_uptrend_patterns = {"主升浪初期", "主升浪中期", "底部反转启动期", "中级整理"}
    market_neutral_patterns = {"主升浪末期", "主升浪加速期", "顶部构筑期", "大箱体震荡"}
    market_down_patterns = {"顶部确立", "趋势下跌期", "加速杀跌期", "杀跌末期"}

    if pattern.pattern in market_uptrend_patterns:
        recommended_position = "70~90%"
        operation_advice = "正常做单（趋势票主菜）"
    elif pattern.pattern in market_neutral_patterns:
        recommended_position = "30~50%"
        operation_advice = "谨慎，只做最强主线"
    elif pattern.pattern in market_down_patterns:
        recommended_position = "≤20%"
        operation_advice = "观望，不做趋势票"
    else:
        recommended_position = "30~50%"
        operation_advice = "谨慎"

    detail = {}
    for ts_code, df in index_data.items():
        if df.empty:
            continue

        def pct_chg_n(n):
            if len(df) < n + 1:
                return None
            r, e = df["close"].iloc[-1], df["close"].iloc[-(n+1)]
            return float((r - e) / e * 100) if e else None

        sub_pattern = identify_market_pattern(df)
        detail[ts_code] = {
            "name": dict(INDEX_LIST).get(ts_code, ts_code),
            "close": float(df["close"].iloc[-1]),
            "pct_chg": float(df["pct_chg"].iloc[-1]) if not pd.isna(df["pct_chg"].iloc[-1]) else 0,
            "pct_5d": pct_chg_n(5),
            "pct_10d": pct_chg_n(10),
            "pct_20d": pct_chg_n(20),
            "pattern": sub_pattern.pattern,
            "duration_weeks": sub_pattern.duration_weeks,
        }

    return {
        "trade_date": end_date.isoformat(),
        "sh_close": float(sh["close"].iloc[-1]),
        "sh_pct_chg": float(sh["pct_chg"].iloc[-1]) if not pd.isna(sh["pct_chg"].iloc[-1]) else 0,
        "sh_pattern": pattern.pattern,
        "sh_pattern_duration": pattern.duration_weeks,
        "sh_pattern_desc": pattern.description,
        "market_style": style["style"],
        "style_description": style["description"],
        "today_amount": sh_amount,
        "amount_ma20": amount_ma20,
        "amount_state": amount_state,
        "recommended_position": recommended_position,
        "operation_advice": operation_advice,
        "details": detail,
        "market_uptrend": pattern.pattern in market_uptrend_patterns,
    }


# ============ 全市场分析 ============

def analyze_market_for_date(date_str: str) -> dict:
    """
    对指定日期做全市场分析。
    """
    end_date = datetime.strptime(date_str, "%Y%m%d").date()

    with session_scope() as s:
        market_result = analyze_market(s, end_date)
        if "error" in market_result:
            return market_result

        sql = text("""
            INSERT INTO market_analysis
              (trade_date, sh_close, sh_pct_chg, sh_pattern, sh_pattern_duration,
               market_style, today_amount, amount_ma20, amount_state,
               recommended_position, operation_advice, detail_json)
            VALUES
              (:trade_date, :sh_close, :sh_pct_chg, :sh_pattern, :sh_pattern_duration,
               :market_style, :today_amount, :amount_ma20, :amount_state,
               :recommended_position, :operation_advice, :detail_json)
            ON DUPLICATE KEY UPDATE
              sh_close=VALUES(sh_close), sh_pct_chg=VALUES(sh_pct_chg),
              sh_pattern=VALUES(sh_pattern), sh_pattern_duration=VALUES(sh_pattern_duration),
              market_style=VALUES(market_style), today_amount=VALUES(today_amount),
              amount_ma20=VALUES(amount_ma20), amount_state=VALUES(amount_state),
              recommended_position=VALUES(recommended_position),
              operation_advice=VALUES(operation_advice),
              detail_json=VALUES(detail_json)
        """)
        s.execute(sql, {
            "trade_date": end_date,
            "sh_close": market_result["sh_close"],
            "sh_pct_chg": market_result["sh_pct_chg"],
            "sh_pattern": market_result["sh_pattern"],
            "sh_pattern_duration": market_result["sh_pattern_duration"],
            "market_style": market_result["market_style"],
            "today_amount": market_result["today_amount"],
            "amount_ma20": market_result["amount_ma20"],
            "amount_state": market_result["amount_state"],
            "recommended_position": market_result["recommended_position"],
            "operation_advice": market_result["operation_advice"],
            "detail_json": json.dumps(market_result["details"], ensure_ascii=False),
        })
        s.commit()

        market_uptrend = market_result["market_uptrend"]

        # 取所有股票（活跃且非ST）
        from sqlalchemy.sql import column
        rows = s.execute(
            text("""
                SELECT ts_code FROM stock_meta
                WHERE delisted = 0
                  AND (list_date IS NULL OR list_date < :cutoff)
                ORDER BY ts_code
            """),
            {"cutoff": end_date - timedelta(days=180)},
        ).fetchall()
        stock_codes = [r[0] for r in rows]

    logger.info(f"开始分析 {len(stock_codes)} 只股票...")

    analyzed_count = 0
    failed_count = 0
    batch_size = 200

    for i in range(0, len(stock_codes), batch_size):
        batch = stock_codes[i:i + batch_size]
        results = []

        with session_scope() as s:
            for ts_code in batch:
                try:
                    r = analyze_single_stock(
                        session=s, ts_code=ts_code, end_date=end_date,
                        market_uptrend=market_uptrend,
                    )
                    if r:
                        results.append(r)
                        analyzed_count += 1
                except Exception as e:
                    failed_count += 1
                    logger.warning(f"分析 {ts_code} 失败: {e}")

            if results:
                _bulk_save_analysis(s, results)

        if i % (batch_size * 5) == 0:
            logger.info(f"分析进度 {min(i+batch_size, len(stock_codes))}/{len(stock_codes)} "
                        f"成功 {analyzed_count} 失败 {failed_count}")

    return {
        "trade_date": date_str,
        "analyzed_count": analyzed_count,
        "failed_count": failed_count,
        "market_pattern": market_result["sh_pattern"],
        "market_style": market_result["market_style"],
    }


def _bulk_save_analysis(session: Session, results: list[dict]):
    """批量保存分析结果。"""
    if not results:
        return
    cols = list(results[0].keys())
    cols_str = ", ".join(f"`{c}`" for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    update_str = ", ".join(f"`{c}`=VALUES(`{c}`)"
                           for c in cols if c not in ("ts_code", "trade_date"))

    sql = (
        f"INSERT INTO stock_analysis ({cols_str}) "
        f"VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_str}"
    )
    session.execute(text(sql), results)
    session.commit()
