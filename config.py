# -*- coding: utf-8 -*-
"""活动报名系统配置（活动固定 5 个名额）。

数据库连接、活动名、名额这些可调项集中在这里。
"""
import os

from sqlalchemy.engine import URL

# ---------------- 数据库 ----------------
DB_USER = os.getenv("SIGNUP_DB_USER", "root")
DB_PASSWORD = os.getenv("SIGNUP_DB_PASSWORD", "123456")
DB_HOST = os.getenv("SIGNUP_DB_HOST", "localhost")
DB_PORT = int(os.getenv("SIGNUP_DB_PORT", "3306"))
# 独立的库名，不动本机其它库
DB_NAME = os.getenv("SIGNUP_DB_NAME", "event_signup")


def db_url(database: str | None = None) -> URL:
    """拼连接串。

    不写成 "mysql+aiomysql://root:密码@host/db" 这种内联字符串：
    凭据内联在后端被工具/日志打码或替换过，容易把密码写坏；用 URL.create 逐字段组装。
    database=None 时连到 server 层（用来 CREATE DATABASE）。
    """
    return URL.create(
        "mysql+aiomysql",
        username=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=database,
        query={"charset": "utf8mb4"},
    )


# ---------------- 业务参数 ----------------
ACTIVITY_ID = 1
ACTIVITY_TITLE = "线下技术分享会 · 现场名额"
CAPACITY = 5                 # 活动固定 5 个名额
USER_ID_MAX_LEN = 32         # 模拟用户 ID 最大长度
