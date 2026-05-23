"""
APScheduler 定时任务：每天17:30/19:00/19:30 北京时间。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from ..config import settings
from ..data import updater

logger = logging.getLogger(__name__)


_scheduler: AsyncIOScheduler | None = None


def parse_time(time_str: str) -> tuple[int, int]:
    """解析 HH:MM 格式。"""
    h, m = time_str.split(":")
    return int(h), int(m)


def get_scheduler() -> AsyncIOScheduler:
    """获取或创建全局 scheduler。"""
    global _scheduler
    if _scheduler is None:
        tz = pytz.timezone("Asia/Shanghai")
        _scheduler = AsyncIOScheduler(timezone=tz)
    return _scheduler


def setup_jobs():
    """注册所有定时任务。"""
    sch = get_scheduler()
    tz = pytz.timezone("Asia/Shanghai")

    # 第一批：行情+基本面+指数（17:30）
    h1, m1 = parse_time(settings.schedule_first_run)
    sch.add_job(
        _job_first_batch,
        trigger=CronTrigger(hour=h1, minute=m1, day_of_week="mon-fri", timezone=tz),
        id="daily_first_batch",
        name="第一批：行情+基本面+指数",
        replace_existing=True,
    )

    # 第二批：资金流向（19:00）
    h2, m2 = parse_time(settings.schedule_second_run)
    sch.add_job(
        _job_second_batch,
        trigger=CronTrigger(hour=h2, minute=m2, day_of_week="mon-fri", timezone=tz),
        id="daily_second_batch",
        name="第二批：资金流向",
        replace_existing=True,
    )

    # 第三批：分析计算（19:30）
    h3, m3 = parse_time(settings.schedule_third_run)
    sch.add_job(
        _job_third_batch,
        trigger=CronTrigger(hour=h3, minute=m3, day_of_week="mon-fri", timezone=tz),
        id="daily_third_batch",
        name="第三批：分析计算",
        replace_existing=True,
    )

    logger.info(f"定时任务已注册：")
    logger.info(f"  17:30/19:00/19:30 北京时间，工作日执行")


def _job_first_batch():
    logger.info("开始执行：第一批")
    try:
        result = updater.daily_update_first_batch()
        logger.info(f"第一批完成: {result}")
    except Exception as e:
        logger.exception(f"第一批失败: {e}")


def _job_second_batch():
    logger.info("开始执行：第二批")
    try:
        result = updater.daily_update_second_batch()
        logger.info(f"第二批完成: {result}")
    except Exception as e:
        logger.exception(f"第二批失败: {e}")


def _job_third_batch():
    logger.info("开始执行：第三批")
    try:
        result = updater.daily_update_third_batch()
        logger.info(f"第三批完成: {result}")
    except Exception as e:
        logger.exception(f"第三批失败: {e}")


def start_scheduler():
    """启动调度器。"""
    sch = get_scheduler()
    if not sch.running:
        setup_jobs()
        sch.start()
        logger.info("调度器已启动")


def stop_scheduler():
    """停止调度器。"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("调度器已停止")
        _scheduler = None
