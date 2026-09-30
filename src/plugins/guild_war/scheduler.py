"""定时任务：每日催刀提醒"""

from nonebot import get_bot, require, get_driver
from nonebot.adapters.onebot.v11 import Bot, Message

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from .config import REMIND_TIMES, MAX_KNIVES_PER_DAY
from .database import get_boss_status, get_today_summary
from .members import at_member

# NoneBot 读取 .env 后不会写入系统环境变量，需从驱动配置中读取
GW_GROUP_ID = str(getattr(get_driver().config, "gw_group_id", "") or "")


async def send_remind(bot: Bot, group_id: str):
    """发送催刀消息"""
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        return

    summaries = await get_today_summary(group_id)
    # 找出未完成的成员
    incomplete = []
    for s in summaries:
        used = s.normal_count + s.tail_count
        if used < MAX_KNIVES_PER_DAY:
            left = MAX_KNIVES_PER_DAY - used
            incomplete.append((s.user_ids, s.user_name, left, s.has_compensate_left))

    if not incomplete:
        await bot.send_group_msg(
            group_id=int(group_id),
            message="✅ 全员出刀完毕，辛苦大家！"
        )
        return

    lines = ["⏰ 催刀提醒！以下成员今日尚未出完刀：\n"]
    at_segments = Message()
    for uids, name, left, has_comp in incomplete:
        comp_hint = "（有补偿刀）" if has_comp else ""
        lines.append(f"· {name}：还差 {left} 刀{comp_hint}")
        at_segments += at_member(uids)  # 多账号成员会同时@所有账号

    lines.append(f"\n请尽快完成今日出刀！")

    # 先发@，再发文字
    msg = at_segments + "\n" + "\n".join(lines)
    await bot.send_group_msg(group_id=int(group_id), message=msg)


# 注册定时任务
for hour, minute in REMIND_TIMES:
    @scheduler.scheduled_job("cron", hour=hour, minute=minute,
                              id=f"gw_remind_{hour}_{minute}")
    async def _remind_job(h=hour, m=minute):
        if not GW_GROUP_ID:
            return
        try:
            bot: Bot = get_bot()
            await send_remind(bot, GW_GROUP_ID)
        except Exception as e:
            import logging
            logging.warning(f"催刀定时任务失败: {e}")
