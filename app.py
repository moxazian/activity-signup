# -*- coding: utf-8 -*-
"""活动报名系统入口（活动固定 5 个名额）。

启动（在 报名系统/ 目录下）：
    ..\\.venv\\Scripts\\python.exe -m uvicorn app:app --port 8021
页面：http://127.0.0.1:8021/    接口文档：http://127.0.0.1:8021/docs
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from db import engine, init_db
from routers import router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()          # 建库 + 建表 + 初始化活动与 5 个座位
    yield
    await engine.dispose()


app = FastAPI(title="活动报名系统（5 个名额）", lifespan=lifespan)

# 开发期：前端静态资源不缓存
@app.middleware("http")
async def no_cache_frontend(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(router)

# StaticFiles 要在所有 API 路由之后挂载，否则会吞掉 /api/*
app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "static"), html=True))
