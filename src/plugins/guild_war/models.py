"""数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class KnifeType(str, Enum):
    NORMAL = "normal"          # 普通刀
    TAIL = "tail"              # 尾刀（击杀BOSS）
    COMPENSATE = "compensate"  # 补偿刀（尾刀后获得）


@dataclass
class KnifeRecord:
    """单次出刀记录"""
    id: Optional[int]
    user_id: str           # QQ号
    user_name: str         # 昵称
    group_id: str          # 群号
    damage: int            # 伤害值
    knife_type: KnifeType  # 刀类型
    boss_round: int        # 打的是第几周目BOSS
    boss_hp_before: int    # 打之前BOSS血量
    boss_hp_after: int     # 打之后BOSS血量（0代表击杀）
    date: str              # 日期 YYYY-MM-DD
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class BossStatus:
    """当前BOSS状态"""
    group_id: str
    round_num: int         # 当前周目
    current_hp: int        # 当前血量
    max_hp: int            # 本周目满血
    is_active: bool        # 工会战是否进行中
    date: str              # 开始日期


@dataclass
class Reservation:
    """BOSS预约"""
    id: Optional[int]
    user_id: str
    user_name: str
    group_id: str
    boss_round: int        # 预约的周目
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class UserDailySummary:
    """用户当日汇总"""
    user_id: str
    user_name: str
    normal_count: int       # 普通刀数
    tail_count: int         # 尾刀数
    compensate_count: int   # 补偿刀数
    total_damage: int       # 总伤害
    has_compensate_left: bool  # 是否有未用补偿刀
