"""官方 QQ 的身份、权限与回复边界。"""

from nonebot import get_plugin_config, logger
from nonebot.adapters.qq import Bot, MessageSegment
from nonebot.adapters.qq.event import GroupMessageCreateEvent
from nonebot.adapters.qq.exception import ActionFailed
from nonebot.permission import Permission
from pydantic import BaseModel, Field

from .models import GuildContext


class QQSettings(BaseModel):
    # AppID:member_openid；不接受普通 QQ 号，也不自动授权群管理。
    gw_admins: set[str] = Field(default_factory=set)
    gw_enable_proactive_reminders: bool = False
    gw_reminder_targets: dict[str, list[str]] = Field(default_factory=dict)


def group_key(app_id: str, group_openid: str) -> str:
    return f"qq:{app_id}:group:{group_openid}"


async def is_admin(bot: Bot, event: GroupMessageCreateEvent) -> bool:
    return (
        f"{bot.self_id}:{event.author.member_openid}"
        in get_plugin_config(QQSettings).gw_admins
    )


ADMIN = Permission(is_admin)


async def get_context(bot: Bot, event: GroupMessageCreateEvent) -> GuildContext:
    uid = event.author.member_openid
    return GuildContext(
        group_id=group_key(bot.self_id, event.group_openid),
        user_id=f"qq:{bot.self_id}:user:{uid}",
        user_name=event.author.username or f"成员{uid[:8]}",
    )


async def reply(bot: Bot, event: GroupMessageCreateEvent, content: str | bytes):
    """bot.send 自动携带触发消息的 msg_id 和递增 msg_seq。"""
    message = (
        MessageSegment.file_image(content) if isinstance(content, bytes) else content
    )
    try:
        await bot.send(event, message)
    except ActionFailed:
        logger.warning("QQ 官方消息发送失败，请检查应用权限、媒体权限及回复时限。")
        raise
