"""QQ 官方群机器人命令入口。"""

from nonebot import on_command
from nonebot.adapters.qq import Bot, Message
from nonebot.adapters.qq.event import GroupMessageCreateEvent
from nonebot.params import CommandArg

from . import services
from .qq_gateway import ADMIN, get_context, reply

start_gw = on_command("开启工会战", permission=ADMIN, block=True)


@start_gw.handle()
async def handle_start_gw(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_start_gw(ctx, args.extract_plain_text())
    await reply(bot, event, result)


end_gw = on_command("结束工会战", permission=ADMIN, block=True)


@end_gw.handle()
async def handle_end_gw(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_end_gw(ctx, args.extract_plain_text())
    await reply(bot, event, result)


boss_status_cmd = on_command(
    "boss状态", aliases={"BOSS状态", "boss", "BOSS"}, block=True
)


@boss_status_cmd.handle()
async def handle_boss_status(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_boss_status(ctx, args.extract_plain_text())
    await reply(bot, event, result)


report_knife = on_command("报刀", block=True)


@report_knife.handle()
async def handle_report_knife(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_report_knife(ctx, args.extract_plain_text())
    await reply(bot, event, result)


compensate_knife = on_command("补偿刀", block=True)


@compensate_knife.handle()
async def handle_compensate(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_compensate(ctx, args.extract_plain_text())
    await reply(bot, event, result)


undo_knife = on_command("撤刀", block=True)


@undo_knife.handle()
async def handle_undo(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_undo(ctx, args.extract_plain_text())
    await reply(bot, event, result)


reserve_cmd = on_command("预约", block=True)


@reserve_cmd.handle()
async def handle_reserve(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_reserve(ctx, args.extract_plain_text())
    await reply(bot, event, result)


cancel_reserve_cmd = on_command("取消预约", block=True)


@cancel_reserve_cmd.handle()
async def handle_cancel_reserve(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_cancel_reserve(ctx, args.extract_plain_text())
    await reply(bot, event, result)


progress_cmd = on_command("出刀进度", aliases={"进度", "查进度"}, block=True)


@progress_cmd.handle()
async def handle_progress(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_progress(ctx, args.extract_plain_text())
    await reply(bot, event, result)


chart_cmd = on_command("今日汇总", aliases={"汇总", "图表"}, block=True)


@chart_cmd.handle()
async def handle_chart(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_chart(ctx, args.extract_plain_text())
    await reply(bot, event, result)


remind_cmd = on_command("催刀", permission=ADMIN, block=True)


@remind_cmd.handle()
async def handle_remind(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    result = await services.handle_remind(ctx, args.extract_plain_text())
    await reply(bot, event, result)


identity_cmd = on_command("我的身份", block=True)

calibrate_cmd = on_command(
    "设置BOSS", aliases={"设置boss"}, permission=ADMIN, block=True
)


@calibrate_cmd.handle()
async def handle_calibrate_boss(
    bot: Bot, event: GroupMessageCreateEvent, args: Message = CommandArg()
):
    ctx = await get_context(bot, event)
    await reply(
        bot, event, await services.handle_calibrate_boss(ctx, args.extract_plain_text())
    )


@identity_cmd.handle()
async def handle_identity(bot: Bot, event: GroupMessageCreateEvent):
    await reply(
        bot,
        event,
        f"AppID：{bot.self_id}\n用户 OpenID：{event.author.member_openid}\n"
        f"群 OpenID：{event.group_openid}\n"
        f"管理员配置项：{bot.self_id}:{event.author.member_openid}",
    )
