"""工会战业务：只接收领域上下文并返回文字/图片，不依赖 QQ 适配器。"""

from datetime import date
from .config import MAX_KNIVES_PER_DAY, ENABLE_COMPENSATE_KNIFE
from .database import (
    get_boss_status,
    create_boss_status,
    update_boss_status,
    get_group_boss_stage,
    calibrate_boss,
    add_knife_record,
    get_user_today_records,
    delete_last_knife,
    add_compensate_knife,
    get_compensate_count,
    use_compensate_knife,
    add_reservation,
    cancel_reservation,
    get_reservations,
    clear_reservations_for_round,
    get_today_summary,
)
from .models import GuildContext, KnifeRecord, KnifeType, Reservation
from .chart import generate_daily_chart


def _fmt_hp(hp: int) -> str:
    """格式化血量显示"""
    if hp <= 0:
        return "待配置（请管理员使用「设置BOSS」）"
    if hp >= 100_000_000:
        return f"{hp / 100_000_000:.2f}亿"
    if hp >= 1000000:
        return f"{hp / 1000000:.2f}M"
    return f"{hp:,}"


async def handle_start_gw(ctx: GuildContext, args: str = ""):
    group_id = str(ctx.group_id)
    existing = await get_boss_status(group_id)
    if existing and existing.is_active:
        return "工会战已开启；如需校准当前进度，请使用「设置BOSS」。"
    try:
        status = await create_boss_status(group_id)
    except ValueError as exc:
        return str(exc)
    stage = await get_group_boss_stage(group_id, status.round_num)
    return f"⚔️ 工会战开始！\n当前BOSS：{stage.name}\n血量：{_fmt_hp(status.current_hp)}\n每人每天最多 {MAX_KNIVES_PER_DAY} 刀，加油！"


async def handle_calibrate_boss(ctx: GuildContext, args: str = "") -> str:
    parts = args.split()
    if len(parts) not in (2, 3) or any(
        not (p.isascii() and p.isdecimal() and len(p) <= 18) for p in parts
    ):
        return (
            "用法：设置BOSS <第几只> <满血> [剩余血量]，例如：设置BOSS 40 10250000000"
        )
    round_num, max_hp = map(int, parts[:2])
    current_hp = int(parts[2]) if len(parts) == 3 else max_hp
    if not (1 <= round_num <= 1_000_000 and 0 < current_hp <= max_hp):
        return "BOSS 序号须为 1～1000000；血量须为正整数，剩余血量不能大于满血。"
    await calibrate_boss(ctx.group_id, round_num, max_hp, current_hp)
    return (
        f"✅ 已校准第 {round_num} 只 BOSS：{current_hp:,} / {max_hp:,}。\n"
        "工会战已开启；已有报刀与刀数保留。第40只及以后的校准会更新本群末段血量。"
    )


async def handle_end_gw(ctx: GuildContext, args: str = ""):
    group_id = str(ctx.group_id)
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        return "当前没有进行中的工会战。"
    status.is_active = False
    await update_boss_status(status)
    return "✅ 今日工会战结束，辛苦各位团员！"


async def handle_boss_status(ctx: GuildContext, args: str = ""):
    group_id = str(ctx.group_id)
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        return "❌ 当前没有进行中的工会战，请管理员使用「开启工会战」。"
    stage = await get_group_boss_stage(group_id, status.round_num)
    if status.max_hp <= 0:
        return f"第 {status.round_num} 只 BOSS 血量待配置，请管理员使用「设置BOSS {status.round_num} <满血>」。"
    hp_pct = status.current_hp / status.max_hp * 100
    bar_len = int(hp_pct / 5)
    hp_bar = "█" * bar_len + "░" * (20 - bar_len)
    reservations = await get_reservations(group_id, status.round_num)
    res_text = ""
    if reservations:
        names = "、".join((r.user_name for r in reservations))
        res_text = f"\n📌 预约中：{names}"
    return f"⚔️ 第 {status.round_num} 只 BOSS\nBOSS：{stage.name}\nHP：{_fmt_hp(status.current_hp)} / {_fmt_hp(status.max_hp)}\n[{hp_bar}] {hp_pct:.1f}%{res_text}"


