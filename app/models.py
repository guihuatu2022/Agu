"""
SQLAlchemy ORM 模型 —— 12张表。

设计原则：
1. 所有表使用 utf8mb4 字符集（兼容MySQL 5.7的真UTF-8）
2. 主键尽量是复合主键（ts_code + trade_date）
3. 关键查询字段都建索引
4. 时间字段用 DATE / DATETIME，避免时区问题
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, DECIMAL, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ============ 1. 股票元信息 ============

class StockMeta(Base):
    """股票元信息：代码、名称、上市日、所属市场等。"""
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
    market: Mapped[Optional[str]] = mapped_column(String(20))  # 主板/创业板/科创板/北交所
    is_st: Mapped[bool] = mapped_column(Boolean, default=False)
    delisted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


# ============ 2. 日线行情（主表，最大）============

class StockDaily(Base):
    """日线行情，包含原始价格和前复权价格。"""
    __tablename__ = "stock_daily"
    __table_args__ = (
        Index("idx_date", "trade_date"),
        Index("idx_code_date", "ts_code", "trade_date"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    # 原始价格
    open: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    high: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    low: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    close: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    pre_close: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    change_amt: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    vol: Mapped[Optional[int]] = mapped_column(BigInteger)  # 成交量（手）
    amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 3))  # 成交额（千元）

    # 前复权价格（计算指标用）
    open_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    high_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    low_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    close_qfq: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))

    # 复权因子和事件标记
    adj_factor: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 6))
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)  # 当日是否停牌（无数据）
    is_ex_dividend: Mapped[bool] = mapped_column(Boolean, default=False)  # 当日是否除权除息


# ============ 3. 每日基本面指标 ============

class StockBasicDaily(Base):
    """每日基本面：换手率、市值、PE等。"""
    __tablename__ = "stock_basic_daily"
    __table_args__ = (
        Index("idx_basic_date", "trade_date"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    turnover_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))  # 换手率%
    turnover_rate_f: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))  # 自由流通换手率%
    volume_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))  # 量比
    pe: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 4))
    pe_ttm: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 4))
    pb: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 4))
    total_share: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))  # 总股本（万股）
    float_share: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))  # 流通股本（万股）
    free_share: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))  # 自由流通股本（万股）
    total_mv: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))  # 总市值（万元）
    circ_mv: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))  # 流通市值（万元）


# ============ 4. 资金流向（大单/超大单分别存）============

class MoneyflowDaily(Base):
    """资金流向：买卖方分小单/中单/大单/超大单分别存。"""
    __tablename__ = "moneyflow_daily"
    __table_args__ = (
        Index("idx_flow_date", "trade_date"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    # 大单（10~100万元）
    buy_lg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    sell_lg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    # 超大单（>100万元）
    buy_elg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    sell_elg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    # 中单（4~10万元）
    buy_md_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    sell_md_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    # 小单（<4万元）
    buy_sm_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    sell_sm_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))

    # 计算列
    net_mf_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))  # 主力净额（大+超大）
    net_elg_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))  # 仅超大单净额


# ============ 5. 指数日线 ============

class IndexDaily(Base):
    """指数日线（上证、深证、各类宽基指数）。"""
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
    """概念板块成员表：哪只票属于哪个概念。"""
    __tablename__ = "concept_member"
    __table_args__ = (
        Index("idx_concept_stock", "ts_code"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    concept_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    concept_name: Mapped[str] = mapped_column(String(50))
    ts_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    src: Mapped[Optional[str]] = mapped_column(String(20))  # 来源（同花顺/东财等）
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ============ 7. 概念板块每日热度（预聚合，加速查询）============

class ConceptDaily(Base):
    """概念板块每日表现：涨跌幅、排名、4窗口持续度。"""
    __tablename__ = "concept_daily"
    __table_args__ = (
        Index("idx_cd_date", "trade_date"),
        Index("idx_cd_rank", "trade_date", "rank_today"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    concept_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    concept_name: Mapped[str] = mapped_column(String(50))

    # 多窗口涨跌幅
    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    pct_chg_5d: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    pct_chg_10d: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    pct_chg_20d: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))

    # 各窗口排名
    rank_today: Mapped[Optional[int]] = mapped_column(Integer)
    rank_5d: Mapped[Optional[int]] = mapped_column(Integer)
    rank_10d: Mapped[Optional[int]] = mapped_column(Integer)
    rank_20d: Mapped[Optional[int]] = mapped_column(Integer)

    # 持续度（在TOP10/TOP20的窗口数）
    persistence_top10: Mapped[Optional[int]] = mapped_column(Integer)  # 0~4
    persistence_top20: Mapped[Optional[int]] = mapped_column(Integer)

    # 强度评级
    strength_rating: Mapped[Optional[str]] = mapped_column(String(20))


# ============ 8. 个股每日分析快照 ============

class StockAnalysis(Base):
    """
    每只股票每天的"完整侦察报告"快照。
    这是扫描器的查询主表，所有筛选条件都在这里。
    """
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

    # ====== 主力侦察五问的结果 ======
    has_main_force: Mapped[bool] = mapped_column(Boolean, default=False)
    force_strength: Mapped[Optional[int]] = mapped_column(Integer)  # 主力强度评分0-100

    force_type: Mapped[Optional[str]] = mapped_column(String(30))   # 机构主导/游资主导/混战/散户
    inst_score: Mapped[Optional[int]] = mapped_column(Integer)
    youzi_score: Mapped[Optional[int]] = mapped_column(Integer)

    control_pct: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 2))  # 控盘度0-100
    control_level: Mapped[Optional[str]] = mapped_column(String(20))     # 高度/中度/弱/无

    phase: Mapped[Optional[str]] = mapped_column(String(30))             # 主阶段
    sub_phase: Mapped[Optional[str]] = mapped_column(String(30))         # 子阶段
    days_in_phase: Mapped[Optional[int]] = mapped_column(Integer)        # 进入该阶段第几天
    phase_score: Mapped[Optional[int]] = mapped_column(Integer)          # 阶段确定度0-100

    # ====== 阶段惯性（避免震荡跳变）======
    phase_established: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否确立（≥3天）
    phase_changed_today: Mapped[bool] = mapped_column(Boolean, default=False)  # 今天是否切换

    # ====== 机会等级 ======
    opportunity_level: Mapped[Optional[str]] = mapped_column(String(30))  # A级/B级/C级/无

    # ====== 综合评分 ======
    score: Mapped[Optional[int]] = mapped_column(Integer)  # 0-100

    # ====== 价格和均线 ======
    close: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    ma5: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    ma20: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    ma60: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    dist_ma20: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))  # 距MA20的%
    dist_ma60: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    dist_high_120: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))

    # ====== 资金多窗口 ======
    flow_5d: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))   # 亿元
    flow_10d: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    flow_20d: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    flow_5d_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))  # 占流通市值%
    flow_direction: Mapped[Optional[str]] = mapped_column(String(50))

    # ====== 量价 ======
    vol_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))  # 上涨日量/下跌日量
    is_volume_stagnation: Mapped[bool] = mapped_column(Boolean, default=False)

    # ====== 控盘指标 ======
    kongpan: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    kongpan_trend: Mapped[Optional[str]] = mapped_column(String(10))

    # ====== 板块共振 ======
    primary_sector: Mapped[Optional[str]] = mapped_column(String(50))
    sector_strength: Mapped[Optional[str]] = mapped_column(String(20))
    is_sector_resonant: Mapped[bool] = mapped_column(Boolean, default=False)

    # ====== 反常信号 ======
    has_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_desc: Mapped[Optional[str]] = mapped_column(String(200))

    # ====== 元信息 ======
    circ_mv: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))   # 流通市值万元
    turnover_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))


# ============ 9. 大盘每日分析 ============

class MarketAnalysis(Base):
    """大盘每日分析：多指数 + 浪型描述 + 风格判断。"""
    __tablename__ = "market_analysis"
    __table_args__ = (
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    # 主指数判断（上证综指）
    sh_close: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 4))
    sh_pct_chg: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    sh_pattern: Mapped[Optional[str]] = mapped_column(String(50))  # 13种浪型之一
    sh_pattern_duration: Mapped[Optional[int]] = mapped_column(Integer)  # 该形态持续多少周

    # 风格判断
    market_style: Mapped[Optional[str]] = mapped_column(String(50))  # 小盘成长/大盘价值/题材投机/...

    # 量能
    today_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))  # 今日全A成交额（亿）
    amount_ma20: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 4))
    amount_state: Mapped[Optional[str]] = mapped_column(String(20))

    # 涨停跌停
    limit_up_count: Mapped[Optional[int]] = mapped_column(Integer)
    limit_down_count: Mapped[Optional[int]] = mapped_column(Integer)
    broken_limit_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))

    # 操作建议
    recommended_position: Mapped[Optional[str]] = mapped_column(String(50))
    operation_advice: Mapped[Optional[str]] = mapped_column(String(100))

    # 完整数据（JSON存所有指数详情）
    detail_json: Mapped[Optional[str]] = mapped_column(Text)


# ============ 10. 自选股 ============

class Watchlist(Base):
    """用户自选股。"""
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

    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    added_phase: Mapped[Optional[str]] = mapped_column(String(30))   # 加入时所在阶段
    added_score: Mapped[Optional[int]] = mapped_column(Integer)       # 加入时评分

    # 持仓信息（可选）
    cost_price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 3))
    shares: Mapped[Optional[int]] = mapped_column(Integer)
    position_pct: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 2))

    # 状态
    status: Mapped[str] = mapped_column(String(20), default="watching")
    # watching=仅观察, holding=持有, removed=已移除

    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    remove_reason: Mapped[Optional[str]] = mapped_column(String(100))


# ============ 11. 笔记/复盘日记 ============

class Note(Base):
    """笔记：可绑定到具体股票，也可作为日记。"""
    __tablename__ = "notes"
    __table_args__ = (
        Index("idx_note_type", "note_type", "created_at"),
        Index("idx_note_stock", "ts_code"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    note_type: Mapped[str] = mapped_column(String(20))  # stock/daily/weekly/scan
    ts_code: Mapped[Optional[str]] = mapped_column(String(12))  # null 表示日记
    title: Mapped[Optional[str]] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


# ============ 12. 系统状态/任务执行记录 ============

class SystemStatus(Base):
    """
    系统状态记录：
    - 数据初始化进度
    - 每日定时任务的执行情况
    - 失败重试记录
    """
    __tablename__ = "system_status"
    __table_args__ = (
        Index("idx_sys_type", "task_type", "started_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(30))  # init/daily_update/scan/...
    task_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))  # running/success/failed/partial

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)

    progress: Mapped[Optional[int]] = mapped_column(Integer)  # 0-100
    progress_msg: Mapped[Optional[str]] = mapped_column(String(500))

    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    api_calls: Mapped[Optional[int]] = mapped_column(Integer)


# ============ 用户保存的扫描预设 ============

class ScanPreset(Base):
    """用户保存的扫描条件预设。"""
    __tablename__ = "scan_presets"
    __table_args__ = (
        UniqueConstraint("name", name="uq_preset_name"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(String(200))
    params_json: Mapped[str] = mapped_column(Text)  # JSON编码的筛选条件
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否内置预设
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


# ============ 扫描历史 ============

class ScanHistory(Base):
    """扫描历史记录。"""
    __tablename__ = "scan_history"
    __table_args__ = (
        Index("idx_scan_date", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preset_name: Mapped[Optional[str]] = mapped_column(String(50))
    params_json: Mapped[str] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    result_codes_json: Mapped[Optional[str]] = mapped_column(Text)  # 命中的票代码列表JSON
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
