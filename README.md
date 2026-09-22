# 活动报名系统（只有 5 个名额）

一个活动报名页：**输入模拟用户 ID 即可报名，页面显示剩余名额和报名名单**。
核心考点是数据一致性 —— 并发下不超卖、同一用户不重复占名额、取消要正确归还名额。

## 需求覆盖

| 层次 | 要求 | 实现位置 |
| --- | --- | --- |
| 基础 | 活动固定 5 个名额；输入模拟用户 ID 报名；页面显示剩余名额与报名名单 | `config.py` 的 `CAPACITY`、`routers.py`、`static/` |
| 第二层 | 同一用户最多占一个名额 | `signups` 表唯一键 `UNIQUE(activity_id, user_id)` + `service.signup()` |
| 第二层 | 支持取消报名，取消后归还名额 | `POST /api/cancel` → `service.cancel()` |
| 第二层 | 重复取消不能重复归还 | 条件 DELETE 的受影响行数判定（见下） |
| 第二层 | 数据在刷新页面、重启服务后仍然存在 | 全部落 MySQL（`event_signup` 库），服务端无内存态 |
| 第二层 | 不要求真实账号体系 | `user_id` 就是任意模拟标识 |
| 第三层 | 多个用户同时报名不能超额 | 座位行的条件 UPDATE + InnoDB 行锁 |
| 第三层 | 同一用户同时提交多次不能占多个名额 | 唯一键 + `IntegrityError` 回滚 |
| 第三层 | 限制必须在服务端成立，不能只依赖按钮禁用 | 全部约束在 SQL/事务层；前端 `disabled` 只是防连点的体验层 |

## 技术栈与运行

后端 FastAPI + SQLAlchemy 2.x（async）+ aiomysql，数据库 MySQL；前端原生 HTML/CSS/JS，无构建步骤。

```bash
# 1) 准备环境（Python 3.12）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt      # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # Linux/macOS

# 2) 启动（先在另一个终端确认 MySQL 在运行）
.venv/Scripts/python.exe -m uvicorn app:app --port 8021
```

启动后：页面 http://127.0.0.1:8021/ ，接口文档 http://127.0.0.1:8021/docs

首次启动会自动建库建表（幂等，可重复启动）：库 `event_signup`、三张表、一条活动配置和 5 个座位。
数据库连接可用环境变量覆盖（默认连本机 MySQL 的 root/123456）：

```
SIGNUP_DB_HOST  SIGNUP_DB_PORT  SIGNUP_DB_USER  SIGNUP_DB_PASSWORD  SIGNUP_DB_NAME
```

## 文件结构

| 文件 | 作用 |
| --- | --- |
| `app.py` | FastAPI 入口：建库建表（lifespan）、挂路由、托管 `static/` |
| `config.py` | 数据库连接（`URL.create` 逐字段组装）、活动名、名额 5 |
| `db.py` | 异步引擎 / 会话 / `init_db()` |
| `models.py` | 三张表：`activities` / `seats` / `signups` |
| `schemas.py` | 请求响应模型（Pydantic v2） |
| `service.py` | 业务核心：抢座、取消、活动状态查询 |
| `routers.py` | HTTP 接口 |
| `static/` | 页面：`index.html` + `app.js` + `style.css` |
| `test_concurrency.py` | 需求覆盖测试（纯标准库，9 个用例） |

## 接口

**GET /api/activity** —— 活动状态（名额 / 剩余 / 报名名单）
```json
{
  "id": 1, "title": "报名系统", "capacity": 5,
  "taken": 3, "remaining": 2,
  "signups": [
    {"user_id": "u0001", "seat_no": 1, "created_at": "2026-09-22T14:44:07.612"}
  ]
}
```

**POST /api/signup** —— 报名
```json
// 请求
{"user_id": "u0001"}
// 200 报名成功
{"success": true, "code": "ok", "message": "报名成功，你的座位号是 1", "seat_no": 1, "taken": 1, "remaining": 4}
// 200 重复报名（幂等，不占新名额）
{"success": true, "code": "already", "message": "已报名", "seat_no": 1, "taken": 1, "remaining": 4}
// 409 名额已满
{"detail": "名额已满，报名失败"}
```

**POST /api/cancel** —— 取消报名（归还名额）
```json
// 200
{"success": true, "code": "ok", "message": "已取消报名，1 号座位已归还", "seat_no": 1, "taken": 0, "remaining": 5}
// 404（没报名 / 已经取消过，不会重复归还名额）
{"detail": "该用户没有报名记录，无需取消"}
```

**POST /api/admin/reset** —— 清空报名记录、释放全部座位（演示/反复测试用）

## 表结构