async def handle_report_knife(ctx: GuildContext, args: str = ""):
    group_id = str(ctx.group_id)
    user_id = str(ctx.user_id)
    user_name = ctx.user_name or str(ctx.user_id)
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        return "❌ 当前没有进行中的工会战。"
    if status.max_hp <= 0:
        return f"第 {status.round_num} 只 BOSS 血量待配置，请管理员使用「设置BOSS {status.round_num} <满血>」。"
    damage_str = args.strip()
    if not (
        damage_str.isascii()
        and damage_str.isdecimal()
        and len(damage_str) <= 18
        and int(damage_str) > 0
    ):
        return "❌ 请输入正确格式：报刀 <伤害值>\n例如：报刀 1234567"
    damage = int(damage_str)
    today_records = await get_user_today_records(user_id, group_id)
    normal_used = sum(
        (1 for r in today_records if r.knife_type in (KnifeType.NORMAL, KnifeType.TAIL))
    )
    if normal_used >= MAX_KNIVES_PER_DAY:
        comp = await get_compensate_count(user_id, group_id)
        hint = "（你有补偿刀未使用，请用「补偿刀 <伤害>」）" if comp > 0 else ""
        return f"❌ 今日普通刀已用完（{MAX_KNIVES_PER_DAY}/{MAX_KNIVES_PER_DAY}）{hint}"
    actual_damage = min(damage, status.current_hp)
    is_kill = damage >= status.current_hp
    hp_after = max(0, status.current_hp - damage)
    record = KnifeRecord(
        id=None,
        user_id=user_id,
        user_name=user_name,
        group_id=group_id,
        damage=actual_damage,
        knife_type=KnifeType.TAIL if is_kill else KnifeType.NORMAL,
        boss_round=status.round_num,
        boss_hp_before=status.current_hp,
        boss_hp_after=hp_after,
        date=date.today().isoformat(),
    )
    await add_knife_record(record)
    if is_kill:
        old_round = status.round_num
        status.round_num += 1
        new_stage = await get_group_boss_stage(group_id, status.round_num)
        status.current_hp = new_stage.hp
        status.max_hp = new_stage.hp
        await update_boss_status(status)
        await clear_reservations_for_round(group_id, old_round)
        if ENABLE_COMPENSATE_KNIFE:
            await add_compensate_knife(user_id, group_id)
        next_res = await get_reservations(group_id, status.round_num)
        res_notice = ""
        if next_res:
            at_list = "、".join(r.user_name for r in next_res)
            res_notice = f"\n\n📣 下一只 BOSS预约提醒：{at_list}"
        return (
            f"💥 【击杀！】{user_name} 尾刀击杀BOSS！\n伤害：{_fmt_hp(actual_damage)}\n{('🎁 获得一次补偿刀！' if ENABLE_COMPENSATE_KNIFE else '')}\n━━━━━━━━━━━━━━\n➡️ 进入第 {status.round_num} 只 BOSS\nBOSS：{new_stage.name}\nHP：{_fmt_hp(new_stage.hp)}"
            + res_notice
        )
    else:
        status.current_hp = hp_after
        await update_boss_status(status)
        hp_pct = hp_after / status.max_hp * 100
        normal_left = MAX_KNIVES_PER_DAY - (normal_used + 1)
        return f"⚔️ {user_name} 出刀！\n伤害：{_fmt_hp(actual_damage)}\nBOSS剩余HP：{_fmt_hp(hp_after)}（{hp_pct:.1f}%）\n今日剩余刀数：{normal_left} 刀"


async def handle_compensate(ctx: GuildContext, args: str = ""):
    group_id = str(ctx.group_id)
    user_id = str(ctx.user_id)
    user_name = ctx.user_name or str(ctx.user_id)
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        return "❌ 当前没有进行中的工会战。"
    if status.max_hp <= 0:
        return f"第 {status.round_num} 只 BOSS 血量待配置，请管理员使用「设置BOSS {status.round_num} <满血>」。"
    damage_str = args.strip()
    if not (
        damage_str.isascii()
        and damage_str.isdecimal()
        and len(damage_str) <= 18
        and int(damage_str) > 0
    ):
        return "❌ 请输入正确格式：补偿刀 <伤害值>"
    damage = int(damage_str)
    ok = await use_compensate_knife(user_id, group_id)
    if not ok:
        return "❌ 你今日没有可用的补偿刀。"
    actual_damage = min(damage, status.current_hp)
    is_kill = damage >= status.current_hp
    hp_after = max(0, status.current_hp - damage)
    record = KnifeRecord(
        id=None,
        user_id=user_id,
        user_name=user_name,
        group_id=group_id,
        damage=actual_damage,
        knife_type=KnifeType.COMPENSATE,
        boss_round=status.round_num,
        boss_hp_before=status.current_hp,
        boss_hp_after=hp_after,
        date=date.today().isoformat(),
    )
    await add_knife_record(record)
    if is_kill:
        old_round = status.round_num
        status.round_num += 1
        new_stage = await get_group_boss_stage(group_id, status.round_num)
        status.current_hp = new_stage.hp
        status.max_hp = new_stage.hp
        await update_boss_status(status)
        await clear_reservations_for_round(group_id, old_round)
        return f"💥 【补偿刀击杀！】{user_name}\n伤害：{_fmt_hp(actual_damage)}\n➡️ 进入第 {status.round_num} 只 BOSS\nBOSS：{new_stage.name}  HP：{_fmt_hp(new_stage.hp)}"
    else:
        status.current_hp = hp_after
        await update_boss_status(status)
        hp_pct = hp_after / status.max_hp * 100
        return f"🎁 {user_name} 使用补偿刀！\n伤害：{_fmt_hp(actual_damage)}\nBOSS剩余HP：{_fmt_hp(hp_after)}（{hp_pct:.1f}%）"


