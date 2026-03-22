"""指令处理器 - 所有QQ群指令的响应逻辑"""

from datetime import datetime, date
from nonebot import on_command, on_regex
from nonebot.adapters.onebot.v11 import (
    Bot, GroupMessageEvent, Message, MessageSegment
)
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.rule import to_me

from .config import (
    MAX_KNIVES_PER_DAY, get_boss_stage, ENABLE_COMPENSATE_KNIFE
)
from .database import (
    get_boss_status, create_boss_status, update_boss_status,
    add_knife_record, get_user_today_records, delete_last_knife,
    add_compensate_knife, get_compensate_count, use_compensate_knife,
    add_reservation, cancel_reservation, get_reservations,
    clear_reservations_for_round, get_today_summary
)
from .models import KnifeRecord, KnifeType, Reservation
from .chart import generate_daily_chart


def _fmt_hp(hp: int) -> str:
    """格式化血量显示"""
    if hp >= 1_000_000:
        return f"{hp/1_000_000:.2f}M"
    return f"{hp:,}"


def _format_knife_count(records) -> str:
    normal = sum(1 for r in records if r.knife_type in (KnifeType.NORMAL, KnifeType.TAIL))
    comp = sum(1 for r in records if r.knife_type == KnifeType.COMPENSATE)
    return f"普通刀{normal}/{MAX_KNIVES_PER_DAY}"


# ─── 开启/结束工会战（管理员） ──────────────────────────────────────────────

start_gw = on_command("开启工会战", permission=SUPERUSER, block=True)