```sql
activities(id, title, capacity, created_at)                  -- 活动配置，capacity = 名额上限 5
seats(id, activity_id, seat_no, user_id, claimed_at)          -- 把「名额」具体化成 5 行座位
    UNIQUE(activity_id, seat_no)                              -- 一个座位只能被一个人占
    INDEX(activity_id, user_id)                               -- 查空座 / 查某人占了哪
signups(id, activity_id, user_id, seat_no, created_at)        -- 报名流水
    UNIQUE(activity_id, user_id)                              -- 同一用户同一活动只能报一次
    INDEX(activity_id, created_at)                            -- 名单按报名时间排序
```

## 并发一致性怎么保证

一句话：**把「还有没有空座」的判断和「占座」的写入压进同一条 UPDATE 的 WHERE 里，由 InnoDB 行锁串行化**，受影响行数就是唯一答案，不需要分布式锁、也不需要额外计数列。

```python
# service.py 抢座（1..5 号座位逐个尝试）
res = await db.execute(
    update(Seat)
    .where(Seat.activity_id == aid, Seat.seat_no == seat_no, Seat.user_id.is_(None))
    .values(user_id=user_id, claimed_at=func.now())
)
if res.rowcount == 1:      # 抢到
    ...
# 5 个座位都是 0 行 → 名额已满
```

- 并发更新同一座位行时，后到的事务会等行锁；拿到锁后按**最新已提交数据**重新判定 WHERE（UPDATE 是当前读，不是快照读），看到已被占用就 `rowcount=0`，去试下一个座位 —— 所以不会有两个请求拿到同一个座位。
- 座位表只有 5 行，天然是 5 个行级锁资源。
- `signups` 的唯一键兜住「同一用户并发双击」：两个请求可能各抢到不同座位，但只有一个能提交成功，另一个主键冲突 → 整个事务回滚 → 刚占的座位自动退回。
- 抢座和写报名记录在同一个事务里提交，不存在「占了座没写记录」。

取消报名用的是同一套思路：

```python
# service.py 取消
res = await db.execute(delete(Signup).where(Signup.activity_id == aid, Signup.user_id == user_id))
if res.rowcount == 0:                       # 已经被并发的另一次取消处理过 → 不重复归还
    return CODE_NOT_SIGNED, None
await db.execute(update(Seat).where(Seat.activity_id == aid, Seat.seat_no == seat_no,
                                    Seat.user_id == user_id).values(user_id=None, claimed_at=None))
await db.commit()
```

## 测试

`test_concurrency.py` 按需求逐条写了 9 个用例，只用 Python 标准库（`http.client` + `threading`）直接发原始 HTTP 请求 —— **不加载页面、不执行任何 JS**，所以「按钮禁用」这类前端限制不参与，能过就说明约束确实在服务端成立。

```bash
python test_concurrency.py        # 默认 20 个并发用户
python test_concurrency.py 50     # 放大到 50
```

脚本自己挑一个空闲端口起服务、自己重置测试数据、跑完自动关服务，最后打印每条用例的 ✅/❌ 和 `用例结果：x/9 通过`（失败会以非 0 退出码结束）。

实测结果（本机 MySQL，20 并发与 50 并发各跑一遍）：

| 用例 | 结果 |
| --- | --- |
| 2.1 同一用户最多占一个名额（顺序重复 + 并发 5 次） | 名单里该用户 1 行，剩余名额 4 → 4（没被重复占用） |
| 2.2 取消报名、取消后归还名额 | 5/5 满员 → 取消 1 人 → 剩余 1 |
| 2.2b 归还的名额能再被别人报名 | 200 抢到刚归还的座位 |
| 2.3 重复取消不能重复归还（并发 5 次 + 顺序再取消） | 只有 1 次 200，其余 404；剩余名额保持 1 |
| 2.4 刷新页面 / 重启服务后数据仍在 | 停服务 → 重启 → 名单与座位号逐条一致 |
| 3.1 多用户并发报名不超额 | 20 并发：成功 5 / 满员 15，座位号恰好 1~5 无重复；50 并发同样恰好 5 |
| 3.2 同一用户并发提交 10 次只占 1 个名额 | `{ok:1, already:9}`，名单 1 条 |
| 3.3 限制在服务端成立（原始 HTTP 直调） | 满员后 409；已报名用户再提交 200「已报名」，名单仍 5 条 |
| 页面自检 | `GET /` 200，含「剩余名额」「报名名单」 |

## 说明与边界

- 名额固定 5 个，写在 `config.py` 的 `CAPACITY`；改名额要重启（活动配置暂时没有管理接口）。
- `POST /api/admin/reset` 是为反复演示/测试留的，不属于业务需求。
- 没有账号体系：`user_id` 是模拟标识，生产环境应校验登录态、并对报名接口做限流与风控。
- 单机 MySQL 行锁即可支撑这个量级；若名额规模极大（上万）或需要多库分片，再考虑计数列、Redis 预扣 + 消息队列异步落库等方案。