async def handle_undo(ctx: GuildContext, args: str = ""):
    group_id = str(ctx.group_id)
    user_id = str(ctx.user_id)
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        return "❌ 当前没有进行中的工会战。"
    record = await delete_last_knife(user_id, group_id)
    if not record:
        return "❌ 今日没有可撤销的出刀记录。"
    if record.boss_round == status.round_num:
        status.current_hp = record.boss_hp_before
        await update_boss_status(status)
    return f"↩️ 已撤销 {record.user_name} 的出刀记录\n伤害：{_fmt_hp(record.damage)}（{record.knife_type.value}）\nBOSS血量已恢复：{_fmt_hp(status.current_hp)}"


async def handle_reserve(ctx: GuildContext, args: str = ""):
    group_id = str(ctx.group_id)
    user_id = str(ctx.user_id)
    user_name = ctx.user_name or str(ctx.user_id)
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        return "❌ 当前没有进行中的工会战。"
    res = Reservation(
        id=None,
        user_id=user_id,
        user_name=user_name,
        group_id=group_id,
        boss_round=status.round_num,
    )
    ok = await add_reservation(res)
    if not ok:
        return f"❌ 你已经预约了第 {status.round_num} 只 BOSS。"
    reservations = await get_reservations(group_id, status.round_num)
    names = "、".join((r.user_name for r in reservations))
    return (
        f"📌 {user_name} 预约了第 {status.round_num} 只 BOSS！\n当前预约名单：{names}"
    )


async def handle_cancel_reserve(ctx: GuildContext, args: str = ""):
    group_id = str(ctx.group_id)
    user_id = str(ctx.user_id)
    status = await get_boss_status(group_id)
    if not status:
        return "❌ 当前没有进行中的工会战。"
    ok = await cancel_reservation(user_id, group_id, status.round_num)
    if not ok:
        return "❌ 你没有预约当前BOSS。"
    return "✅ 已取消预约。"


async def handle_progress(ctx: GuildContext, args: str = ""):
    group_id = str(ctx.group_id)
    summaries = await get_today_summary(group_id)
    if not summaries:
        return "今日暂无出刀记录。"
    lines = ["📊 今日出刀进度：\n"]
    total_damage = 0
    for s in summaries:
        knife_used = s.normal_count + s.tail_count
        icons = "⚔️" * knife_used + "🎁" * s.compensate_count
        comp_hint = " [有补偿刀]" if s.has_compensate_left else ""
        lines.append(f"{s.user_name}：{icons} {_fmt_hp(s.total_damage)}{comp_hint}")
        total_damage += s.total_damage
    lines.append(f"\n合计总伤害：{_fmt_hp(total_damage)}")
    return "\n".join(lines)


async def handle_chart(ctx: GuildContext, args: str = ""):
    group_id = str(ctx.group_id)
    summaries = await get_today_summary(group_id)
    if not summaries:
        return "今日暂无出刀记录，无法生成汇总。"
    status = await get_boss_status(group_id)
    round_num = status.round_num if status else 1
    img_path = await generate_daily_chart(summaries, round_num, group_id)
    return img_path.read_bytes()


async def handle_remind(ctx: GuildContext, args: str = "") -> str:
    return await build_reminder(ctx.group_id)


async def build_reminder(group_id: str) -> str:
    status = await get_boss_status(group_id)
    if not status or not status.is_active:
        return "当前没有进行中的工会战。"
    summaries = await get_today_summary(group_id)
    if not summaries:
        return "今日暂无出刀记录，请团员及时报刀。尚未登记完整成员名单。"
    lines = ["⏰ 今日已报刀成员的剩余出刀情况："]
    for s in summaries:
        left = MAX_KNIVES_PER_DAY - s.normal_count - s.tail_count
        if left > 0 or s.has_compensate_left:
            hint = "，有补偿刀" if s.has_compensate_left else ""
            lines.append(f"· {s.user_name}：剩余 {left} 刀{hint}")
    if len(lines) == 1:
        lines.append("已报刀成员均已完成。")
    lines.append("仅统计今日已报刀成员，零出刀成员需自行核对。")
    return "\n".join(lines)
