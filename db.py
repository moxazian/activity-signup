# -*- coding: utf-8 -*-
"""数据库连接与初始化（建库 / 建表 / 初始化活动与 5 个座位，全部幂等）。"""
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.pool import NullPool

from config import ACTIVITY_ID, ACTIVITY_TITLE, CAPACITY, DB_NAME, db_url
from models import Activity, Base, Seat

# pool_size + max_overflow = 同时最多能拿到多少个连接（并发验证时要注意别把池子堵死）
engine = create_async_engine(
    db_url(DB_NAME),
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """FastAPI 依赖：每个请求一个会话（请求结束自动归还连接）。"""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """建库 → 建表 → 初始化活动与座位。可重复执行。"""
    # 1) 建库：这一步要连到 server 层（不指定 database）
    boot = create_async_engine(db_url(None), poolclass=NullPool)
    try:
        async with boot.begin() as conn:
            await conn.execute(text(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
            ))
    finally:
        await boot.dispose()

    # 2) 建表（已存在则跳过）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 3) 初始化活动 + 5 个座位
    async with AsyncSessionLocal() as db:
        act = await db.get(Activity, ACTIVITY_ID)
        if act is None:
            db.add(Activity(id=ACTIVITY_ID, title=ACTIVITY_TITLE, capacity=CAPACITY))
        else:
            act.title = ACTIVITY_TITLE
            act.capacity = CAPACITY
        existing = set((await db.execute(
            select(Seat.seat_no).where(Seat.activity_id == ACTIVITY_ID)
        )).scalars().all())
        for no in range(1, CAPACITY + 1):
            if no not in existing:
                db.add(Seat(activity_id=ACTIVITY_ID, seat_no=no))
        await db.commit()
        n = await db.scalar(select(func.count()).select_from(Seat)
                            .where(Seat.activity_id == ACTIVITY_ID))
        print(f"[init] 活动 #{ACTIVITY_ID} 「{ACTIVITY_TITLE}」 名额 {CAPACITY} 个，座位行 {n} 条")
