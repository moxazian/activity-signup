# -*- coding: utf-8 -*-
"""核心业务：抢座（报名）/ 活动状态 / 重置。

并发一致性核心在 _claim_seat()：把「还有没有空座」的判断和「占座」的写入
压进同一条 UPDATE 的 WHERE 里（WHERE user_id IS NULL），由 InnoDB 行锁串行化：
受影响行数 1 = 抢到座位，试完 5 个座位都是 0 = 名额已满。
不需要分布式锁、不需要额外计数列，也不需要在应用层做「先查再写」。

取消报名（cancel）用同样思路：带条件的 DELETE 判定「有没有这条报名记录」，
受影响行数 0 就说明已经被并发的另一次取消处理过 → 不重复归还名额。
"""
import logging

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from config import ACTIVITY_ID
from models import Activity, Seat, Signup
from schemas import ActivityOut, MemberOut

log = logging.getLogger("signup")

CODE_OK = "ok"
CODE_ALREADY = "already"
CODE_FULL = "full"
CODE_NOT_SIGNED = "not_signed"
CODE_NO_ACTIVITY = "no_activity"
CODE_BUSY = "busy"


async def _existing_signup(db: AsyncSession, activity_id: int, user_id: str):
    return await db.scalar(
        select(Signup).where(Signup.activity_id == activity_id,
                             Signup.user_id == user_id)
    )


async def _claim_seat(db: AsyncSession, activity_id: int, user_id: str,
                      capacity: int) -> int | None:
    """原子抢座：从 1 号座位开始，逐行尝试条件更新，抢到返回座位号，全满返回 None。

    为什么不是「先 SELECT 找空座，再 UPDATE」：先查后写（check-then-act）两步之间
    就是竞态窗口，并发下会超卖。
    这里把「判断」和「占用」压进同一条 UPDATE 的 WHERE 里，由 InnoDB 的行锁串行化：
      - 座位还空着 → WHERE 命中，加锁并写入，rowcount=1
      - 别人已占    → WHERE 不命中，rowcount=0（若对方事务未提交，本事务会等行锁，
                      拿到锁后按最新数据重新判定），于是接着试下一个座位
    注：MySQL 方言有 UPDATE ... ORDER BY ... LIMIT 1 写法，但核心 SQLAlchemy 的 Update
    不支持 order_by/limit（只有 mysql 方言版支持），逐座位尝试语义完全一致，且换
    PostgreSQL / SQLite 也不用改代码。
    """
    for seat_no in range(1, capacity + 1):
        res = await db.execute(
            update(Seat)
            .where(Seat.activity_id == activity_id,
                   Seat.seat_no == seat_no,
                   Seat.user_id.is_(None))
            .values(user_id=user_id, claimed_at=func.now())
        )
        if res.rowcount == 1:
            return seat_no
    return None


async def signup(db: AsyncSession, user_id: str,
                 activity_id: int = ACTIVITY_ID) -> tuple[str, int | None]:
    """报名。返回 (code, seat_no)；code ∈ ok / already / full / no_activity / busy。

    步骤：
      1. 快速幂等：这个用户已经报过名 → 直接返回原来的座位号（不占新座位）
      2. 原子抢座：一条 UPDATE ... WHERE user_id IS NULL ORDER BY seat_no LIMIT 1
         - 并发下 InnoDB 会给扫到的座位行加排它锁，别人只能等/换下一个座位
         - rowcount==1 表示这条座位被本事务占下；0 表示没有空座（名额已满）
      3. 写报名记录并与座位更新放在同一个事务里提交
         - signups 的唯一键 (activity_id, user_id) 兜住「同一用户并发双击」：
           两个请求各抢到不同座位时，后提交的那个主键冲突 → 整个事务回滚 → 座位自动退回
    """
    act = await db.get(Activity, activity_id)
    if act is None:
        await db.rollback()
        return CODE_NO_ACTIVITY, None

    old = await _existing_signup(db, activity_id, user_id)
    if old is not None:
        # 先把 seat_no 取出来再 rollback：rollback 会让这个 ORM 对象过期，
        # 之后再访问 old.seat_no 会触发「同步」的属性重载 → async 下抛
        # MissingGreenlet → 500（这就是重复报名曾经报 500 的原因）
        seat_no = old.seat_no
        await db.rollback()
        return CODE_ALREADY, seat_no

    # —— 关键的一步：原子的「判断 + 占用」（见 _claim_seat）——
    try:
        seat_no = await _claim_seat(db, activity_id, user_id, act.capacity)
    except OperationalError as exc:           # 锁等待超时等极端情况
        await db.rollback()
        log.warning("抢座失败 user=%s: %s", user_id, exc)
        return CODE_BUSY, None

    if seat_no is None:                        # 5 个座位都被占了 → 名额已满
        await db.rollback()
        return CODE_FULL, None

    db.add(Signup(activity_id=activity_id, user_id=user_id, seat_no=seat_no))
    try:
        await db.commit()
    except IntegrityError:
        # 同一用户并发双击：另一个请求已经写成功了，座位随回滚一起退回
        await db.rollback()
        old = await _existing_signup(db, activity_id, user_id)
        return CODE_ALREADY, (old.seat_no if old else None)

    return CODE_OK, seat_no


