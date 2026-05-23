"""
数据库连接管理。
SQLAlchemy 2.0 风格，PyMySQL 纯Python驱动（ARM/Debian友好）。

启动时自动确保数据库存在（不存在则自动创建）。
"""
from contextlib import contextmanager
from typing import Iterator
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

logger = logging.getLogger(__name__)


# 数据库基类
class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None
_db_ensured = False


def _ensure_database_exists():
    """
    连到 MySQL 服务器（不指定数据库），如果目标数据库不存在则创建。
    只执行一次。
    """
    global _db_ensured
    if _db_ensured:
        return

    # 不带数据库名的连接URL
    server_url = (
        f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_password}"
        f"@{settings.mysql_host}:{settings.mysql_port}"
        f"?charset=utf8mb4"
    )
    try:
        tmp_engine = create_engine(server_url)
        with tmp_engine.connect() as conn:
            conn.execute(text(
                f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_database}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            ))
            conn.commit()
        tmp_engine.dispose()
        logger.info(f"数据库 {settings.mysql_database} 已就绪")
        _db_ensured = True
    except Exception as e:
        logger.error(f"创建数据库失败: {e}")
        raise


def get_engine():
    """获取或创建 SQLAlchemy 引擎。"""
    global _engine
    if _engine is None:
        _ensure_database_exists()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
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
        # 先确保数据库存在
        _ensure_database_exists()
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT VERSION()")).scalar()
            return True, str(result)
    except Exception as e:
        return False, str(e)
