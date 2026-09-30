"""帮助菜单与 @机器人 交互"""

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import to_me

HELP_SECTIONS = {
    "成员": [
        ("注册 [游戏名]", "注册成员，报刀/预约前必须先注册"),
        ("绑定 @小号", "把小号绑到自己名下，刀数合并计算"),
        ("解绑 [@账号]", "解绑账号，不@则解绑自己"),
        ("解除注册", "删除自己的注册信息"),
        ("改名 <名字>", "修改成员名"),
        ("我的信息 / 成员列表", "查看注册信息"),
    ],
    "出刀": [
        ("报刀 <伤害>", "记录一刀，打死BOSS自动算尾刀并获得补偿刀"),
        ("补偿刀 <伤害>", "使用补偿刀"),
        ("撤刀", "撤销自己最近一刀"),
        ("预约 / 取消预约", "预约当前周目BOSS"),
        ("BOSS状态", "查看BOSS血量与预约名单"),
        ("出刀进度", "查看今日全员出刀情况"),
        ("今日汇总", "生成今日出刀图表"),
    ],
    "作业": [
        ("查作业", "列出所有作业"),
        ("查作业 <编号/关键词>", "查看作业图"),
    ],
    "管理": [
        ("开启工会战 / 结束工会战", "开始/结束今日工会战"),
        ("催刀", "@所有未出完刀的成员"),
        ("上传作业 <标题> [图片]", "可附图、回复图片或随后发送"),
        ("删除作业 <编号>", "删除作业"),
        ("绑定 @大号 @小号", "代为绑定账号"),
        ("注销 @成员", "删除某个成员"),
    ],
}

HELP_ALIASES = {"成员": "成员", "注册": "成员", "出刀": "出刀", "报刀": "出刀",
                "作业": "作业", "管理": "管理", "管理员": "管理"}


def build_help(section: str = "") -> str:
    key = HELP_ALIASES.get(section)
    if key:
        lines = [f"📖 {key}指令："]
        lines += [f"· {cmd}\n   {desc}" for cmd, desc in HELP_SECTIONS[key]]
        return "\n".join(lines)

    lines = ["📖 工会战BOT 指令菜单"]
    for name, cmds in HELP_SECTIONS.items():
        lines.append(f"\n【{name}】")
        lines += [f"· {cmd}" for cmd, _ in cmds]
    lines.append(
        "\n发送「帮助 成员/出刀/作业/管理」查看说明\n"
        "指令前可以@我，例如：@我 报刀 1234567"
    )
    return "\n".join(lines)


# ─── 帮助 ───────────────────────────────────────────────────────────────────

help_cmd = on_command("帮助", aliases={"菜单", "help", "指令"}, block=True)

@help_cmd.handle()
async def handle_help(event: GroupMessageEvent):
    section = event.get_plaintext().strip().split(maxsplit=1)
    await help_cmd.finish(build_help(section[1] if len(section) > 1 else ""))


# ─── @机器人 兜底：只@不说话显示菜单，说了无法识别的内容给出提示 ───────────────

def _explicit_at(event: GroupMessageEvent) -> bool:
    """确实@了机器人（回复机器人消息也会被视为to_me，此处排除）"""
    return any(seg.type == "at" and str(seg.data.get("qq")) == str(event.self_id)
               for seg in event.original_message)


at_fallback = on_message(rule=to_me() & _explicit_at, priority=99, block=True)

@at_fallback.handle()
async def handle_at_fallback(event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    if not text:
        await at_fallback.finish(build_help(), at_sender=True)
    await at_fallback.finish(
        f"没有识别到指令「{text[:20]}」（或你没有该指令权限）\n发送「帮助」查看所有指令",
        at_sender=True,
    )
