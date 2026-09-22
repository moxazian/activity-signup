# -*- coding: utf-8 -*-
"""需求覆盖测试：第二层 / 第三层逐条对应用例。

第二层
  2.1 同一用户最多占一个名额
  2.2 支持取消报名，取消后归还名额
  2.3 重复取消不能重复归还
  2.4 数据在刷新页面和重启服务后仍然存在
第三层
  3.1 多个用户同时报名不能超额
  3.2 同一用户同时提交多次不能占多个名额
  3.3 限制必须在服务端成立（不能只依赖按钮禁用）

全程只用标准库 http.client 直接打 HTTP 接口：不加载页面、不执行任何 JS，
所以「按钮禁用」这类前端限制完全不参与 —— 能过就说明约束确实在服务端成立。

跑法（在 报名系统/ 目录下）：
    ..\\.venv\\Scripts\\python.exe test_concurrency.py        默认 20 个并发用户
    ..\\.venv\\Scripts\\python.exe test_concurrency.py 50     也可以改成 50
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time

HOST = "127.0.0.1"
PORT = 8021            # main() 里会改成一个当前空闲的端口
BASE = os.path.dirname(os.path.abspath(__file__))
USERS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
CAPACITY = 5

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = []           # [(用例名, 是否通过, 说明)]


# ------------------------------------------------------------------ 基础设施
def call(method, path, body=None, timeout=15):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        conn.request(method, path,
                     json.dumps(body, ensure_ascii=False) if body is not None else None,
                     {"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except Exception:
            data = {"raw": raw[:200]}
        return resp.status, data
    finally:
        conn.close()


def get_text(path, timeout=15):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", "replace")
    finally:
        conn.close()


def port_in_use(port):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex((HOST, port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def pick_port(start=8021, end=8100):
    """挑一个没人监听的端口，避免踩到手动起的服务或上一轮的残留进程。"""
    for port in range(start, end):
        if not port_in_use(port):
            return port
    raise RuntimeError(f"{start}-{end} 没有空闲端口")


def wait_ready(timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st, _ = call("GET", "/api/health", timeout=2)
            if st == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def start_server():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    logfile = open(os.path.join(BASE, "server.log"), "ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", HOST,
         "--port", str(PORT), "--no-access-log"],
        cwd=BASE, env=env, stdout=logfile, stderr=subprocess.STDOUT,
    )
    if not wait_ready():
        proc.terminate()
        raise RuntimeError("服务启动失败，看 server.log")
    return proc, logfile


def stop_server(proc, logfile):
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
        proc.wait(timeout=10)
    logfile.close()
    for _ in range(20):
        if not port_in_use(PORT):
            return
        time.sleep(0.25)
    print(f"  ⚠ 端口 {PORT} 似乎还有进程占用")


def burst(users, path="/api/signup"):
    """所有线程在 barrier（栅栏）处对齐后同一瞬间发请求，制造真并发。"""
    barrier = threading.Barrier(len(users))
    out = [None] * len(users)

    def worker(idx, user):
        barrier.wait()
        try:
            out[idx] = call("POST", path, {"user_id": user})
        except Exception as exc:            # noqa: BLE001
            out[idx] = (0, {"detail": repr(exc)})

    threads = [threading.Thread(target=worker, args=(i, u)) for i, u in enumerate(users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def state():
    _, data = call("GET", "/api/activity")
    return data


def roster(data):
    return [(m["user_id"], m["seat_no"]) for m in data["signups"]]


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  —— {detail}" if detail else ""))


# ------------------------------------------------------------------ 各层用例
def layer2():
    print("\n【第二层 · 追加业务规则】")

    # ---- 2.1 同一用户最多占一个名额 ----
    call("POST", "/api/admin/reset")
    st1, d1 = call("POST", "/api/signup", {"user_id": "u0001"})
    s_after_first = state()
    seq = call("POST", "/api/signup", {"user_id": "u0001"})          # 顺序重复
    conc = burst(["u0001"] * 5)                                      # 并发重复
    s2 = state()
    mine = [m for m in s2["signups"] if m["user_id"] == "u0001"]
    ok = (st1 == 200 and seq[0] == 200 and all(st == 200 for st, _ in conc)
          and len(mine) == 1
          and s2["remaining"] == s_after_first["remaining"] == CAPACITY - 1)
    check("2.1 同一用户最多占一个名额（顺序重复 + 并发重复都只算一次）", ok,
          f"首次 {st1}，顺序再报 {seq[0]}，并发 5 次 "
          f"{[st for st, _ in conc]}；名单里该用户 {len(mine)} 行，剩余名额 "
          f"{s_after_first['remaining']} → {s2['remaining']}（没被重复占用）")

    # ---- 2.2 取消报名，取消后归还名额 ----
    for u in ["u0002", "u0003", "u0004", "u0005"]:
        call("POST", "/api/signup", {"user_id": u})
    full = state()
    st_c, d_c = call("POST", "/api/cancel", {"user_id": "u0003"})
    after = state()
    ok = (full["remaining"] == 0 and st_c == 200 and after["remaining"] == 1
          and "u0003" not in [x[0] for x in roster(after)])
    check("2.2 支持取消报名、取消后名额归还（5/5 满员 → 取消 1 人 → 剩余 1）", ok,
          f"满员时剩余 {full['remaining']}，取消返回 HTTP {st_c} "
          f"{d_c.get('message', '')}，之后剩余 {after['remaining']}")
    # 归还的名额能被别人抢到
    st_take, d_take = call("POST", "/api/signup", {"user_id": "u9999"})
    check("2.2b 归还的名额可以再被别人报名", st_take == 200 and state()["remaining"] == 0,
          f"{d_take.get('message') or d_take.get('detail')}")

    # ---- 2.3 重复取消不能重复归还 ----
    conc_cancel = burst(["u9999"] * 5, path="/api/cancel")            # 并发重复取消
    s3 = state()
    ok_c = [st for st, _ in conc_cancel if st == 200]
    seq_c = call("POST", "/api/cancel", {"user_id": "u9999"})          # 顺序再取消
    s4 = state()
    ok = (len(ok_c) == 1 and s3["remaining"] == 1 and s4["remaining"] == 1
          and seq_c[0] == 404)
    check("2.3 重复取消不能重复归还（并发 5 次 + 顺序再取消，只归还 1 个名额）", ok,
          f"并发取消成功 {len(ok_c)} 次、其余 {[st for st, _ in conc_cancel if st != 200]}；"
          f"剩余名额 {s3['remaining']}（再顺序取消 HTTP {seq_c[0]} 后仍是 {s4['remaining']}）")

    # ---- 2.4 刷新页面 / 重启服务后数据仍在 ----
    before = state()
    return before


def layer2_restart(proc, logfile):
    """2.4：把服务停掉再起起来，比对名单是否一模一样。"""
    before = state()
    stop_server(proc, logfile)
    proc, logfile = start_server()
    after = state()
    again = state()          # 再 GET 一次 = 刷新页面
    ok = (roster(before) == roster(after) == roster(again)
          and before["remaining"] == after["remaining"])
    check("2.4 数据在刷新页面和重启服务后仍然存在", ok,
          f"重启前 {len(roster(before))} 人 {roster(before)} → 重启后 "
          f"{len(roster(after))} 人 {roster(after)}")
    return proc, logfile


def layer3():
    print("\n【第三层 · 边界与变更】")

    # ---- 3.1 多个用户同时报名不能超额 ----
    call("POST", "/api/admin/reset")
    users = [f"u{i:04d}" for i in range(1, USERS + 1)]
    res = burst(users)
    s = state()
    ok_count = [st for st, _ in res if st == 200]
    seats = sorted(d.get("seat_no") for st, d in res if st == 200)
    dup = sorted({x for x in seats if seats.count(x) > 1})
    check(f"3.1 {USERS} 个用户同时报名不超额（恰好 {CAPACITY} 人成功）",
          len(ok_count) == CAPACITY and s["taken"] == CAPACITY
          and seats == list(range(1, CAPACITY + 1)) and not dup,
          f"成功 {len(ok_count)} 人、满员 {sum(1 for st, _ in res if st == 409)} 人，"
          f"座位号 {seats}，名单 {len(roster(s))} 条，剩余 {s['remaining']}")

    # ---- 3.2 同一用户同时提交多次不能占多个名额 ----
    call("POST", "/api/admin/reset")
    res2 = burst(["u0001"] * 10)
    s2 = state()
    codes = {}
    for st, d in res2:
        codes[d.get("code", st)] = codes.get(d.get("code", st), 0) + 1
    check("3.2 同一用户同时提交 10 次只占 1 个名额",
          s2["taken"] == 1 and s2["remaining"] == CAPACITY - 1,
          f"返回分布 {codes}，名单 {len(roster(s2))} 条，剩余 {s2['remaining']}")

    # ---- 3.3 限制在服务端成立 ----
    # 证据1：以上所有请求都是标准库 http.client 直接发的原始 HTTP，没有页面、没有 JS，
    #        前端的按钮禁用（disabled）根本没参与；约束依然成立。
    # 证据2：满员后直接打接口依然被服务端拒绝（409）。
    call("POST", "/api/admin/reset")
    for i in range(CAPACITY):
        call("POST", "/api/signup", {"user_id": f"fill{i}"})
    st_over, d_over = call("POST", "/api/signup", {"user_id": "overflow"})
    st_twice, d_twice = call("POST", "/api/signup", {"user_id": "fill0"})
    s3 = state()
    check("3.3 限制在服务端成立（原始 HTTP 直调，绕开页面/按钮）",
          st_over == 409 and s3["taken"] == CAPACITY and s3["remaining"] == 0
          and st_twice == 200,
          f"满员后新用户 HTTP {st_over}「{d_over.get('detail', '')}」；"
          f"已报名用户再提交 HTTP {st_twice}「{d_twice.get('message', '')}」，"
          f"名单仍 {s3['taken']} 条")


def page_check():
    print("\n【页面自检】")
    st, body = get_text("/")
    check("页面可以打开", st == 200 and "剩余名额" in body and "报名名单" in body,
          f"GET / → {st}，{len(body)} 字节")


def main():
    global PORT
    PORT = pick_port()
    print("=" * 78)
    print(f"需求覆盖测试（并发规模 {USERS}，名额固定 {CAPACITY}）")
    print(f"端口 {PORT}：脚本自己起服务、跑完自动关；全程标准库 http.client 直调接口")
    print("=" * 78)

    proc, logfile = start_server()
    try:
        layer2()
        proc, logfile = layer2_restart(proc, logfile)
        layer3()
        page_check()
    finally:
        stop_server(proc, logfile)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 78)
    print(f"用例结果：{passed}/{len(RESULTS)} 通过")
    for name, ok, _ in RESULTS:
        print(f"  {'✅' if ok else '❌'} {name}")
    print("=" * 78)
    if passed != len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
