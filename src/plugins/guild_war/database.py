"""SQLite 数据库操作层"""

import json
import aiosqlite
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from .models import (
    KnifeRecord, KnifeType, BossStatus, QueueEntry, Reservation, UserDailySummary,
    Member, Homework,
)
from .config import MAX_KNIVES_PER_DAY, get_boss_stage, BOSS_STAGES

DB_PATH = Path("data/guild_war.db")


async def init_db():
    """初始化数据库，创建表"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS member_accounts (
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                member_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, group_id)
            );

            CREATE TABLE IF NOT EXISTS knife_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                member_id INTEGER NOT NULL,
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

            CREATE TABLE IF NOT EXISTS queue (
                member_id INTEGER NOT NULL,
                group_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (member_id, group_id)
            );

            CREATE TABLE IF NOT EXISTS boss_reservations (
                member_id INTEGER NOT NULL,
                group_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                boss_round INTEGER NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (member_id, group_id, boss_round)
            );

            CREATE TABLE IF NOT EXISTS compensate_knives (
                member_id INTEGER NOT NULL,
                group_id TEXT NOT NULL,
                date TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (member_id, group_id, date)
            );

            CREATE TABLE IF NOT EXISTS homework (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                title TEXT NOT NULL,
                image_paths TEXT NOT NULL,
                uploader_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        await db.commit()


# ─── Members ────────────────────────────────────────────────────────────────

async def _load_member(db, member_id: int) -> Optional[Member]:
    async with db.execute(
        "SELECT id, group_id, name FROM members WHERE id=?", (member_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    async with db.execute(
        "SELECT user_id FROM member_accounts WHERE member_id=? ORDER BY rowid",
        (member_id,)
    ) as cursor:
        user_ids = [r[0] for r in await cursor.fetchall()]
    return Member(id=row[0], group_id=row[1], name=row[2], user_ids=user_ids)


async def get_member(member_id: int) -> Optional[Member]:
    async with aiosqlite.connect(DB_PATH) as db:
        return await _load_member(db, member_id)


async def get_member_by_user(user_id: str, group_id: str) -> Optional[Member]:
    """根据QQ号查找所属成员"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT member_id FROM member_accounts WHERE user_id=? AND group_id=?",
            (user_id, group_id)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        return await _load_member(db, row[0])


async def create_member(group_id: str, name: str, user_id: str) -> Member:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO members (group_id, name, created_at) VALUES (?, ?, ?)",
            (group_id, name, datetime.now().isoformat())
        )
        member_id = cursor.lastrowid
        await db.execute(
            "INSERT INTO member_accounts (user_id, group_id, member_id) VALUES (?, ?, ?)",
            (user_id, group_id, member_id)
        )
        await db.commit()
    return Member(id=member_id, group_id=group_id, name=name, user_ids=[user_id])


