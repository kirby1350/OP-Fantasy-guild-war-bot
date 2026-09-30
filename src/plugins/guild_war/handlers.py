"""指令处理器 - 所有QQ群指令的响应逻辑"""

import re
from datetime import date
from typing import Optional

from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot, GroupMessageEvent, Message, MessageSegment
)
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER

from .config import (
    MAX_KNIVES_PER_DAY, get_boss_stage, ENABLE_COMPENSATE_KNIFE
)
from .database import (
    get_boss_status, create_boss_status, update_boss_status,
    add_knife_record, get_member_today_records, delete_last_knife,
    add_compensate_knife, get_compensate_count, use_compensate_knife,
    get_today_summary, get_queue, clear_queue, get_reservations, clear_reservations,
)
from .members import require_member
from .models import KnifeRecord, KnifeType
from .queueing import after_knife, format_queue
from .chart import generate_daily_chart


def _fmt_hp(hp: int) -> str:
    """格式化血量显示"""
    if hp >= 1_000_000:
        return f"{hp/1_000_000:.2f}M"
    return f"{hp:,}"


# ─── 开启/结束工会战（管理员） ──────────────────────────────────────────────

start_gw = on_command("开启工会战", aliases={"开启公会战"}, permission=SUPERUSER, block=True)

