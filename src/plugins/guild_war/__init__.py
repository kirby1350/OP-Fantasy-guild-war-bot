"""
工会战报刀 BOT 插件
功能：报刀/撤刀/补偿刀、BOSS血量追踪、周目进阶、预约、进度查询、图表汇总、定时催刀
"""

from nonebot import get_driver
from .database import init_db
from . import handlers  # noqa: F401 - 注册所有指令
from . import scheduler  # noqa: F401 - 注册定时任务

driver = get_driver()

@driver.on_startup
async def _():
    """启动时初始化数据库"""
    await init_db()
    import logging
    logging.info("✅ 工会战BOT数据库初始化完成")
