"""成员注册与多账号绑定"""

from typing import List

from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot, GroupMessageEvent, Message, MessageSegment, GROUP_ADMIN, GROUP_OWNER
)
from nonebot.internal.matcher import Matcher
from nonebot.params import ArgPlainText, CommandArg
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State

from .database import (
    get_member_by_user, create_member, bind_account, unbind_account,
    rename_member, delete_member, list_members,
)
from .models import Member

# 管理员：超级用户 / 群主 / 群管理
ADMIN = SUPERUSER | GROUP_ADMIN | GROUP_OWNER


def at_member(user_ids: List[str]) -> Message:
    """@成员的所有绑定账号"""
    return Message([MessageSegment.at(uid) for uid in user_ids])


def extract_ats(args: Message) -> List[str]:
    return [str(seg.data["qq"]) for seg in args
            if seg.type == "at" and str(seg.data["qq"]) != "all"]


async def require_member(matcher: Matcher, event: GroupMessageEvent) -> Member:
    """获取发送者所属成员，未注册则直接结束"""
    member = await get_member_by_user(str(event.user_id), str(event.group_id))
    if not member:
        await matcher.finish("❌ 你还没有注册，请先发送「注册 <游戏名>」。")
    return member


async def _is_admin(bot: Bot, event: GroupMessageEvent) -> bool:
    return await ADMIN(bot, event)


# ─── 注册 ───────────────────────────────────────────────────────────────────

register_cmd = on_command("注册", block=True)

@register_cmd.handle()
async def handle_register(event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    user_id = str(event.user_id)

    existing = await get_member_by_user(user_id, group_id)
    if existing:
        await register_cmd.finish(f"❌ 你已注册为「{existing.name}」。")

    name = (args.extract_plain_text().strip()
            or event.sender.card or event.sender.nickname or user_id)
    member = await create_member(group_id, name, user_id)
    await register_cmd.finish(
        f"✅ 注册成功：{member.name}\n"
        f"如有小号，请用本账号发送「绑定 @小号」，两个账号将共用刀数。"
    )


# ─── 绑定 / 解绑 ─────────────────────────────────────────────────────────────

bind_cmd = on_command("绑定", block=True)

@bind_cmd.handle()
async def handle_bind(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    ats = extract_ats(args)

    if len(ats) == 2:
        # 管理员代绑：绑定 @大号 @小号
        if not await _is_admin(bot, event):
            await bind_cmd.finish("❌ 只有管理员可以为他人绑定账号。")
        member = await get_member_by_user(ats[0], group_id)
        if not member:
            await bind_cmd.finish("❌ 第一个@的账号尚未注册。")
        target = ats[1]
    elif len(ats) == 1:
        member = await require_member(bind_cmd, event)
        target = ats[0]
    else:
        await bind_cmd.finish(
            "❌ 用法：绑定 @小号\n管理员代绑：绑定 @大号 @小号"
        )

    if not await bind_account(member.id, group_id, target):
        await bind_cmd.finish("❌ 该账号已注册或已绑定到其他成员，请先解绑。")
    await bind_cmd.finish(
        Message(f"✅ 已将 ") + MessageSegment.at(target)
        + f" 绑定到「{member.name}」，出刀将合并计算。"
    )


unbind_cmd = on_command("解绑", block=True)

@unbind_cmd.handle()
async def handle_unbind(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    ats = extract_ats(args)
    target = ats[0] if ats else str(event.user_id)

    member = await get_member_by_user(target, group_id)
    if not member:
        await unbind_cmd.finish("❌ 该账号没有注册或绑定。")

    caller_member = await get_member_by_user(str(event.user_id), group_id)
    is_own = caller_member is not None and caller_member.id == member.id
    if not is_own and not await _is_admin(bot, event):
        await unbind_cmd.finish("❌ 只能解绑自己成员下的账号。")
    if len(member.user_ids) <= 1:
        await unbind_cmd.finish("❌ 这是该成员最后一个账号，无法解绑（如需删除请让管理员「注销」）。")

    await unbind_account(target, group_id)
    await unbind_cmd.finish(f"✅ 已从「{member.name}」解绑账号 {target}。")


# ─── 改名 / 查看 ─────────────────────────────────────────────────────────────

rename_cmd = on_command("改名", block=True)

@rename_cmd.handle()
async def handle_rename(event: GroupMessageEvent, args: Message = CommandArg()):
    member = await require_member(rename_cmd, event)
    name = args.extract_plain_text().strip()
    if not name:
        await rename_cmd.finish("❌ 用法：改名 <新名字>")
    await rename_member(member.id, name)
    await rename_cmd.finish(f"✅ 已改名：{member.name} → {name}")


my_info_cmd = on_command("我的信息", aliases={"我的账号"}, block=True)

@my_info_cmd.handle()
async def handle_my_info(event: GroupMessageEvent):
    member = await require_member(my_info_cmd, event)
    await my_info_cmd.finish(
        f"👤 成员：{member.name}\n绑定账号：{'、'.join(member.user_ids)}"
    )


member_list_cmd = on_command("成员列表", block=True)

@member_list_cmd.handle()
async def handle_member_list(event: GroupMessageEvent):
    members = await list_members(str(event.group_id))
    if not members:
        await member_list_cmd.finish("暂无注册成员。")
    lines = [f"📋 已注册成员（{len(members)}人）："]
    for m in members:
        extra = f"（{len(m.user_ids)}个账号）" if len(m.user_ids) > 1 else ""
        lines.append(f"· {m.name}{extra}")
    await member_list_cmd.finish("\n".join(lines))


# ─── 注销（管理员） ──────────────────────────────────────────────────────────

delete_member_cmd = on_command("注销", permission=ADMIN, block=True)

@delete_member_cmd.handle()
async def handle_delete_member(event: GroupMessageEvent, args: Message = CommandArg()):
    ats = extract_ats(args)
    if not ats:
        await delete_member_cmd.finish("❌ 用法：注销 @成员")
    member = await get_member_by_user(ats[0], str(event.group_id))
    if not member:
        await delete_member_cmd.finish("❌ 该账号没有注册。")
    await delete_member(member.id)
    await delete_member_cmd.finish(
        f"✅ 已注销成员「{member.name}」及其 {len(member.user_ids)} 个账号。"
    )


# ─── 解除注册（本人） ────────────────────────────────────────────────────────

unregister_cmd = on_command("解除注册", aliases={"取消注册"}, block=True)

@unregister_cmd.handle()
async def handle_unregister(event: GroupMessageEvent, state: T_State):
    member = await require_member(unregister_cmd, event)
    state["member_id"] = member.id
    state["member_name"] = member.name
    accounts = f"及其 {len(member.user_ids)} 个绑定账号" if len(member.user_ids) > 1 else ""
    await unregister_cmd.send(
        f"⚠️ 确定要解除「{member.name}」的注册{accounts}吗？\n"
        f"发送「确认」继续，发送其他内容取消。"
    )


@unregister_cmd.got("confirm")
async def handle_unregister_confirm(state: T_State, confirm: str = ArgPlainText()):
    if confirm.strip() != "确认":
        await unregister_cmd.finish("已取消。")
    await delete_member(state["member_id"])
    await unregister_cmd.finish(
        f"✅ 已解除「{state['member_name']}」的注册，今日出刀记录保留。"
    )
