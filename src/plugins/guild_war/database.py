"""SQLite 数据库操作层"""

import aiosqlite
from datetime import date
from pathlib import Path
from typing import List, Optional

from .models import KnifeRecord, KnifeType, BossStatus, Reservation, UserDailySummary
from .config import MAX_KNIVES_PER_DAY, get_boss_stage, BOSS_STAGES

DB_PATH = Path("data/guild_war.db")


async def init_db():
    """初始化数据库，创建表"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS knife_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                group_id TEXT NOT NULL,
                damage INTEGER NOT NULL,
                knife_type TEXT NOT NULL,
                boss_round INTEGER NOT NULL,
                boss_hp_before INTEGER NOT NULL,
                boss_hp_after INTEGER NOT NULL,
                date TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS boss_status (
                group_id TEXT PRIMARY KEY,
                round_num INTEGER NOT NULL DEFAULT 1,
                current_hp INTEGER NOT NULL,
                max_hp INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                date TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                group_id TEXT NOT NULL,
                boss_round INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, group_id, boss_round)
            );

            CREATE TABLE IF NOT EXISTS compensate_knives (
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                date TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, group_id, date)
            );
        """)
        await db.commit()


# ─── Boss Status ────────────────────────────────────────────────────────────

async def get_boss_status(group_id: str) -> Optional[BossStatus]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT group_id, round_num, current_hp, max_hp, is_active, date FROM boss_status WHERE group_id=?",
            (group_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return BossStatus(
                group_id=row[0], round_num=row[1], current_hp=row[2],
                max_hp=row[3], is_active=bool(row[4]), date=row[5]
            )


async def create_boss_status(group_id: str) -> BossStatus:
    """初始化工会战（第1周目，满血）"""
    stage = get_boss_stage(1)
    today = date.today().isoformat()
    status = BossStatus(
        group_id=group_id, round_num=1, current_hp=stage.hp,
        max_hp=stage.hp, is_active=True, date=today
    )
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO boss_status
            (group_id, round_num, current_hp, max_hp, is_active, date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (group_id, status.round_num, status.current_hp,
              status.max_hp, 1, today))
        await db.commit()
    return status


async def update_boss_status(status: BossStatus):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE boss_status SET round_num=?, current_hp=?, max_hp=?, is_active=?, date=?
            WHERE group_id=?
        """, (status.round_num, status.current_hp, status.max_hp,
              int(status.is_active), status.date, status.group_id))
        await db.commit()


# ─── Knife Records ──────────────────────────────────────────────────────────

async def add_knife_record(record: KnifeRecord) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO knife_records
            (user_id, user_name, group_id, damage, knife_type, boss_round,
             boss_hp_before, boss_hp_after, date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (record.user_id, record.user_name, record.group_id,
              record.damage, record.knife_type.value, record.boss_round,
              record.boss_hp_before, record.boss_hp_after,
              record.date, record.created_at.isoformat()))
        await db.commit()
        return cursor.lastrowid


async def get_user_today_records(user_id: str, group_id: str) -> List[KnifeRecord]:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, user_id, user_name, group_id, damage, knife_type,
                   boss_round, boss_hp_before, boss_hp_after, date, created_at
            FROM knife_records
            WHERE user_id=? AND group_id=? AND date=?
            ORDER BY created_at
        """, (user_id, group_id, today)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_knife(r) for r in rows]


async def delete_last_knife(user_id: str, group_id: str) -> Optional[KnifeRecord]:
    """撤销最近一刀，返回被撤销的记录"""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, user_id, user_name, group_id, damage, knife_type,
                   boss_round, boss_hp_before, boss_hp_after, date, created_at
            FROM knife_records
            WHERE user_id=? AND group_id=? AND date=?
            ORDER BY created_at DESC LIMIT 1
        """, (user_id, group_id, today)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        record = _row_to_knife(row)
        await db.execute("DELETE FROM knife_records WHERE id=?", (row[0],))
        await db.commit()
        return record


async def get_today_all_records(group_id: str) -> List[KnifeRecord]:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, user_id, user_name, group_id, damage, knife_type,
                   boss_round, boss_hp_before, boss_hp_after, date, created_at
            FROM knife_records WHERE group_id=? AND date=?
            ORDER BY created_at
        """, (group_id, today)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_knife(r) for r in rows]