@start_gw.handle()
async def handle_start_gw(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    status = await create_boss_status(group_id)
    await clear_queue(group_id)
    await clear_reservations(group_id)
    stage = get_boss_stage(status.round_num)
    await start_gw.finish(
        f"⚔️ 工会战开始！\n"
        f"当前BOSS：{stage.name}\n"
        f"血量：{_fmt_hp(status.current_hp)}\n"
        f"每人每天最多 {MAX_KNIVES_PER_DAY} 刀，加油！"
    )


end_gw = on_command("结束工会战", aliases={"结束公会战"}, permission=SUPERUSER, block=True)

@end_gw.handle()
async def handle_end_gw(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await end_gw.finish("当前没有进行中的工会战。")
    status.is_active = False
    await update_boss_status(status)
    await clear_queue(group_id)
    await clear_reservations(group_id)
    await end_gw.finish("✅ 今日工会战结束，辛苦各位团员！")


# ─── BOSS 状态查询 ──────────────────────────────────────────────────────────

boss_status_cmd = on_command("boss状态", aliases={"BOSS状态", "boss", "BOSS"}, block=True)

@boss_status_cmd.handle()
async def handle_boss_status(event: GroupMessageEvent):
    group_id = str(event.group_id)
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await boss_status_cmd.finish("❌ 当前没有进行中的工会战，请管理员使用「开启工会战」。")
    stage = get_boss_stage(status.round_num)
    hp_pct = status.current_hp / status.max_hp * 100
    bar_len = int(hp_pct / 5)
    hp_bar = "█" * bar_len + "░" * (20 - bar_len)
    queue = await get_queue(group_id)
    res_text = f"\n━━━━━━━━━━━━━━\n📋 出刀队列：\n{format_queue(queue)}" if queue else ""
    next_res = await get_reservations(group_id, status.round_num + 1)
    if next_res:
        res_text += f"\n🔔 下一周目预约：{'、'.join(r.user_name for r in next_res)}"
    await boss_status_cmd.finish(
        f"⚔️ 第 {status.round_num} 周目\n"
        f"BOSS：{stage.name}\n"
        f"HP：{_fmt_hp(status.current_hp)} / {_fmt_hp(status.max_hp)}\n"
        f"[{hp_bar}] {hp_pct:.1f}%"
        f"{res_text}"
    )


# ─── 出刀（报刀 / 尾刀 / 补偿刀 / 连续刀） ───────────────────────────────────

KILL_WORDS = {"尾", "尾刀", "击杀", "杀", "死", "收尾"}
CONTINUE_WORDS = {"连", "连续", "连续刀"}
_UNITS = {"w": 10_000, "万": 10_000, "k": 1_000, "千": 1_000, "m": 1_000_000}


def _parse_damage(token: str) -> Optional[int]:
    """解析伤害：1234567 / 123.4w / 123万 / 1.2m / 500k"""
    token = token.lower().replace(",", "").replace("，", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([wk万千m]?)", token)
    if not m:
        return None
    return int(float(m.group(1)) * _UNITS.get(m.group(2), 1))


def _parse_knife_args(text: str):
    """返回 (伤害 or None, 是否击杀, 是否连续刀, 是否有无法识别的参数)"""
    damage, kill, cont, bad = None, False, False, False
    for token in text.split():
        if token in KILL_WORDS:
            kill = True
        elif token in CONTINUE_WORDS:
            cont = True
        elif (d := _parse_damage(token)) is not None:
            damage = d
        else:
            bad = True
    return damage, kill, cont, bad


KNIFE_USAGE = (
    "❌ 格式：报刀 <伤害> [连]\n"
    "例：报刀 1234567 / 报刀 123w / 尾刀（直接打死）\n"
    "末尾加「连」表示连续刀，不叫下一位"
)


async def _do_knife(matcher, event: GroupMessageEvent, text: str,
                    compensate: bool = False, kill: bool = False,
                    continuing: bool = False):
    group_id = str(event.group_id)
    member = await require_member(matcher, event)

    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await matcher.finish("❌ 当前没有进行中的工会战。")

    damage, kill_arg, cont_arg, bad = _parse_knife_args(text)
    kill = kill or kill_arg
    continuing = continuing or cont_arg
    if bad or (damage is None and not kill):
        await matcher.finish(KNIFE_USAGE)
    if kill:
        damage = status.current_hp

    # 与PCR相同：尾刀获得补偿刀后，下一刀必定是补偿刀
    auto_comp = False
    if not compensate and await get_compensate_count(member.id, group_id) > 0:
        compensate = auto_comp = True

    # 检查刀数
    today_records = await get_member_today_records(member.id, group_id)
    normal_used = sum(1 for r in today_records
                      if r.knife_type in (KnifeType.NORMAL, KnifeType.TAIL))
    if compensate:
        if not await use_compensate_knife(member.id, group_id):
            await matcher.finish("❌ 你今日没有可用的补偿刀。")
    elif normal_used >= MAX_KNIVES_PER_DAY:
        comp = await get_compensate_count(member.id, group_id)
        hint = "（你有补偿刀未使用，请用「补偿刀 <伤害>」）" if comp > 0 else ""
        await matcher.finish(
            f"❌ 今日普通刀已用完（{MAX_KNIVES_PER_DAY}/{MAX_KNIVES_PER_DAY}）{hint}"
        )

    is_kill = damage >= status.current_hp
    actual_damage = min(damage, status.current_hp)
    hp_after = status.current_hp - actual_damage
    if compensate:
        knife_type = KnifeType.COMPENSATE
    else:
        knife_type = KnifeType.TAIL if is_kill else KnifeType.NORMAL
        normal_used += 1

    await add_knife_record(KnifeRecord(
        id=None, user_id=str(event.user_id), member_id=member.id,
        user_name=member.name, group_id=group_id, damage=actual_damage,
        knife_type=knife_type, boss_round=status.round_num,
        boss_hp_before=status.current_hp, boss_hp_after=hp_after,
        date=date.today().isoformat()
    ))

    label = "补偿刀（自动）" if auto_comp else ("补偿刀" if compensate else "出刀")
    if is_kill:
        got_comp = ENABLE_COMPENSATE_KNIFE and not compensate  # 补偿刀击杀不再给补偿刀
        if got_comp:
            await add_compensate_knife(member.id, group_id)
        status.round_num += 1
        new_stage = get_boss_stage(status.round_num)
        status.current_hp = new_stage.hp
        status.max_hp = new_stage.hp
        await update_boss_status(status)
        text_out = (
            f"💥 【击杀！】{member.name} {label}击杀BOSS！\n"
            f"伤害：{_fmt_hp(actual_damage)}"
            + ("\n🎁 获得一次补偿刀！" if got_comp else "") +
            f"\n━━━━━━━━━━━━━━\n"
            f"➡️ 进入第 {status.round_num} 周目\n"
            f"BOSS：{new_stage.name}\n"
            f"HP：{_fmt_hp(new_stage.hp)}"
        )
    else:
        status.current_hp = hp_after
        await update_boss_status(status)
        hp_pct = hp_after / status.max_hp * 100
        text_out = (
            f"⚔️ {member.name} {label}！\n"
            f"伤害：{_fmt_hp(actual_damage)}\n"
            f"BOSS剩余HP：{_fmt_hp(hp_after)}（{hp_pct:.1f}%）"
        )

    comp_left = await get_compensate_count(member.id, group_id)
    text_out += f"\n今日剩余：普通刀 {MAX_KNIVES_PER_DAY - normal_used} 刀"
    if comp_left:
        text_out += f"，补偿刀 {comp_left} 刀"

    notice = await after_knife(member, group_id, continuing)
    await matcher.finish(Message(text_out) + notice)


report_knife = on_command("报刀", aliases={"出刀"}, block=True)

@report_knife.handle()
async def handle_report_knife(event: GroupMessageEvent, args: Message = CommandArg()):
    await _do_knife(report_knife, event, args.extract_plain_text())


tail_knife = on_command("尾刀", aliases={"击杀", "收尾"}, block=True)

@tail_knife.handle()
async def handle_tail_knife(event: GroupMessageEvent, args: Message = CommandArg()):
    await _do_knife(tail_knife, event, args.extract_plain_text(), kill=True)


continue_knife = on_command("连续刀", block=True)

@continue_knife.handle()
async def handle_continue_knife(event: GroupMessageEvent, args: Message = CommandArg()):
    await _do_knife(continue_knife, event, args.extract_plain_text(), continuing=True)


compensate_knife = on_command("补偿刀", block=True)

@compensate_knife.handle()
async def handle_compensate(event: GroupMessageEvent, args: Message = CommandArg()):
    await _do_knife(compensate_knife, event, args.extract_plain_text(), compensate=True)


# ─── 撤刀 ───────────────────────────────────────────────────────────────────

undo_knife = on_command("撤刀", block=True)

@undo_knife.handle()
async def handle_undo(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    member = await require_member(undo_knife, event)

    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await undo_knife.finish("❌ 当前没有进行中的工会战。")

    record = await delete_last_knife(member.id, group_id)
    if not record:
        await undo_knife.finish("❌ 今日没有可撤销的出刀记录。")

    # 补偿刀归还；尾刀撤销则收回因此获得的补偿刀
    if record.knife_type == KnifeType.COMPENSATE:
        await add_compensate_knife(member.id, group_id)
    elif record.knife_type == KnifeType.TAIL and ENABLE_COMPENSATE_KNIFE:
        await use_compensate_knife(member.id, group_id)

    # 回滚BOSS：同周目直接恢复血量；击杀刀且新BOSS还没人打过则退回上一周目
    note = ""
    if record.boss_round == status.round_num:
        status.current_hp = record.boss_hp_before
        await update_boss_status(status)
    elif (record.boss_hp_after == 0 and status.round_num == record.boss_round + 1
          and status.current_hp == status.max_hp):
        status.round_num = record.boss_round
        status.max_hp = get_boss_stage(status.round_num).hp
        status.current_hp = record.boss_hp_before
        await update_boss_status(status)
    else:
        note = "\n⚠️ BOSS已被后续出刀推进，血量未回滚，请管理员核对"

    type_name = {KnifeType.NORMAL: "普通刀", KnifeType.TAIL: "尾刀",
                 KnifeType.COMPENSATE: "补偿刀"}[record.knife_type]
    await undo_knife.finish(
        f"↩️ 已撤销 {record.user_name} 的{type_name}\n"
        f"伤害：{_fmt_hp(record.damage)}\n"
        f"当前：第 {status.round_num} 周目，HP {_fmt_hp(status.current_hp)}"
        f"{note}"
    )


# ─── 出刀进度查询 ────────────────────────────────────────────────────────────

progress_cmd = on_command("出刀进度", aliases={"进度", "查进度"}, block=True)

@progress_cmd.handle()
async def handle_progress(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    summaries = await get_today_summary(group_id)

    if not summaries:
        await progress_cmd.finish("暂无注册成员，请成员先发送「注册 <游戏名>」。")

    lines = ["📊 今日出刀进度：\n"]
    total_damage = 0
    for s in summaries:
        knife_used = s.normal_count + s.tail_count
        icons = ("⚔️" * knife_used + "🎁" * s.compensate_count) or "未出刀"
        comp_hint = " [有补偿刀]" if s.has_compensate_left else ""
        lines.append(
            f"{s.user_name}：{icons} {_fmt_hp(s.total_damage)}{comp_hint}"
        )
        total_damage += s.total_damage

    lines.append(f"\n合计总伤害：{_fmt_hp(total_damage)}")
    await progress_cmd.finish("\n".join(lines))


# ─── 今日图表汇总 ────────────────────────────────────────────────────────────

chart_cmd = on_command("今日汇总", aliases={"汇总", "图表"}, block=True)

@chart_cmd.handle()
async def handle_chart(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    summaries = await get_today_summary(group_id)

    if not summaries:
        await chart_cmd.finish("暂无注册成员，无法生成汇总。")

    status = await get_boss_status(group_id)
    round_num = status.round_num if status else 1

    img_path = await generate_daily_chart(summaries, round_num, group_id)
    await bot.send_group_msg(
        group_id=event.group_id,
        message=MessageSegment.image(img_path.read_bytes())
    )


# ─── 催刀（手动） ────────────────────────────────────────────────────────────

remind_cmd = on_command("催刀", permission=SUPERUSER, block=True)

@remind_cmd.handle()
async def handle_remind(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    from .scheduler import send_remind
    await send_remind(bot, group_id)
