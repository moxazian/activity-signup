# -*- coding: utf-8 -*-
"""HTTP 接口（挂 /api 下）。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from config import ACTIVITY_ID
from db import get_db
from schemas import ActionResult, ActivityOut, CancelIn, SignupIn
from service import (CODE_ALREADY, CODE_BUSY, CODE_FULL, CODE_NO_ACTIVITY,
                     CODE_NOT_SIGNED, CODE_OK, cancel, get_activity_state,
                     reset, signup)

router = APIRouter(tags=["signup"])

OK_MESSAGE = "报名成功，你的座位号是 {seat}"
ALREADY_MESSAGE = "已报名"
CANCEL_MESSAGE = "已取消报名，{seat} 号座位已归还"


@router.get("/api/health")
async def health():
    return {"ok": True}


@router.get("/api/activity", response_model=ActivityOut)
async def activity(activity_id: int = Query(default=ACTIVITY_ID, ge=1),
                   db: AsyncSession = Depends(get_db)):
    """活动状态：名额 / 剩余 / 报名名单。"""
    state = await get_activity_state(db, activity_id)
    if state is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    return state


@router.post("/api/signup", response_model=ActionResult)
async def do_signup(body: SignupIn, db: AsyncSession = Depends(get_db)):
    """报名：只传一个模拟用户 ID。

    - 成功 / 重复报名 → 200（重复报名是幂等的，返回原座位号，不占新名额）
    - 名额已满       → 409
    """
    code, seat_no = await signup(db, body.user_id, body.activity_id)

    if code == CODE_NO_ACTIVITY:
        raise HTTPException(status_code=404, detail="活动不存在")
    if code == CODE_FULL:
        raise HTTPException(status_code=409, detail="名额已满，报名失败")
    if code == CODE_BUSY:
        raise HTTPException(status_code=503, detail="系统繁忙，请稍后重试")

    state = await get_activity_state(db, body.activity_id)
    if code == CODE_ALREADY:
        return ActionResult(success=True, code=CODE_ALREADY,
                            message=ALREADY_MESSAGE.format(seat=seat_no),
                            seat_no=seat_no, taken=state.taken,
                            remaining=state.remaining)
    return ActionResult(success=True, code=CODE_OK,
                        message=OK_MESSAGE.format(seat=seat_no),
                        seat_no=seat_no, taken=state.taken,
                        remaining=state.remaining)


@router.post("/api/cancel", response_model=ActionResult)
async def do_cancel(body: CancelIn, db: AsyncSession = Depends(get_db)):
    """取消报名：归还名额。

    - 取消成功           → 200
    - 没报名 / 已取消过   → 404（重复取消不会重复归还名额）
    """
    code, seat_no = await cancel(db, body.user_id, body.activity_id)

    if code == CODE_NO_ACTIVITY:
        raise HTTPException(status_code=404, detail="活动不存在")
    if code == CODE_BUSY:
        raise HTTPException(status_code=503, detail="系统繁忙，请稍后重试")
    if code == CODE_NOT_SIGNED:
        raise HTTPException(status_code=404, detail="该用户没有报名记录，无需取消")

    state = await get_activity_state(db, body.activity_id)
    return ActionResult(success=True, code=CODE_OK,
                        message=CANCEL_MESSAGE.format(seat=seat_no),
                        seat_no=seat_no, taken=state.taken,
                        remaining=state.remaining)


@router.post("/api/admin/reset", response_model=ActivityOut)
async def admin_reset(activity_id: int = Query(default=ACTIVITY_ID, ge=1),
                      db: AsyncSession = Depends(get_db)):
    """重置活动（清空报名记录、释放座位）。演示用接口。"""
    await reset(db, activity_id)
    state = await get_activity_state(db, activity_id)
    if state is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    return state
