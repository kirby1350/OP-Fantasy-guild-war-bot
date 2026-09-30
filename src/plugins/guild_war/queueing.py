"""出刀排队：排在第一位的是当前出刀人，出完刀后自动@下一位"""

from typing import List

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.params import CommandArg

from .database import (
    get_boss_status, add_to_queue, remove_from_queue, get_queue, clear_queue,
    get_member, get_member_by_user,
)
from .members import ADMIN, require_member, at_member, extract_ats
from .models import Member, QueueEntry


def format_queue(queue: List[QueueEntry]) -> str:
    if not queue:
        return "队列为空"
    lines = []
    for i, q in enumerate(queue):
        tag = "⚔️ 出刀中" if i == 0 else f"{i}."
        lines.append(f"{tag} {q.user_name}")
    return "\n".join(lines)


async def _call_head(queue: List[QueueEntry]) -> Message:
    """@队首成员（所有绑定账号）通知其出刀"""
    if not queue:
        return Message()
    head = await get_member(queue[0].member_id)
    if not head:
        return Message()
    return Message("\n\n📣 轮到你出刀了：") + at_member(head.user_ids)


async def leave_queue(member: Member, group_id: str) -> Message:
    """成员离开队列；若其原本是出刀中（队首），通知下一位"""
    queue = await get_queue(group_id)
    was_head = bool(queue) and queue[0].member_id == member.id
    if not await remove_from_queue(member.id, group_id):
        return Message()
    if not was_head:
        return Message()
    return await _call_head(await get_queue(group_id))


async def after_knife(member: Member, group_id: str, continuing: bool) -> Message:
    """出刀后处理队列：连续刀则保留在队首，不叫下一位"""
    if continuing:
        return Message("\n🔁 连续刀：继续由你出刀，暂不叫下一位")
    return await leave_queue(member, group_id)


# ─── 排队 ───────────────────────────────────────────────────────────────────

join_cmd = on_command("排队", aliases={"预约", "申请出刀"}, block=True)

@join_cmd.handle()
async def handle_join(event: GroupMessageEvent):
    group_id = str(event.group_id)
    member = await require_member(join_cmd, event)

    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await join_cmd.finish("❌ 当前没有进行中的工会战。")

    added = await add_to_queue(member.id, group_id, member.name)
    queue = await get_queue(group_id)
    pos = next(i for i, q in enumerate(queue) if q.member_id == member.id)

    if pos == 0:
        head = "⚔️ 轮到你了，请出刀！" if added else "⚔️ 你正在出刀中。"
    else:
        head = (f"📌 {member.name} 已排队，前面还有 {pos} 人" if added
                else f"❌ 你已在队列中，前面还有 {pos} 人")
    await join_cmd.finish(f"{head}\n━━━━━━━━━━━━━━\n{format_queue(queue)}")


leave_cmd = on_command("取消排队", aliases={"取消预约"}, block=True)

@leave_cmd.handle()
async def handle_leave(event: GroupMessageEvent):
    group_id = str(event.group_id)
    member = await require_member(leave_cmd, event)
    queue = await get_queue(group_id)
    if not any(q.member_id == member.id for q in queue):
        await leave_cmd.finish("❌ 你不在队列中。")
    notice = await leave_queue(member, group_id)
    await leave_cmd.finish(Message(f"✅ {member.name} 已退出队列。") + notice)


show_cmd = on_command("队列", aliases={"排队情况", "查看排队", "查队列"}, block=True)

@show_cmd.handle()
async def handle_show(event: GroupMessageEvent):
    queue = await get_queue(str(event.group_id))
    await show_cmd.finish(f"📋 出刀队列（{len(queue)}人）：\n{format_queue(queue)}")


# ─── 管理员 ─────────────────────────────────────────────────────────────────

kick_cmd = on_command("移出队列", permission=ADMIN, block=True)

@kick_cmd.handle()
async def handle_kick(event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    ats = extract_ats(args)
    if not ats:
        await kick_cmd.finish("❌ 用法：移出队列 @成员")
    member = await get_member_by_user(ats[0], group_id)
    queue = await get_queue(group_id)
    if not member or not any(q.member_id == member.id for q in queue):
        await kick_cmd.finish("❌ 该成员不在队列中。")
    notice = await leave_queue(member, group_id)
    await kick_cmd.finish(Message(f"✅ 已将 {member.name} 移出队列。") + notice)


clear_cmd = on_command("清空队列", permission=ADMIN, block=True)

@clear_cmd.handle()
async def handle_clear(event: GroupMessageEvent):
    await clear_queue(str(event.group_id))
    await clear_cmd.finish("✅ 队列已清空。")
