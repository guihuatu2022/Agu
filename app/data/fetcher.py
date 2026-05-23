"""
数据抓取核心：tushare → MySQL。

关键设计：
1. 全市场拉取一律按"日期模式"（一次返回全市场某天数据），节省接口调用
2. 自动跳过非交易日
3. 计算前复权字段并入库
4. 资金流向分大单/超大单分别存
5. 全部走频控
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import tushare as ts

from ..config import settings
from .rate_limiter import safe_call

logger = logging.getLogger(__name__)


_pro = None


def get_pro():
    """单例方式获取 tushare Pro 接口。"""
    global _pro
    if _pro is None:
        if not settings.tushare_token:
            raise RuntimeError("TUSHARE_TOKEN 未配置！请检查 .env 文件")
        ts.set_token(settings.tushare_token)
        _pro = ts.pro_api()
    return _pro


# ============ 交易日历 ============

def fetch_trade_cal(start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取交易日历。
    返回 DataFrame: cal_date, is_open
    """
    pro = get_pro()
    df = safe_call(
        "trade_cal",
        pro.trade_cal,
        start_date=start_date,
        end_date=end_date,
        exchange="SSE",  # 上交所日历，沪深通用
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df["cal_date"] = pd.to_datetime(df["cal_date"])
    return df.sort_values("cal_date").reset_index(drop=True)


def get_trading_days(start: str, end: str) -> list[str]:
    """获取区间内所有交易日的字符串列表（YYYYMMDD）。"""
    df = fetch_trade_cal(start, end)
    if df.empty:
        return []
    open_days = df[df["is_open"] == 1]
    return [d.strftime("%Y%m%d") for d in open_days["cal_date"]]


def is_trading_day(date_str: str) -> bool:
    """判断指定日期是否为交易日。"""
    df = fetch_trade_cal(date_str, date_str)
    if df.empty:
        return False
    return bool(df.iloc[0]["is_open"] == 1)


def get_previous_trading_day(date_str: str) -> Optional[str]:
    """获取指定日期之前最近的交易日。"""
    base = datetime.strptime(date_str, "%Y%m%d")
    start = (base - timedelta(days=15)).strftime("%Y%m%d")
    days = get_trading_days(start, date_str)
    if not days:
        return None
    # 排除当日
    candidates = [d for d in days if d < date_str]
    return candidates[-1] if candidates else None


# ============ 股票元信息 ============

def fetch_stock_basic() -> pd.DataFrame:
    """
    获取所有上市股票基础信息（一次拉取全市场约5300只）。
    
    返回字段：ts_code, symbol, name, area, industry, market, list_date, is_st, delisted
    """
    pro = get_pro()
    # 上市状态 L=上市
    df_list = safe_call(
        "stock_basic",
        pro.stock_basic,
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,area,industry,market,list_date",
    )
    df_list = df_list if df_list is not None else pd.DataFrame()
    df_list["delisted"] = False
    df_list["is_st"] = df_list["name"].str.contains("ST", na=False)
    df_list["list_date"] = pd.to_datetime(df_list["list_date"], errors="coerce").dt.date

    return df_list


# ============ 单日全市场行情 ============

def fetch_daily_market(trade_date: str) -> pd.DataFrame:
    """
    一次拉取某交易日全市场所有股票的日线。
    注意：tushare 的 daily 接口支持 trade_date 模式，1次调用搞定全市场。
    """
    pro = get_pro()
    df = safe_call(
        "daily",
        pro.daily,
        trade_date=trade_date,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


def fetch_daily_basic_market(trade_date: str) -> pd.DataFrame:
    """单日全市场每日基本面（市值、换手等）。"""
    pro = get_pro()
    df = safe_call(
        "daily_basic",
        pro.daily_basic,
        trade_date=trade_date,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


def fetch_moneyflow_market(trade_date: str) -> pd.DataFrame:
    """单日全市场资金流向（大单/超大单）。"""
    pro = get_pro()
    df = safe_call(
        "moneyflow",
        pro.moneyflow,
        trade_date=trade_date,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    # 计算主力净额（大+超大）
    if all(c in df.columns for c in ["buy_lg_amount", "buy_elg_amount", "sell_lg_amount", "sell_elg_amount"]):
        df["net_mf_amount"] = (
            df["buy_lg_amount"].fillna(0) + df["buy_elg_amount"].fillna(0)
            - df["sell_lg_amount"].fillna(0) - df["sell_elg_amount"].fillna(0)
        )
        df["net_elg_amount"] = (
            df["buy_elg_amount"].fillna(0) - df["sell_elg_amount"].fillna(0)
        )
    return df


def fetch_adj_factor_market(trade_date: str) -> pd.DataFrame:
    """单日全市场复权因子。"""
    pro = get_pro()
    df = safe_call(
        "adj_factor",
        pro.adj_factor,
        trade_date=trade_date,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


# ============ 单只股票多日数据（首次建库时按股票循环用，但优先按日期模式）============

def fetch_daily_stock(ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """单只股票指定区间的日线（备用，首选按日期模式）。"""
    pro = get_pro()
    df = safe_call(
        "daily",
        pro.daily,
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df.sort_values("trade_date").reset_index(drop=True)


# ============ 指数 ============

# 我们关注的核心指数
INDEX_LIST = [
    ("000001.SH", "上证综指"),
    ("399001.SZ", "深证成指"),
    ("000016.SH", "上证50"),
    ("000300.SH", "沪深300"),
    ("000905.SH", "中证500"),
    ("000852.SH", "中证1000"),
    ("932000.CSI", "中证2000"),
    ("399006.SZ", "创业板指"),
    ("399673.SZ", "创业板50"),
    ("000688.SH", "科创50"),
]


def fetch_index_daily(ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """单个指数指定区间的日线。"""
    pro = get_pro()
    df = safe_call(
        "index_daily",
        pro.index_daily,
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df.sort_values("trade_date").reset_index(drop=True)


# ============ 概念板块 ============

def fetch_concepts() -> pd.DataFrame:
    """
    获取所有概念板块列表。
    某些 tushare 版本字段名为 ts_code, name；统一处理。
    """
    pro = get_pro()
    try:
        df = safe_call("concept", pro.concept, src="ts")
    except Exception as e:
        logger.warning(f"获取概念板块列表失败: {e}")
        return pd.DataFrame()
    return df if df is not None else pd.DataFrame()


def fetch_concept_detail(concept_code: str) -> pd.DataFrame:
    """获取某个概念板块的成分股。"""
    pro = get_pro()
    try:
        df = safe_call(
            "concept_detail",
            pro.concept_detail,
            id=concept_code,
        )
    except Exception as e:
        logger.warning(f"获取概念{concept_code}成分失败: {e}")
        return pd.DataFrame()
    return df if df is not None else pd.DataFrame()


# ============ 工具：前复权计算 ============

def apply_qfq(daily_df: pd.DataFrame, adj_df: pd.DataFrame) -> pd.DataFrame:
    """
    给日线数据加上前复权字段（close_qfq 等）。
    
    输入：
      daily_df: 必须有 ts_code, trade_date, open, high, low, close 列
      adj_df: 必须有 ts_code, trade_date, adj_factor 列
    
    返回：原 DataFrame + open_qfq, high_qfq, low_qfq, close_qfq, adj_factor 列
    """
    if daily_df.empty or adj_df.empty:
        out = daily_df.copy()
        out["adj_factor"] = None
        for c in ["open_qfq", "high_qfq", "low_qfq", "close_qfq"]:
            out[c] = out.get(c.replace("_qfq", ""))
        return out

    df = daily_df.merge(adj_df[["ts_code", "trade_date", "adj_factor"]],
                        on=["ts_code", "trade_date"], how="left")

    # 前复权：所有价格 * 当日因子 / 最新因子
    # 在 init/update 入库时，按"截止当前最新日期"计算前复权
    # 这里使用每只票自身的最新因子作为基准
    if "adj_factor" in df.columns:
        df["adj_factor"] = df["adj_factor"].astype(float)
        # 按 ts_code 分组，每组最大日期的因子作为基准
        latest_factor = df.sort_values("trade_date").groupby("ts_code")["adj_factor"].last()
        df = df.set_index("ts_code")
        df["latest_factor"] = latest_factor
        df = df.reset_index()

        for col in ["open", "high", "low", "close"]:
            qfq_col = f"{col}_qfq"
            df[qfq_col] = df[col] * df["adj_factor"] / df["latest_factor"]

        df = df.drop(columns=["latest_factor"])
    else:
        for c in ["open_qfq", "high_qfq", "low_qfq", "close_qfq"]:
            df[c] = df[c.replace("_qfq", "")]

    return df


def determine_market(symbol: str, ts_code: str) -> str:
    """根据代码判断市场类型。"""
    if ts_code.endswith(".BJ"):
        return "北交所"
    if symbol.startswith("688") or symbol.startswith("689"):
        return "科创板"
    if symbol.startswith("3"):
        return "创业板"
    if symbol.startswith("0") or symbol.startswith("6"):
        return "主板"
    return "其他"
