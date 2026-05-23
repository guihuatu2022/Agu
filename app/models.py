"""
SQLAlchemy ORM 模型 —— 12张表。

设计原则：
1. 所有表使用 utf8mb4 字符集
2. 主键尽量是复合主键（ts_code + trade_date）
3. 关键查询字段都建索引
4. 所有时间字段都设为 nullable，由代码层手动设置（避免 MySQL 5.7 严格模式默认值问题）
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, DECIMAL,
    Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


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
    area: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    list_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    market: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_st: Mapped[bool] = mapped_column(Boolean, default=False)
    delisted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


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

    open: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3), nullable=True)
    high: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3), nullable=True)
    low: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3), nullable=True)
    close: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3), nullable=True)
    pre_close: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3), nullable=True)
    change_amt: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3), nullable=True)
    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    vol: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 3), nullable=True)

    open_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    high_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    low_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    close_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)

    adj_factor: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 6), nullable=True)
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

    turnover_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    turnover_rate_f: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    pe: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 4), nullable=True)
    pe_ttm: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 4), nullable=True)
    pb: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 4), nullable=True)
    total_share: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    float_share: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    free_share: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    total_mv: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    circ_mv: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)


# ============ 4. 资金流向 ============

class MoneyflowDaily(Base):
    __tablename__ = "moneyflow_daily"
    __table_args__ = (
        Index("idx_flow_date", "trade_date"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    buy_lg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    sell_lg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    buy_elg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    sell_elg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    buy_md_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    sell_md_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    buy_sm_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    sell_sm_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)

    net_mf_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    net_elg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)


# ============ 5. 指数日线 ============

class IndexDaily(Base):
    __tablename__ = "index_daily"
    __table_args__ = (
        Index("idx_index_date", "trade_date"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4), nullable=True)
    high: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4), nullable=True)
    low: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4), nullable=True)
    close: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4), nullable=True)
    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    vol: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)


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
    src: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


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

    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    pct_chg_5d: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    pct_chg_10d: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    pct_chg_20d: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)

    rank_today: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rank_5d: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rank_10d: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rank_20d: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    persistence_top10: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    persistence_top20: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    strength_rating: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)


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
    force_strength: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    force_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    inst_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    youzi_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    control_pct: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 2), nullable=True)
    control_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    phase: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    sub_phase: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    days_in_phase: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    phase_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    phase_established: Mapped[bool] = mapped_column(Boolean, default=False)
    phase_changed_today: Mapped[bool] = mapped_column(Boolean, default=False)

    opportunity_level: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    close: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3), nullable=True)
    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    ma5: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    ma20: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    ma60: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    dist_ma20: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    dist_ma60: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    dist_high_120: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)

    flow_5d: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    flow_10d: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    flow_20d: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    flow_5d_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    flow_direction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    vol_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    is_volume_stagnation: Mapped[bool] = mapped_column(Boolean, default=False)

    kongpan: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    kongpan_trend: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    primary_sector: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sector_strength: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_sector_resonant: Mapped[bool] = mapped_column(Boolean, default=False)

    has_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_desc: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    circ_mv: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    turnover_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)


# ============ 9. 大盘每日分析 ============

class MarketAnalysis(Base):
    __tablename__ = "market_analysis"
    __table_args__ = (
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    sh_close: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4), nullable=True)
    sh_pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    sh_pattern: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sh_pattern_duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    market_style: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    today_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    amount_ma20: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4), nullable=True)
    amount_state: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    limit_up_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    limit_down_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    broken_limit_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    recommended_position: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    operation_advice: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    detail_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


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
    sector: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    added_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    added_phase: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    added_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    cost_price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3), nullable=True)
    shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position_pct: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 2), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="watching")
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remove_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


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
    ts_code: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text)

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ============ 12. 系统状态 ============

class SystemStatus(Base):
    __tablename__ = "system_status"
    __table_args__ = (
        Index("idx_sys_type", "task_type", "started_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(30))
    task_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20))

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    progress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    progress_msg: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_calls: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


# ============ 扫描预设 ============

class ScanPreset(Base):
    __tablename__ = "scan_presets"
    __table_args__ = (
        UniqueConstraint("name", name="uq_preset_name"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    params_json: Mapped[str] = mapped_column(Text)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ============ 扫描历史 ============

class ScanHistory(Base):
    __tablename__ = "scan_history"
    __table_args__ = (
        Index("idx_scan_date", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preset_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    params_json: Mapped[str] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    result_codes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
