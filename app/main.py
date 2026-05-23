"""
FastAPI 应用入口。
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings, BASE_DIR

# ============ 日志配置 ============

def setup_logging():
    log_dir = settings.log_path
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


setup_logging()
logger = logging.getLogger(__name__)


# ============ 生命周期 ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("股票趋势分析系统 v2.0 启动中...")
    logger.info(f"调试模式: {settings.debug}")
    logger.info(f"监听地址: {settings.web_host}:{settings.web_port}")

    # 测试数据库
    db_ok = False
    try:
        from .database import test_connection
        ok, msg = test_connection()
        db_ok = ok
        if ok:
            logger.info(f"MySQL 连接正常: {msg}")
        else:
            logger.warning(f"MySQL 连接失败: {msg}")
    except Exception as e:
        logger.warning(f"数据库测试出错: {e}")

    # 启动调度器（仅当 DB 连接成功时）
    if db_ok:
        try:
            from .scheduler.jobs import start_scheduler
            start_scheduler()
        except Exception as e:
            logger.warning(f"调度器启动失败（可继续运行）: {e}")
    else:
        logger.warning("数据库未连接，调度器未启动")

    logger.info("启动完成")
    logger.info("=" * 60)

    yield

    logger.info("应用关闭中...")
    try:
        from .scheduler.jobs import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    logger.info("应用已关闭")


# ============ 应用实例 ============

app = FastAPI(
    title="股票趋势分析系统",
    description="A股趋势票分析与全市场扫描",
    version="2.0.0",
    lifespan=lifespan,
)

# 静态资源
static_dir = BASE_DIR / "app" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 模板引擎
templates_dir = BASE_DIR / "app" / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


# ============ 注册API路由 ============

from .api import admin, market, scanner, watchlist
app.include_router(admin.router)
app.include_router(market.router)
app.include_router(scanner.router)
app.include_router(watchlist.router)


# ============ 页面路由 ============

NAV_TABS = [
    {"id": "dashboard", "name": "总览", "icon": "📊", "url": "/"},
    {"id": "market", "name": "大盘", "icon": "📈", "url": "/market"},
    {"id": "sector", "name": "板块", "icon": "🔥", "url": "/sector"},
    {"id": "scanner", "name": "扫描", "icon": "🎯", "url": "/scanner"},
    {"id": "watchlist", "name": "自选", "icon": "⭐", "url": "/watchlist"},
    {"id": "archive", "name": "归档", "icon": "📁", "url": "/archive"},
    {"id": "settings", "name": "设置", "icon": "⚙️", "url": "/settings"},
]


def _ctx(active: str, **extra) -> dict:
    """生成模板上下文（不含 request，新版 TemplateResponse 单独传）。"""
    return {
        "tabs": NAV_TABS,
        "active_tab": active,
        "version": "2.0.0",
        **extra,
    }


@app.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    return templates.TemplateResponse(request, "tabs/dashboard.html", _ctx("dashboard"))


@app.get("/market", response_class=HTMLResponse)
async def page_market(request: Request):
    return templates.TemplateResponse(request, "tabs/market.html", _ctx("market"))


@app.get("/sector", response_class=HTMLResponse)
async def page_sector(request: Request):
    return templates.TemplateResponse(request, "tabs/sector.html", _ctx("sector"))


@app.get("/scanner", response_class=HTMLResponse)
async def page_scanner(request: Request):
    return templates.TemplateResponse(request, "tabs/scanner.html", _ctx("scanner"))


@app.get("/watchlist", response_class=HTMLResponse)
async def page_watchlist(request: Request):
    return templates.TemplateResponse(request, "tabs/watchlist.html", _ctx("watchlist"))


@app.get("/archive", response_class=HTMLResponse)
async def page_archive(request: Request):
    return templates.TemplateResponse(request, "tabs/archive.html", _ctx("archive"))


@app.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request):
    return templates.TemplateResponse(request, "tabs/settings.html", _ctx("settings"))


# ============ 公共API（兼容原 health 路径）============

@app.get("/api/health")
async def api_health():
    """健康检查端点。"""
    from .database import test_connection
    db_ok, db_msg = test_connection()
    return {
        "status": "ok",
        "version": "2.0.0",
        "database": {"ok": db_ok, "info": db_msg},
    }


# ============ 启动入口 ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.web_host,
        port=settings.web_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
