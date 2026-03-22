"""
工会战配置文件
修改此文件来适配你的游戏规则
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class BossStage:
    """单个阶段的BOSS配置"""
    name: str          # BOSS名称
    hp: int            # 血量
    round_start: int   # 从第几周目开始适用此阶段


# =============================================
# 在此处配置你的游戏BOSS数据
# 示例为5阶段，每阶段血量递增
# =============================================
BOSS_STAGES: List[BossStage] = [
    BossStage(name="阶段一·混沌核心", hp=6_000_000,  round_start=1),
    BossStage(name="阶段二·混沌核心", hp=8_000_000,  round_start=4),
    BossStage(name="阶段三·混沌核心", hp=10_000_000, round_start=7),
    BossStage(name="阶段四·混沌核心", hp=12_000_000, round_start=11),
    BossStage(name="阶段五·混沌核心", hp=15_000_000, round_start=16),
]

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
    """根据周目数获取当前BOSS阶段配置"""
    current = BOSS_STAGES[0]
    for stage in BOSS_STAGES:
        if round_num >= stage.round_start:
            current = stage
    return current