@start_gw.handle()
async def handle_start_gw(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    status = await create_boss_status(group_id)
    stage = get_boss_stage(status.round_num)
    await start_gw.finish(
        f"⚔️ 工会战开始！\n"
        f"当前BOSS：{stage.name}\n"
        f"血量：{_fmt_hp(status.current_hp)}\n"
        f"每人每天最多 {MAX_KNIVES_PER_DAY} 刀，加油！"
    )


end_gw = on_command("结束工会战", permission=SUPERUSER, block=True)

@end_gw.handle()
async def handle_end_gw(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await end_gw.finish("当前没有进行中的工会战。")
    status.is_active = False
    await update_boss_status(status)
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
    reservations = await get_reservations(group_id, status.round_num)
    res_text = ""
    if reservations:
        names = "、".join(r.user_name for r in reservations)
        res_text = f"\n📌 预约中：{names}"
    await boss_status_cmd.finish(
        f"⚔️ 第 {status.round_num} 周目\n"
        f"BOSS：{stage.name}\n"
        f"HP：{_fmt_hp(status.current_hp)} / {_fmt_hp(status.max_hp)}\n"
        f"[{hp_bar}] {hp_pct:.1f}%"
        f"{res_text}"
    )


# ─── 报刀（普通刀） ─────────────────────────────────────────────────────────

report_knife = on_command("报刀", block=True)

@report_knife.handle()
async def handle_report_knife(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    user_name = event.sender.nickname or str(event.user_id)

    # 检查工会战状态
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await report_knife.finish("❌ 当前没有进行中的工会战。")

    # 解析伤害
    damage_str = args.extract_plain_text().strip()
    if not damage_str.isdigit():
        await report_knife.finish("❌ 请输入正确格式：报刀 <伤害值>\n例如：报刀 1234567")
    damage = int(damage_str)

    # 检查刀数
    today_records = await get_user_today_records(user_id, group_id)
    normal_used = sum(1 for r in today_records if r.knife_type in (KnifeType.NORMAL, KnifeType.TAIL))
    if normal_used >= MAX_KNIVES_PER_DAY:
        comp = await get_compensate_count(user_id, group_id)
        hint = "（你有补偿刀未使用，请用「补偿刀 <伤害>」）" if comp > 0 else ""
        await report_knife.finish(f"❌ 今日普通刀已用完（{MAX_KNIVES_PER_DAY}/{MAX_KNIVES_PER_DAY}）{hint}")

    # 检查伤害是否超过BOSS血量
    actual_damage = min(damage, status.current_hp)
    is_kill = damage >= status.current_hp

    hp_after = max(0, status.current_hp - damage)

    # 写入记录
    record = KnifeRecord(
        id=None, user_id=user_id, user_name=user_name,
        group_id=group_id, damage=actual_damage,
        knife_type=KnifeType.TAIL if is_kill else KnifeType.NORMAL,
        boss_round=status.round_num,
        boss_hp_before=status.current_hp,
        boss_hp_after=hp_after,
        date=date.today().isoformat()
    )
    await add_knife_record(record)

    if is_kill:
        # 击杀BOSS
        old_round = status.round_num
        status.round_num += 1
        new_stage = get_boss_stage(status.round_num)
        status.current_hp = new_stage.hp
        status.max_hp = new_stage.hp
        await update_boss_status(status)
        await clear_reservations_for_round(group_id, old_round)

        # 给予补偿刀
        if ENABLE_COMPENSATE_KNIFE:
            await add_compensate_knife(user_id, group_id)

        # 通知预约了下一周目的成员
        next_res = await get_reservations(group_id, status.round_num)
        res_notice = ""
        if next_res:
            at_list = "".join(str(MessageSegment.at(r.user_id)) for r in next_res)
            res_notice = f"\n\n📣 下一周目预约提醒：{at_list}"

        await report_knife.finish(
            f"💥 【击杀！】{user_name} 尾刀击杀BOSS！\n"
            f"伤害：{_fmt_hp(actual_damage)}\n"
            f"{'🎁 获得一次补偿刀！' if ENABLE_COMPENSATE_KNIFE else ''}\n"
            f"━━━━━━━━━━━━━━\n"
            f"➡️ 进入第 {status.round_num} 周目\n"
            f"BOSS：{new_stage.name}\n"
            f"HP：{_fmt_hp(new_stage.hp)}"
            + res_notice
        )
    else:
        # 普通伤害
        status.current_hp = hp_after
        await update_boss_status(status)
        stage = get_boss_stage(status.round_num)
        hp_pct = hp_after / status.max_hp * 100
        normal_left = MAX_KNIVES_PER_DAY - (normal_used + 1)
        await report_knife.finish(
            f"⚔️ {user_name} 出刀！\n"
            f"伤害：{_fmt_hp(actual_damage)}\n"
            f"BOSS剩余HP：{_fmt_hp(hp_after)}（{hp_pct:.1f}%）\n"
            f"今日剩余刀数：{normal_left} 刀"
        )


# ─── 补偿刀 ─────────────────────────────────────────────────────────────────

compensate_knife = on_command("补偿刀", block=True)

@compensate_knife.handle()
async def handle_compensate(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    user_name = event.sender.nickname or str(event.user_id)

    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await compensate_knife.finish("❌ 当前没有进行中的工会战。")

    damage_str = args.extract_plain_text().strip()
    if not damage_str.isdigit():
        await compensate_knife.finish("❌ 请输入正确格式：补偿刀 <伤害值>")
    damage = int(damage_str)

    # 消耗补偿刀
    ok = await use_compensate_knife(user_id, group_id)
    if not ok:
        await compensate_knife.finish("❌ 你今日没有可用的补偿刀。")

    actual_damage = min(damage, status.current_hp)
    is_kill = damage >= status.current_hp
    hp_after = max(0, status.current_hp - damage)

    record = KnifeRecord(
        id=None, user_id=user_id, user_name=user_name,
        group_id=group_id, damage=actual_damage,
        knife_type=KnifeType.COMPENSATE,
        boss_round=status.round_num,
        boss_hp_before=status.current_hp,
        boss_hp_after=hp_after,
        date=date.today().isoformat()
    )
    await add_knife_record(record)

    if is_kill:
        old_round = status.round_num
        status.round_num += 1
        new_stage = get_boss_stage(status.round_num)
        status.current_hp = new_stage.hp
        status.max_hp = new_stage.hp
        await update_boss_status(status)
        await clear_reservations_for_round(group_id, old_round)
        # 补偿刀击杀不给新补偿刀

        await compensate_knife.finish(
            f"💥 【补偿刀击杀！】{user_name}\n"
            f"伤害：{_fmt_hp(actual_damage)}\n"
            f"➡️ 进入第 {status.round_num} 周目\n"
            f"BOSS：{new_stage.name}  HP：{_fmt_hp(new_stage.hp)}"
        )
    else:
        status.current_hp = hp_after
        await update_boss_status(status)
        hp_pct = hp_after / status.max_hp * 100
        await compensate_knife.finish(
            f"🎁 {user_name} 使用补偿刀！\n"
            f"伤害：{_fmt_hp(actual_damage)}\n"
            f"BOSS剩余HP：{_fmt_hp(hp_after)}（{hp_pct:.1f}%）"
        )


# ─── 撤刀 ───────────────────────────────────────────────────────────────────

undo_knife = on_command("撤刀", block=True)

@undo_knife.handle()
async def handle_undo(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)

    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await undo_knife.finish("❌ 当前没有进行中的工会战。")

    record = await delete_last_knife(user_id, group_id)
    if not record:
        await undo_knife.finish("❌ 今日没有可撤销的出刀记录。")

    # 回滚BOSS血量（简单处理：仅撤销当前周目的刀）
    if record.boss_round == status.round_num:
        status.current_hp = record.boss_hp_before
        await update_boss_status(status)

    # 如果撤的是尾刀还需要归还补偿刀（逻辑简化：不处理跨周目）
    await undo_knife.finish(
        f"↩️ 已撤销 {record.user_name} 的出刀记录\n"
        f"伤害：{_fmt_hp(record.damage)}（{record.knife_type.value}）\n"
        f"BOSS血量已恢复：{_fmt_hp(status.current_hp)}"
    )


# ─── 预约 ───────────────────────────────────────────────────────────────────

reserve_cmd = on_command("预约", block=True)

@reserve_cmd.handle()
async def handle_reserve(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    user_name = event.sender.nickname or str(event.user_id)

    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        await reserve_cmd.finish("❌ 当前没有进行中的工会战。")

    res = Reservation(
        id=None, user_id=user_id, user_name=user_name,
        group_id=group_id, boss_round=status.round_num
    )
    ok = await add_reservation(res)
    if not ok:
        await reserve_cmd.finish(f"❌ 你已经预约了第 {status.round_num} 周目的BOSS。")

    reservations = await get_reservations(group_id, status.round_num)
    names = "、".join(r.user_name for r in reservations)
    await reserve_cmd.finish(
        f"📌 {user_name} 预约了第 {status.round_num} 周目 BOSS！\n"
        f"当前预约名单：{names}"
    )


cancel_reserve_cmd = on_command("取消预约", block=True)

@cancel_reserve_cmd.handle()
async def handle_cancel_reserve(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)

    status = await get_boss_status(group_id)
    if not status:
        await cancel_reserve_cmd.finish("❌ 当前没有进行中的工会战。")

    ok = await cancel_reservation(user_id, group_id, status.round_num)
    if not ok:
        await cancel_reserve_cmd.finish("❌ 你没有预约当前BOSS。")
    await cancel_reserve_cmd.finish("✅ 已取消预约。")


# ─── 出刀进度查询 ────────────────────────────────────────────────────────────

progress_cmd = on_command("出刀进度", aliases={"进度", "查进度"}, block=True)

@progress_cmd.handle()
async def handle_progress(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    summaries = await get_today_summary(group_id)

    if not summaries:
        await progress_cmd.finish("今日暂无出刀记录。")

    lines = ["📊 今日出刀进度：\n"]
    total_damage = 0
    for s in summaries:
        knife_used = s.normal_count + s.tail_count
        icons = "⚔️" * knife_used + "🎁" * s.compensate_count
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
        await chart_cmd.finish("今日暂无出刀记录，无法生成汇总。")

    status = await get_boss_status(group_id)
    round_num = status.round_num if status else 1

    img_path = await generate_daily_chart(summaries, round_num, group_id)
    await bot.send_group_msg(
        group_id=event.group_id,
        message=MessageSegment.image(f"file:///{img_path.absolute()}")
    )


# ─── 催刀（手动） ────────────────────────────────────────────────────────────

remind_cmd = on_command("催刀", permission=SUPERUSER, block=True)

@remind_cmd.handle()
async def handle_remind(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    from .scheduler import send_remind
    await send_remind(bot, group_id)
