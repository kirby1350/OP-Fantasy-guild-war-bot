"""数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class KnifeType(str, Enum):
    NORMAL = "normal"          # 普通刀
    TAIL = "tail"              # 尾刀（击杀BOSS）
    COMPENSATE = "compensate"  # 补偿刀（尾刀后获得）


@dataclass
class Member:
    """已注册的工会成员，可绑定多个QQ号"""
    id: int
    group_id: str
    name: str
    user_ids: List[str]


@dataclass
class Homework:
    """作业（攻略图）"""
    id: int
    group_id: str
    title: str
    image_paths: List[str]
    uploader_id: str
    created_at: datetime


@dataclass
class KnifeRecord:
    """单次出刀记录"""
    id: Optional[int]
    user_id: str           # 实际报刀的QQ号
    member_id: int         # 所属成员（多个QQ号可属于同一成员）
    user_name: str         # 成员名
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
    member_id: int
    user_name: str
    group_id: str
    boss_round: int        # 预约的周目
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class UserDailySummary:
    """成员当日汇总"""
    member_id: int
    user_name: str
    user_ids: List[str]     # 该成员绑定的全部QQ号（用于@）
    normal_count: int       # 普通刀数
    tail_count: int         # 尾刀数
    compensate_count: int   # 补偿刀数
    total_damage: int       # 总伤害
    has_compensate_left: bool  # 是否有未用补偿刀
