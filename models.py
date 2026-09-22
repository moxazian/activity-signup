# -*- coding: utf-8 -*-
"""数据模型：活动 / 座位 / 报名记录。

设计要点（面试官最关心的三张表的分工）：
- activities：活动配置。capacity = 名额上限（本任务固定 5）。
- seats     ：把「名额」具体化成 5 行座位记录，user_id 为空 = 这个座位还空着。
              UNIQUE(activity_id, seat_no) 是「一个座位只能被一个人占」的最后一道防线，
              抢座时用一条带条件的 UPDATE（WHERE user_id IS NULL）由 InnoDB 行锁串行化，
              所以不需要分布式锁。
- signups   ：报名流水（谁、什么时候、坐几号）。UNIQUE(activity_id, user_id) 保证
              同一个用户在同一个活动里只会有一条报名记录（点两次 / 双击 / 重试都安全）。
"""
from sqlalchemy import (BigInteger, Column, DateTime, ForeignKey, Index, Integer,
                        String, UniqueConstraint, text)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(100), nullable=False)
    capacity = Column(Integer, nullable=False, default=0)
    created_at = Column(DATETIME(fsp=3), nullable=False,
                        server_default=text("CURRENT_TIMESTAMP(3)"))


class Seat(Base):
    __tablename__ = "seats"
    __table_args__ = (
        UniqueConstraint("activity_id", "seat_no", name="uk_seat_no"),
        Index("idx_seat_free", "activity_id", "user_id"),
        {"mysql_charset": "utf8mb4"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    activity_id = Column(Integer, ForeignKey("activities.id"), nullable=False)
    seat_no = Column(Integer, nullable=False)
    # 谁占了这个座位；NULL = 空座
    user_id = Column(String(32), nullable=True)
    claimed_at = Column(DATETIME(fsp=3), nullable=True)


class Signup(Base):
    __tablename__ = "signups"
    __table_args__ = (
        UniqueConstraint("activity_id", "user_id", name="uk_signup_user"),
        Index("idx_signup_activity_time", "activity_id", "created_at"),
        {"mysql_charset": "utf8mb4"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    activity_id = Column(Integer, ForeignKey("activities.id"), nullable=False)
    user_id = Column(String(32), nullable=False)
    seat_no = Column(Integer, nullable=True)
    created_at = Column(DATETIME(fsp=3), nullable=False,
                        server_default=text("CURRENT_TIMESTAMP(3)"))
