"""
工会战配置文件
修改此文件来适配你的游戏规则
"""

from dataclasses import dataclass
from typing import List


@dataclass
class BossStage:
    """单个阶段的BOSS配置"""
    name: str          # BOSS名称
    hp: int            # 血量
    round_start: int   # 从第几周目开始适用此阶段


# 同盟战的“第几只”不等于游戏显示的 Lv。
# Wiki 确认第 40 只达到 Lv120，此后等级不变。
# 末段 HP 为用户于 2026-09-25 提供的记忆值，尚未独立核实。
# 1～39 只缺少可靠数据，不沿用原来虚构的五段示例。
# 可补充已核实的数据，或在群内由管理员使用“设置BOSS”校准。
BOSS_HP_BY_ROUND: dict[int, int] = {40: 10_250_000_000}
BOSS_REPEAT_FROM = 40

# 每人每天刀数上限
MAX_KNIVES_PER_DAY: int = 3

# 是否允许尾刀后获得补偿刀
ENABLE_COMPENSATE_KNIFE: bool = True

# 工会成员总人数（用于催刀统计）
GUILD_MEMBER_COUNT: int = 30

# 催刀时间配置（24小时制）
REMIND_TIMES: List[tuple] = [
    (20, 0),   # 20:00
    (22, 0),   # 22:00
]

# 图表颜色配置
CHART_COLORS = {
    "done": "#4ade80",        # 出完3刀 - 绿
    "partial": "#facc15",     # 未出完 - 黄
    "zero": "#f87171",        # 未出刀 - 红
    "compensate": "#60a5fa",  # 有补偿刀 - 蓝
    "background": "#1e1e2e",  # 背景色
    "text": "#cdd6f4",        # 文字色
}


def get_boss_stage(round_num: int) -> BossStage:
    """未知血量使用 0 哨兵；业务层必须先提示校准，不能报刀。"""
    if round_num < 1:
        raise ValueError("BOSS 序号必须为正数")
    key = min(round_num, BOSS_REPEAT_FROM)
    hp = BOSS_HP_BY_ROUND.get(key, 0)
    name = f"同盟战第 {round_num} 只 BOSS"
    if round_num >= BOSS_REPEAT_FROM:
        name += "（Lv120，102.5亿为待核实记忆值）"
    if not hp:
        name += "（血量待配置）"
    return BossStage(name=name, hp=hp, round_start=round_num)
