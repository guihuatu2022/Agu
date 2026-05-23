"""
SQLAlchemy ORM 模型 —— 12张表。

设计原则：
1. 所有表使用 utf8mb4 字符集（兼容MySQL 5.7的真UTF-8）
2. 主键尽量是复合主键（ts_code + trade_date）
3. 关键查询字段都建索引
4. 时间字段用 server_default，让 MySQL 自己管理默认值（兼容严格模式）
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, DECIMAL, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# MySQL 5.7 严格模式下，时间字段必须用 server_default 而不是 Python 的 default
_NOW = text("CURRENT_TIMESTAMP")
_NOW_UPDATE = text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")


# ============ 1. 股票元信息 ============

class StockMeta(Base):
    __tablename__ = "stock_meta"
    __table_args__ = (
        Index("idx_market", "market"),
        Index("idx_industry", "industry"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(50))
    area: Mapped[Optional[str]] = mapped_column(String(20))
    industry: Mapped[Optional[str]] = mapped_column(String(50))
    list_date: Mapped[Optional[date]] = mapped_column(Date)
    market: Mapped[Optional[str]] = mapped_column(String(20))
    is_st: Mapped[bool] = mapped_column(Boolean, default=False)
    delisted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=_NOW_UPDATE, nullable=True
    )


# ============ 2. 日线行情 ============

class StockDaily(Base):
    __tablename__ = "stock_daily"
    __table_args__ = (
        Index("idx_date", "trade_date"),
        Index("idx_code_date", "ts_code", "trade_date"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    open: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    high: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    low: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    close: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    pre_close: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    change_amt: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    vol: Mapped[Optional[int]] = mapped_column(BigInteger)
    amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 3))

    open_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    high_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    low_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    close_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))

    adj_factor: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 6))
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    is_ex_dividend: Mapped[bool] = mapped_column(Boolean, default=False)


# ============ 3. 每日基本面 ============

class StockBasicDaily(Base):
    __tablename__ = "stock_basic_daily"
    __table_args__ = (
        Index("idx_basic_date", "trade_date"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    turnover_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    turnover_rate_f: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    volume_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    pe: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 4))
    pe_ttm: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 4))
    pb: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 4))
    total_share: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    float_share: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    free_share: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    total_mv: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    circ_mv: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))


# ============ 4. 资金流向 ============

class MoneyflowDaily(Base):
    __tablename__ = "moneyflow_daily"
    __table_args__ = (
        Index("idx_flow_date", "trade_date"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    buy_lg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    sell_lg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    buy_elg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    sell_elg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    buy_md_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    sell_md_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    buy_sm_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    sell_sm_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))

    net_mf_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    net_elg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))


# ============ 5. 指数日线 ============

class IndexDaily(Base):
    __tablename__ = "index_daily"
    __table_args__ = (
        Index("idx_index_date", "trade_date"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4))
    high: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4))
    low: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4))
    close: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4))
    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    vol: Mapped[Optional[int]] = mapped_column(BigInteger)
    amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))


# ============ 6. 概念板块成员 ============

class ConceptMember(Base):
    __tablename__ = "concept_member"
    __table_args__ = (
        Index("idx_concept_stock", "ts_code"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    concept_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    concept_name: Mapped[str] = mapped_column(String(50))
    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    src: Mapped[Optional[str]] = mapped_column(String(20))
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=_NOW, nullable=True
    )


# ============ 7. 概念板块每日热度 ============

class ConceptDaily(Base):
    __tablename__ = "concept_daily"
    __table_args__ = (
        Index("idx_cd_date", "trade_date"),
        Index("idx_cd_rank", "trade_date", "rank_today"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    concept_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    concept_name: Mapped[str] = mapped_column(String(50))

    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    pct_chg_5d: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    pct_chg_10d: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    pct_chg_20d: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))

    rank_today: Mapped[Optional[int]] = mapped_column(Integer)
    rank_5d: Mapped[Optional[int]] = mapped_column(Integer)
    rank_10d: Mapped[Optional[int]] = mapped_column(Integer)
    rank_20d: Mapped[Optional[int]] = mapped_column(Integer)

    persistence_top10: Mapped[Optional[int]] = mapped_column(Integer)
    persistence_top20: Mapped[Optional[int]] = mapped_column(Integer)
    strength_rating: Mapped[Optional[str]] = mapped_column(String(20))


# ============ 8. 个股每日分析快照 ============

class StockAnalysis(Base):
    __tablename__ = "stock_analysis"
    __table_args__ = (
        Index("idx_an_date", "trade_date"),
        Index("idx_an_phase", "trade_date", "phase"),
        Index("idx_an_opp", "trade_date", "opportunity_level"),
        Index("idx_an_score", "trade_date", "score"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    has_main_force: Mapped[bool] = mapped_column(Boolean, default=False)
    force_strength: Mapped[Optional[int]] = mapped_column(Integer)
    force_type: Mapped[Optional[str]] = mapped_column(String(30))
    inst_score: Mapped[Optional[int]] = mapped_column(Integer)
    youzi_score: Mapped[Optional[int]] = mapped_column(Integer)

    control_pct: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 2))
    control_level: Mapped[Optional[str]] = mapped_column(String(20))

    phase: Mapped[Optional[str]] = mapped_column(String(30))
    sub_phase: Mapped[Optional[str]] = mapped_column(String(30))
    days_in_phase: Mapped[Optional[int]] = mapped_column(Integer)
    phase_score: Mapped[Optional[int]] = mapped_column(Integer)

    phase_established: Mapped[bool] = mapped_column(Boolean, default=False)
    phase_changed_today: Mapped[bool] = mapped_column(Boolean, default=False)

    opportunity_level: Mapped[Optional[str]] = mapped_column(String(30))
    score: Mapped[Optional[int]] = mapped_column(Integer)

    close: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    ma5: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    ma20: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    ma60: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    dist_ma20: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    dist_ma60: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    dist_high_120: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))

    flow_5d: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    flow_10d: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    flow_20d: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    flow_5d_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    flow_direction: Mapped[Optional[str]] = mapped_column(String(50))

    vol_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    is_volume_stagnation: Mapped[bool] = mapped_column(Boolean, default=False)

    kongpan: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    kongpan_trend: Mapped[Optional[str]] = mapped_column(String(10))

    primary_sector: Mapped[Optional[str]] = mapped_column(String(50))
    sector_strength: Mapped[Optional[str]] = mapped_column(String(20))
    is_sector_resonant: Mapped[bool] = mapped_column(Boolean, default=False)

    has_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_desc: Mapped[Optional[str]] = mapped_column(String(200))

    circ_mv: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    turnover_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))


# ============ 9. 大盘每日分析 ============

class MarketAnalysis(Base):
    __tablename__ = "market_analysis"
    __table_args__ = (
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    sh_close: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4))
    sh_pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    sh_pattern: Mapped[Optional[str]] = mapped_column(String(50))
    sh_pattern_duration: Mapped[Optional[int]] = mapped_column(Integer)
    market_style: Mapped[Optional[str]] = mapped_column(String(50))
    today_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    amount_ma20: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    amount_state: Mapped[Optional[str]] = mapped_column(String(20))
    limit_up_count: Mapped[Optional[int]] = mapped_column(Integer)
    limit_down_count: Mapped[Optional[int]] = mapped_column(Integer)
    broken_limit_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    recommended_position: Mapped[Optional[str]] = mapped_column(String(50))
    operation_advice: Mapped[Optional[str]] = mapped_column(String(100))
    detail_json: Mapped[Optional[str]] = mapped_column(Text)


# ============ 10. 自选股 ============

class Watchlist(Base):
    __tablename__ = "watchlist"
    __table_args__ = (
        Index("idx_watch_status", "status", "ts_code"),
        UniqueConstraint("ts_code", "status", name="uq_watch_active"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(50))
    sector: Mapped[Optional[str]] = mapped_column(String(50))

    added_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=_NOW, nullable=True
    )
    added_phase: Mapped[Optional[str]] = mapped_column(String(30))
    added_score: Mapped[Optional[int]] = mapped_column(Integer)

    cost_price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    shares: Mapped[Optional[int]] = mapped_column(Integer)
    position_pct: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 2))

    status: Mapped[str] = mapped_column(String(20), default="watching")
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    remove_reason: Mapped[Optional[str]] = mapped_column(String(100))


# ============ 11. 笔记/复盘日记 ============

class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("idx_note_type", "note_type", "created_at"),
        Index("idx_note_stock", "ts_code"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    note_type: Mapped[str] = mapped_column(String(20))
    ts_code: Mapped[Optional[str]] = mapped_column(String(12))
    title: Mapped[Optional[str]] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)

    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=_NOW, nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=_NOW_UPDATE, nullable=True
    )


# ============ 12. 系统状态/任务执行记录 ============

class SystemStatus(Base):
    __tablename__ = "system_status"
    __table_args__ = (
        Index("idx_sys_type", "task_type", "started_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(30))
    task_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=_NOW, nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)

    progress: Mapped[Optional[int]] = mapped_column(Integer)
    progress_msg: Mapped[Optional[str]] = mapped_column(String(500))
    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    api_calls: Mapped[Optional[int]] = mapped_column(Integer)


# ============ 扫描预设 ============

class ScanPreset(Base):
    __tablename__ = "scan_presets"
    __table_args__ = (
        UniqueConstraint("name", name="uq_preset_name"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(String(200))
    params_json: Mapped[str] = mapped_column(Text)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=_NOW, nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=_NOW_UPDATE, nullable=True
    )


# ============ 扫描历史 ============

class ScanHistory(Base):
    __tablename__ = "scan_history"
    __table_args__ = (
        Index("idx_scan_date", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preset_name: Mapped[Optional[str]] = mapped_column(String(50))
    params_json: Mapped[str] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    result_codes_json: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=_NOW, nullable=True
    )
