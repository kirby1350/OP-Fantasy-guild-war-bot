"""官方 QQ 测试上下文，不访问网络或读取生产数据库。"""

import nonebot
from nonebot.adapters.qq import Adapter, Bot
from nonebot.adapters.qq.config import BotInfo
from nonebot.adapters.qq.event import GroupAtMessageCreateEvent

nonebot.init(
    driver="~fastapi+~httpx",
    gw_admins={"999:123456"},
    command_start={"", "/"},
    qq_bots=[],
)
nonebot.get_driver().register_adapter(Adapter)
assert nonebot.load_plugin("src.plugins.guild_war") is not None


def make_bot(app_id="999"):
    return Bot(
        nonebot.get_adapter(Adapter),
        app_id,
        BotInfo(id=app_id, token="", secret="test-secret", use_websocket=False),
    )


def event(user_id=123456, group_id=100, content="", attachments=None):
    return GroupAtMessageCreateEvent(
        id="message-001",
        timestamp="2026-09-25T00:00:00+08:00",
        content=content,
        group_id=str(group_id),
        group_openid=str(group_id),
        attachments=attachments,
        author={
            "id": str(user_id),
            "member_openid": str(user_id),
            "bot": False,
            "member_role": "admin",
            "username": "测试成员",
        },
    )