async def bind_account(member_id: int, group_id: str, user_id: str) -> bool:
    """给成员绑定一个QQ号，返回是否成功（False表示该QQ已注册/绑定）"""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO member_accounts (user_id, group_id, member_id) VALUES (?, ?, ?)",
                (user_id, group_id, member_id)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def unbind_account(user_id: str, group_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM member_accounts WHERE user_id=? AND group_id=?",
            (user_id, group_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def rename_member(member_id: int, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE members SET name=? WHERE id=?", (name, member_id))
        await db.commit()


async def delete_member(member_id: int):
    """注销成员及其所有绑定账号（出刀记录保留）"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM member_accounts WHERE member_id=?", (member_id,))
        await db.execute("DELETE FROM queue WHERE member_id=?", (member_id,))
        await db.execute("DELETE FROM boss_reservations WHERE member_id=?", (member_id,))
        await db.execute("DELETE FROM members WHERE id=?", (member_id,))
        await db.commit()


async def list_members(group_id: str) -> List[Member]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM members WHERE group_id=? ORDER BY id", (group_id,)
        ) as cursor:
            ids = [r[0] for r in await cursor.fetchall()]
        return [m for m in [await _load_member(db, i) for i in ids] if m]


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

_KNIFE_COLUMNS = """id, user_id, member_id, user_name, group_id, damage, knife_type,
                   boss_round, boss_hp_before, boss_hp_after, date, created_at"""


async def add_knife_record(record: KnifeRecord) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO knife_records
            (user_id, member_id, user_name, group_id, damage, knife_type, boss_round,
             boss_hp_before, boss_hp_after, date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (record.user_id, record.member_id, record.user_name, record.group_id,
              record.damage, record.knife_type.value, record.boss_round,
              record.boss_hp_before, record.boss_hp_after,
              record.date, record.created_at.isoformat()))
        await db.commit()
        return cursor.lastrowid


async def get_member_today_records(member_id: int, group_id: str) -> List[KnifeRecord]:
    """成员今日所有出刀（包含其所有绑定账号）"""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"""
            SELECT {_KNIFE_COLUMNS}
            FROM knife_records
            WHERE member_id=? AND group_id=? AND date=?
            ORDER BY created_at
        """, (member_id, group_id, today)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_knife(r) for r in rows]


async def delete_last_knife(member_id: int, group_id: str) -> Optional[KnifeRecord]:
    """撤销成员最近一刀，返回被撤销的记录"""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"""
            SELECT {_KNIFE_COLUMNS}
            FROM knife_records
            WHERE member_id=? AND group_id=? AND date=?
            ORDER BY created_at DESC LIMIT 1
        """, (member_id, group_id, today)) as cursor:
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
        async with db.execute(f"""
            SELECT {_KNIFE_COLUMNS}
            FROM knife_records WHERE group_id=? AND date=?
            ORDER BY created_at
        """, (group_id, today)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_knife(r) for r in rows]


def _row_to_knife(row) -> KnifeRecord:
    return KnifeRecord(
        id=row[0], user_id=row[1], member_id=row[2], user_name=row[3],
        group_id=row[4], damage=row[5], knife_type=KnifeType(row[6]),
        boss_round=row[7], boss_hp_before=row[8], boss_hp_after=row[9],
        date=row[10], created_at=datetime.fromisoformat(row[11])
    )


# ─── Compensate Knives ──────────────────────────────────────────────────────

async def add_compensate_knife(member_id: int, group_id: str):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO compensate_knives (member_id, group_id, date, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(member_id, group_id, date) DO UPDATE SET count = count + 1
        """, (member_id, group_id, today))
        await db.commit()


async def get_compensate_count(member_id: int, group_id: str) -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT count FROM compensate_knives WHERE member_id=? AND group_id=? AND date=?",
            (member_id, group_id, today)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def use_compensate_knife(member_id: int, group_id: str) -> bool:
    """消耗一次补偿刀，返回是否成功"""
    count = await get_compensate_count(member_id, group_id)
    if count <= 0:
        return False
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE compensate_knives SET count = count - 1
            WHERE member_id=? AND group_id=? AND date=?
        """, (member_id, group_id, today))
        await db.commit()
    return True


# ─── Queue ──────────────────────────────────────────────────────────────────

async def add_to_queue(member_id: int, group_id: str, user_name: str) -> bool:
    """加入出刀队列，返回是否成功（False表示已在队列中）"""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("""
                INSERT INTO queue (member_id, group_id, user_name, created_at)
                VALUES (?, ?, ?, ?)
            """, (member_id, group_id, user_name, datetime.now().isoformat()))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_from_queue(member_id: int, group_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM queue WHERE member_id=? AND group_id=?", (member_id, group_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_queue(group_id: str) -> List[QueueEntry]:
    """按排队先后返回队列，第一位为当前出刀人"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT member_id, group_id, user_name, created_at
            FROM queue WHERE group_id=? ORDER BY created_at
        """, (group_id,)) as cursor:
            return [
                QueueEntry(member_id=r[0], group_id=r[1], user_name=r[2],
                           created_at=datetime.fromisoformat(r[3]))
                for r in await cursor.fetchall()
            ]


async def clear_queue(group_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM queue WHERE group_id=?", (group_id,))
        await db.commit()


# ─── Reservations ───────────────────────────────────────────────────────────

async def add_reservation(member_id: int, group_id: str, user_name: str,
                          boss_round: int) -> bool:
    """预约某周目，返回是否成功（False表示已预约过）"""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("""
                INSERT INTO boss_reservations
                (member_id, group_id, user_name, boss_round, notified, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
            """, (member_id, group_id, user_name, boss_round, datetime.now().isoformat()))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def cancel_reservations(member_id: int, group_id: str,
                              boss_round: Optional[int] = None) -> int:
    """取消预约（不指定周目则取消全部未提醒的预约），返回取消数量"""
    sql = "DELETE FROM boss_reservations WHERE member_id=? AND group_id=? AND notified=0"
    params: tuple = (member_id, group_id)
    if boss_round is not None:
        sql += " AND boss_round=?"
        params += (boss_round,)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(sql, params)
        await db.commit()
        return cursor.rowcount


async def get_reservations(group_id: str, boss_round: Optional[int] = None,
                           pending_only: bool = True) -> List[Reservation]:
    sql = """SELECT member_id, group_id, user_name, boss_round, notified, created_at
             FROM boss_reservations WHERE group_id=?"""
    params: tuple = (group_id,)
    if boss_round is not None:
        sql += " AND boss_round=?"
        params += (boss_round,)
    if pending_only:
        sql += " AND notified=0"
    sql += " ORDER BY boss_round, created_at"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(sql, params) as cursor:
            return [
                Reservation(member_id=r[0], group_id=r[1], user_name=r[2],
                            boss_round=r[3], notified=bool(r[4]),
                            created_at=datetime.fromisoformat(r[5]))
                for r in await cursor.fetchall()
            ]


async def mark_reservations_notified(group_id: str, boss_round: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE boss_reservations SET notified=1 WHERE group_id=? AND boss_round=?",
            (group_id, boss_round)
        )
        await db.commit()


async def clear_reservations(group_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM boss_reservations WHERE group_id=?", (group_id,))
        await db.commit()


# ─── Homework ───────────────────────────────────────────────────────────────

async def add_homework(group_id: str, title: str, image_paths: List[str],
                       uploader_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO homework (group_id, title, image_paths, uploader_id, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (group_id, title, json.dumps(image_paths), uploader_id,
              datetime.now().isoformat()))
        await db.commit()
        return cursor.lastrowid


def _row_to_homework(row) -> Homework:
    return Homework(
        id=row[0], group_id=row[1], title=row[2],
        image_paths=json.loads(row[3]), uploader_id=row[4],
        created_at=datetime.fromisoformat(row[5])
    )


async def list_homework(group_id: str, keyword: str = "") -> List[Homework]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, group_id, title, image_paths, uploader_id, created_at
            FROM homework WHERE group_id=? AND title LIKE ?
            ORDER BY id
        """, (group_id, f"%{keyword}%")) as cursor:
            return [_row_to_homework(r) for r in await cursor.fetchall()]


async def get_homework(group_id: str, homework_id: int) -> Optional[Homework]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, group_id, title, image_paths, uploader_id, created_at
            FROM homework WHERE group_id=? AND id=?
        """, (group_id, homework_id)) as cursor:
            row = await cursor.fetchone()
            return _row_to_homework(row) if row else None


async def delete_homework(group_id: str, homework_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM homework WHERE group_id=? AND id=?", (group_id, homework_id)
        )
        await db.commit()
        return cursor.rowcount > 0


# ─── Summary ────────────────────────────────────────────────────────────────

async def get_today_summary(group_id: str) -> List[UserDailySummary]:
    """获取今日所有已注册成员的出刀汇总（含未出刀成员）"""
    records = await get_today_all_records(group_id)
    members = await list_members(group_id)
    member_map: dict = {
        m.id: {
            "user_name": m.name, "user_ids": m.user_ids,
            "normal": 0, "tail": 0, "compensate": 0, "total_damage": 0
        } for m in members
    }
    for r in records:
        d = member_map.get(r.member_id)
        if d is None:  # 已注销成员的历史记录
            continue
        d["total_damage"] += r.damage
        if r.knife_type == KnifeType.NORMAL:
            d["normal"] += 1
        elif r.knife_type == KnifeType.TAIL:
            d["tail"] += 1
        elif r.knife_type == KnifeType.COMPENSATE:
            d["compensate"] += 1

    result = []
    for mid, d in member_map.items():
        comp_left = await get_compensate_count(mid, group_id)
        result.append(UserDailySummary(
            member_id=mid,
            user_name=d["user_name"],
            user_ids=d["user_ids"],
            normal_count=d["normal"],
            tail_count=d["tail"],
            compensate_count=d["compensate"],
            total_damage=d["total_damage"],
            has_compensate_left=comp_left > 0
        ))
    return sorted(result, key=lambda x: x.total_damage, reverse=True)
