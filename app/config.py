"""
配置中心：从 .env 加载，提供全局可访问的 settings 对象。
"""
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录（v2/）
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """全局配置。所有配置项都从环境变量或 .env 读取。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ============ Tushare ============
    tushare_token: str = Field(default="", description="tushare token")

    # ============ MySQL ============
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "gupiao_app"
    mysql_password: str = ""
    mysql_database: str = "gupiao"

    # ============ Web ============
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    debug: bool = False

    # ============ 定时任务（北京时间）============
    schedule_first_run: str = "17:30"
    schedule_second_run: str = "19:00"
    schedule_third_run: str = "19:30"

    # ============ 数据策略 ============
    history_days: int = 500
    min_data_days: int = 60

    # ============ 接口频控 ============
    rate_limit_interval: float = 1.0
    rate_limit_per_minute: int = 80

    # ============ 日志 ============
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_dir: str = "logs"

    # ============ 报告归档 ============
    report_dir: str = "reports"

    # ============ 派生属性 ============
    @property
    def database_url(self) -> str:
        """SQLAlchemy 数据库连接字符串。"""
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )

    @property
    def base_dir(self) -> Path:
        return BASE_DIR

    @property
    def log_path(self) -> Path:
        p = BASE_DIR / self.log_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def report_path(self) -> Path:
        p = BASE_DIR / self.report_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


# 全局单例
settings = Settings()