async def cancel(db: AsyncSession, user_id: str,
                 activity_id: int = ACTIVITY_ID) -> tuple[str, int | None]:
    """取消报名并归还名额。返回 (code, seat_no)；code ∈ ok / not_signed / no_activity / busy。

    重复取消不会重复归还：
      1. 删报名记录用「带 user_id 条件的 DELETE」，受影响行数就是唯一判定 ——
         并发的两次取消里，只有一个 DELETE 能删到行（另一个 rowcount=0，直接返回 not_signed），
         所以不会出现「一次报名被归还两次名额」。
      2. 归还座位也是一条带条件的 UPDATE（WHERE user_id = 本人），
         即使重复执行，第二次也是 0 行，动不了别人的座位。
      3. 删记录和归还座位在同一个事务里提交，不会出现「记录没了、座位还占着」的中间态。
    """
    act = await db.get(Activity, activity_id)
    if act is None:
        await db.rollback()
        return CODE_NO_ACTIVITY, None

    row = await _existing_signup(db, activity_id, user_id)
    if row is None:                       # 本来就没报名（或已经被取消过了）
        await db.rollback()
        return CODE_NOT_SIGNED, None
    seat_no = row.seat_no

    try:
        res = await db.execute(
            delete(Signup).where(Signup.activity_id == activity_id,
                                 Signup.user_id == user_id)
        )
    except OperationalError as exc:
        await db.rollback()
        log.warning("取消报名失败 user=%s: %s", user_id, exc)
        return CODE_BUSY, None

    if res.rowcount == 0:                 # 并发的另一次取消已经先删掉了
        await db.rollback()
        return CODE_NOT_SIGNED, None

    await db.execute(
        update(Seat)
        .where(Seat.activity_id == activity_id,
               Seat.seat_no == seat_no,
               Seat.user_id == user_id)
        .values(user_id=None, claimed_at=None)
    )
    await db.commit()
    return CODE_OK, seat_no


async def get_activity_state(db: AsyncSession,
                             activity_id: int = ACTIVITY_ID) -> ActivityOut | None:
    """页面数据：剩余名额 + 报名名单。"""
    act = await db.get(Activity, activity_id)
    if act is None:
        return None
    rows = (await db.execute(
        select(Signup).where(Signup.activity_id == activity_id)
        .order_by(Signup.created_at, Signup.id)
    )).scalars().all()
    taken = len(rows)
    return ActivityOut(
        id=act.id,
        title=act.title,
        capacity=act.capacity,
        taken=taken,
        remaining=max(0, act.capacity - taken),   # 名额有限，最少显示 0
        signups=[MemberOut.model_validate(r) for r in rows],
    )


async def reset(db: AsyncSession, activity_id: int = ACTIVITY_ID) -> None:
    """清空报名记录、释放全部座位（演示 / 反复验证用）。"""
    await db.execute(delete(Signup).where(Signup.activity_id == activity_id))
    await db.execute(update(Seat).where(Seat.activity_id == activity_id)
                     .values(user_id=None, claimed_at=None))
    await db.commit()
