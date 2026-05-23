"""
数据库连接管理。
SQLAlchemy 2.0 风格，PyMySQL 纯Python驱动（ARM/Debian友好）。
"""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


# 数据库基类（SQLAlchemy 2.0 风格）
class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""
    pass


# 引擎 - 延迟初始化
_engine = None
_SessionLocal = None


def get_engine():
    """获取或创建 SQLAlchemy 引擎。"""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,       # 连接前ping，避免连接断开
            pool_recycle=3600,        # 1小时回收连接
            pool_size=5,
            max_overflow=10,
            echo=settings.debug,
        )
    return _engine


def get_session_factory():
    """获取 Session 工厂。"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """
    上下文管理器：自动提交/回滚。
    
    使用方式：
        with session_scope() as session:
            session.add(obj)
    """
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖注入用。"""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables():
    """创建所有表（首次初始化用）。"""
    from . import models  # 触发模型注册
    Base.metadata.create_all(bind=get_engine())


def drop_all_tables():
    """删除所有表（危险操作，仅开发用）。"""
    from . import models
    Base.metadata.drop_all(bind=get_engine())


def test_connection() -> tuple[bool, str]:
    """
    测试数据库连接。
    返回：(是否成功, 错误信息或版本号)
    """
    try:
        engine = get_engine()
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text("SELECT VERSION()")).scalar()
            return True, str(result)
    except Exception as e:
        return False, str(e)
