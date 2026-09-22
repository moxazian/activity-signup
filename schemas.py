# -*- coding: utf-8 -*-
"""请求 / 响应模型（Pydantic v2）。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config import ACTIVITY_ID, USER_ID_MAX_LEN


class SignupIn(BaseModel):
    """报名请求：只输入一个模拟用户 ID。"""

    user_id: str = Field(..., min_length=1, max_length=USER_ID_MAX_LEN,
                         description="模拟用户 ID，例如 u1001")
    activity_id: int = Field(default=ACTIVITY_ID, ge=1)

    @field_validator("user_id")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("user_id 不能为空")
        return v


class MemberOut(BaseModel):
    """报名名单里的一行。"""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    seat_no: int | None = None
    created_at: datetime


class ActivityOut(BaseModel):
    """活动当前状态：名额 / 剩余 / 报名名单。"""

    id: int
    title: str
    capacity: int
    taken: int                 # 已报名人数（名单长度）
    remaining: int             # 剩余名额
    signups: list[MemberOut]


class CancelIn(SignupIn):
    """取消报名请求：同样只需要一个模拟用户 ID。"""


class ActionResult(BaseModel):
    """报名 / 取消共用的返回形状。"""

    success: bool
    code: str                  # ok / already
    message: str
    seat_no: int | None = None
    taken: int
    remaining: int
