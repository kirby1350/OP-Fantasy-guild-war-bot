"""出刀队列与BOSS预约

- 进入（队列）：排在第一位的是当前出刀人，出完刀后自动@下一位
- 预约：预约之后的周目，BOSS被击杀进入该周目时@预约的人
  （击杀时带「连」则等连续刀打完再提醒）
"""

from itertools import groupby
from typing import List

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.params import CommandArg

from .database import (
    get_boss_status, add_to_queue, remove_from_queue, get_queue, clear_queue,
    get_member, get_member_by_user,
    add_reservation, cancel_reservations, get_reservations, mark_reservations_notified,
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


async def _at_members(member_ids: List[int]) -> Message:
    msg = Message()
    for mid in member_ids:
        m = await get_member(mid)
        if m:
            msg += at_member(m.user_ids)
    return msg


async def _call_head(queue: List[QueueEntry]) -> Message:
    """@队首成员（所有绑定账号）通知其出刀"""
    if not queue:
        return Message()
    return Message("\n\n📣 轮到你出刀了：") + await _at_members([queue[0].member_id])


async def leave_queue(member: Member, group_id: str) -> Message:
    """成员离开队列；若其原本是出刀中（队首），通知下一位"""
    queue = await get_queue(group_id)
    was_head = bool(queue) and queue[0].member_id == member.id
    if not await remove_from_queue(member.id, group_id):
        return Message()
    if not was_head:
        return Message()
    return await _call_head(await get_queue(group_id))


async def notify_reservations(group_id: str) -> Message:
    """@预约了当前周目且尚未提醒过的成员"""
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        return Message()
    pending = await get_reservations(group_id, status.round_num)
    if not pending:
        return Message()
    await mark_reservations_notified(group_id, status.round_num)
    return (Message(f"\n\n🔔 第 {status.round_num} 周目到了，预约的成员请出刀：")
            + await _at_members([r.member_id for r in pending]))


async def after_knife(member: Member, group_id: str, continuing: bool) -> Message:
    """出刀后处理：连续刀则保留在队首，不叫下一位也不提醒预约"""
    if continuing:
        return Message("\n🔁 连续刀：继续由你出刀，暂不叫下一位")
    return await leave_queue(member, group_id) + await notify_reservations(group_id)


# ─── 进入（出刀队列） ────────────────────────────────────────────────────────

join_cmd = on_command("进入", aliases={"排队", "申请出刀", "进刀"}, block=True)

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
        head = (f"📌 {member.name} 已进入队列，前面还有 {pos} 人" if added
                else f"❌ 你已在队列中，前面还有 {pos} 人")
    await join_cmd.finish(f"{head}\n━━━━━━━━━━━━━━\n{format_queue(queue)}")


leave_cmd = on_command("取消进入", aliases={"取消排队", "退出队列"}, block=True)

@leave_cmd.handle()
async def handle_leave(event: GroupMessageEvent):
    group_id = str(event.group_id)
    member = await require_member(leave_cmd, event)
    queue = await get_queue(group_id)
    if not any(q.member_id == member.id for q in queue):
        await leave_cmd.finish("❌ 你不在队列中。")
    notice = await leave_queue(member, group_id) + await notify_reservations(group_id)
    await leave_cmd.finish(Message(f"✅ {member.name} 已退出队列。") + notice)


show_cmd = on_command("队列", aliases={"排队情况", "查看排队", "查队列"}, block=True)

@show_cmd.handle()
async def handle_show(event: GroupMessageEvent):
    queue = await get_queue(str(event.group_id))
    await show_cmd.finish(f"📋 出刀队列（{len(queue)}人）：\n{format_queue(queue)}")


# ─── 预约 ───────────────────────────────────────────────────────────────────

reserve_cmd = on_command("预约", block=True)

@reserve_cmd.handle()
async def handle_reserve(event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    member = await require_member(reserve_cmd, event)

    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await reserve_cmd.finish("❌ 当前没有进行中的工会战。")

    arg = args.extract_plain_text().strip()
    if arg and not arg.isdigit():
        await reserve_cmd.finish("❌ 用法：预约 [周目]（不写默认预约下一周目）")
    boss_round = int(arg) if arg else status.round_num + 1
    if boss_round <= status.round_num:
        await reserve_cmd.finish(
            f"❌ 第 {boss_round} 周目已经开始，当前BOSS请直接「进入」出刀。"
        )

    if not await add_reservation(member.id, group_id, member.name, boss_round):
        await reserve_cmd.finish(f"❌ 你已经预约了第 {boss_round} 周目。")
    names = "、".join(r.user_name for r in await get_reservations(group_id, boss_round))
    await reserve_cmd.finish(
        f"🔔 {member.name} 预约了第 {boss_round} 周目，到达时会@你\n"
        f"第 {boss_round} 周目预约：{names}"
    )


cancel_reserve_cmd = on_command("取消预约", block=True)

@cancel_reserve_cmd.handle()
async def handle_cancel_reserve(event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    member = await require_member(cancel_reserve_cmd, event)
    arg = args.extract_plain_text().strip()
    if arg and not arg.isdigit():
        await cancel_reserve_cmd.finish("❌ 用法：取消预约 [周目]（不写则取消全部预约）")

    count = await cancel_reservations(member.id, group_id, int(arg) if arg else None)
    if not count:
        await cancel_reserve_cmd.finish("❌ 没有可取消的预约。")
    target = f"第 {arg} 周目的" if arg else f"全部 {count} 个"
    await cancel_reserve_cmd.finish(f"✅ 已取消{target}预约。")


query_reserve_cmd = on_command("查询预约", aliases={"查预约", "预约情况", "预约列表"}, block=True)

@query_reserve_cmd.handle()
async def handle_query_reserve(event: GroupMessageEvent):
    reservations = await get_reservations(str(event.group_id))
    if not reservations:
        await query_reserve_cmd.finish("暂无预约。发送「预约 [周目]」预约之后的BOSS。")
    lines = ["🔔 预约情况："]
    for boss_round, group in groupby(reservations, key=lambda r: r.boss_round):
        lines.append(f"第 {boss_round} 周目：{'、'.join(r.user_name for r in group)}")
    await query_reserve_cmd.finish("\n".join(lines))


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
    notice = await leave_queue(member, group_id) + await notify_reservations(group_id)
    await kick_cmd.finish(Message(f"✅ 已将 {member.name} 移出队列。") + notice)


clear_cmd = on_command("清空队列", permission=ADMIN, block=True)

@clear_cmd.handle()
async def handle_clear(event: GroupMessageEvent):
    await clear_queue(str(event.group_id))
    await clear_cmd.finish("✅ 队列已清空。")