def _row_to_knife(row) -> KnifeRecord:
    from datetime import datetime
    return KnifeRecord(
        id=row[0], user_id=row[1], user_name=row[2], group_id=row[3],
        damage=row[4], knife_type=KnifeType(row[5]), boss_round=row[6],
        boss_hp_before=row[7], boss_hp_after=row[8], date=row[9],
        created_at=datetime.fromisoformat(row[10])
    )


# ─── Compensate Knives ──────────────────────────────────────────────────────

async def add_compensate_knife(user_id: str, group_id: str):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO compensate_knives (user_id, group_id, date, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id, group_id, date) DO UPDATE SET count = count + 1
        """, (user_id, group_id, today))
        await db.commit()


async def get_compensate_count(user_id: str, group_id: str) -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT count FROM compensate_knives WHERE user_id=? AND group_id=? AND date=?",
            (user_id, group_id, today)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def use_compensate_knife(user_id: str, group_id: str) -> bool:
    """消耗一次补偿刀，返回是否成功"""
    count = await get_compensate_count(user_id, group_id)
    if count <= 0:
        return False
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE compensate_knives SET count = count - 1
            WHERE user_id=? AND group_id=? AND date=?
        """, (user_id, group_id, today))
        await db.commit()
    return True


# ─── Reservations ───────────────────────────────────────────────────────────

async def add_reservation(res: Reservation) -> bool:
    """添加预约，返回是否成功（False表示已预约）"""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("""
                INSERT INTO reservations (user_id, user_name, group_id, boss_round, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (res.user_id, res.user_name, res.group_id,
                  res.boss_round, res.created_at.isoformat()))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def cancel_reservation(user_id: str, group_id: str, boss_round: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            DELETE FROM reservations WHERE user_id=? AND group_id=? AND boss_round=?
        """, (user_id, group_id, boss_round))
        await db.commit()
        return cursor.rowcount > 0


async def get_reservations(group_id: str, boss_round: int) -> List[Reservation]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, user_id, user_name, group_id, boss_round, created_at
            FROM reservations WHERE group_id=? AND boss_round=?
            ORDER BY created_at
        """, (group_id, boss_round)) as cursor:
            rows = await cursor.fetchall()
            from datetime import datetime
            return [
                Reservation(
                    id=r[0], user_id=r[1], user_name=r[2],
                    group_id=r[3], boss_round=r[4],
                    created_at=datetime.fromisoformat(r[5])
                ) for r in rows
            ]


async def clear_reservations_for_round(group_id: str, boss_round: int):
    """BOSS被击杀后清理该周目预约"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM reservations WHERE group_id=? AND boss_round=?",
            (group_id, boss_round)
        )
        await db.commit()


# ─── Summary ────────────────────────────────────────────────────────────────

async def get_today_summary(group_id: str) -> List[UserDailySummary]:
    """获取今日所有出刀用户汇总"""
    records = await get_today_all_records(group_id)
    user_map: dict = {}
    for r in records:
        if r.user_id not in user_map:
            user_map[r.user_id] = {
                "user_name": r.user_name,
                "normal": 0, "tail": 0, "compensate": 0,
                "total_damage": 0
            }
        d = user_map[r.user_id]
        d["total_damage"] += r.damage
        if r.knife_type == KnifeType.NORMAL:
            d["normal"] += 1
        elif r.knife_type == KnifeType.TAIL:
            d["tail"] += 1
        elif r.knife_type == KnifeType.COMPENSATE:
            d["compensate"] += 1

    result = []
    for uid, d in user_map.items():
        comp_left = await get_compensate_count(uid, group_id)
        result.append(UserDailySummary(
            user_id=uid,
            user_name=d["user_name"],
            normal_count=d["normal"],
            tail_count=d["tail"],
            compensate_count=d["compensate"],
            total_damage=d["total_damage"],
            has_compensate_left=comp_left > 0
        ))
    return sorted(result, key=lambda x: x.total_damage, reverse=True)
