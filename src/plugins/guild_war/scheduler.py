"""官方 QQ 主动催刀：仅在明确配置并具备平台权限时启用。"""

from nonebot import get_bot, get_plugin_config, logger, require
from nonebot.adapters.qq import Bot

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from .config import REMIND_TIMES
from .database import get_boss_status
from .qq_gateway import QQSettings, group_key
from .services import build_reminder


async def run_reminders():
    settings = get_plugin_config(QQSettings)
    if not settings.gw_enable_proactive_reminders:
        return
    for app_id, group_openids in settings.gw_reminder_targets.items():
        for group_openid in dict.fromkeys(group_openids):
            try:
                bot = get_bot(app_id)
                if not isinstance(bot, Bot):
                    continue
                key = group_key(app_id, group_openid)
                status = await get_boss_status(key)
                if status and status.is_active:
                    # 主动消息不伪造 msg_id，也不借用过期用户消息。
                    await bot.send_to_group(group_openid, await build_reminder(key))
            except Exception:
                logger.warning(
                    f"QQ 主动催刀失败（AppID={app_id}），请检查连接、群授权和主动消息额度。"
                )


for hour, minute in REMIND_TIMES:
    scheduler.add_job(
        run_reminders,
        "cron",
        hour=hour,
        minute=minute,
        timezone="Asia/Shanghai",
        id=f"gw_remind_{hour}_{minute}",
    )
