import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from passlib.context import CryptContext
from psycopg.errors import UniqueViolation

from db import SCHEMA, connect
from rules import judge

SECRET = os.environ.get("JWT_SECRET", "pvivscan-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "scanner": {"role": "writer", "password_hash": pwd.hash("scan123456")},
    "watcher": {"role": "reader", "password_hash": pwd.hash("watch123456")},
}

ROSTER = ["阵列A-串03", "阵列B-串11", "阵列C-串05", "阵列C-串06", "阵列D-串02", "阵列D-串08"]


def dump(row):
    out = dict(row)
    for key, val in list(out.items()):
        if hasattr(val, "isoformat"):
            out[key] = val.isoformat()
    return out


def seed():
    with connect() as conn:
        conn.execute(SCHEMA)
        for code in ROSTER:
            conn.execute(
                "INSERT INTO string_roster (string_code) VALUES (%s) ON CONFLICT DO NOTHING",
                (code,),
            )
        n = conn.execute("SELECT COUNT(*) AS n FROM iv_scans").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            samples = [
                ("阵列A-串03", 41.2, 9.1, 0.78, "合格"),
                ("阵列B-串11", 38.0, 8.4, 0.61, "衰减"),
            ]
            for code, voc, isc, ff, expect in samples:
                verdict, reason = judge(ff)
                assert verdict == expect
                conn.execute(
                    """INSERT INTO iv_scans
                       (string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                        created_by, created_at, processed_at)
                       VALUES (%s,%s,%s,%s,'done',%s,%s,'scanner',%s,%s)""",
                    (code, voc, isc, ff, verdict, reason, now, now),
                )
        conn.commit()


seed()


def user_from(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(auth.split(" ", 1)[1].strip(), SECRET, algorithms=["HS256"])
    except JWTError:
        return None
    sub = payload.get("sub")
    if sub not in USERS:
        return None
    return {"username": sub, "role": payload.get("role")}


def need_login(request: Request):
    user = user_from(request)
    if user is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未登录")
    return user


def need_writer(request: Request):
    user = need_login(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅扫描员可提交IV扫描")
    return user


@get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "pv-string-iv-scan"}


@post("/api/auth/login")
async def login(request: Request) -> dict:
    data = await request.json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = USERS.get(username)
    if not user or not pwd.verify(password, user["password_hash"]):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp}, SECRET, algorithm="HS256"
    )
    return {"access_token": token, "username": username, "role": user["role"]}


@get("/api/logs")
async def list_logs(request: Request) -> list:
    need_login(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                      qr_code, created_by, created_at, processed_at
               FROM iv_scans ORDER BY id DESC"""
        ).fetchall()
        return [dump(r) for r in rows]


@get("/api/logs/{scan_id:int}")
async def get_log(request: Request, scan_id: int) -> dict:
    need_login(request)
    with connect() as conn:
        row = conn.execute(
            """SELECT id, string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                      qr_code, created_by, created_at, processed_at
               FROM iv_scans WHERE id = %s""",
            (scan_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="单据不存在")
        return dump(row)


@get("/api/labels/board")
async def label_board(request: Request) -> dict:
    need_login(request)
    with connect() as conn:
        labeled = conn.execute(
            """SELECT id, string_code, qr_code, labeled_by, labeled_at
               FROM string_labels ORDER BY id DESC"""
        ).fetchall()
        pending = conn.execute(
            """SELECT r.string_code FROM string_roster r
               WHERE NOT EXISTS (SELECT 1 FROM string_labels l
                                 WHERE l.string_code = r.string_code)
               ORDER BY r.string_code"""
        ).fetchall()
        rejections = conn.execute(
            """SELECT id, string_code, reason, attempted_by, attempted_at
               FROM scan_rejections ORDER BY id DESC"""
        ).fetchall()
        return {
            "pending": [dump(r) for r in pending],
            "labeled": [dump(r) for r in labeled],
            "rejections": [dump(r) for r in rejections],
        }


@post("/api/labels", status_code=201)
async def create_label(request: Request) -> dict:
    user = need_writer(request)
    data = await request.json()
    code = (data.get("string_code") or "").strip()
    qr = (data.get("qr_code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="组串编号不能为空")
    if not qr:
        raise HTTPException(status_code=400, detail="现场二维码不能为空")
    now = datetime.now(timezone.utc)
    try:
        with connect() as conn:
            row = conn.execute(
                """INSERT INTO string_labels (string_code, qr_code, labeled_by, labeled_at)
                   VALUES (%s,%s,%s,%s)
                   RETURNING id, string_code, qr_code, labeled_by, labeled_at""",
                (code, qr, user["username"], now),
            ).fetchone()
            conn.commit()
            return dump(row)
    except UniqueViolation as exc:
        constraint = exc.diag.constraint_name or ""
        if "qr_code" in constraint:
            raise HTTPException(status_code=409, detail=f"二维码 {qr} 已被占用，贴码失败")
        raise HTTPException(status_code=409, detail=f"组串 {code} 已贴过码，不能重复贴")


@post("/api/logs", status_code=201)
async def create_log(request: Request) -> dict:
    user = need_writer(request)
    data = await request.json()
    code = (data.get("string_code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="组串编号不能为空")
    try:
        voc = float(data.get("voc_v"))
        isc = float(data.get("isc_a"))
        ff = float(data.get("fill_factor"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="电压电流与填充因子必须是数字")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        # 贴码与入队同一次写入：码号由 INSERT...SELECT 一并落库，不拆两笔
        row = conn.execute(
            """INSERT INTO iv_scans
               (string_code, voc_v, isc_a, fill_factor, status, created_by, created_at, qr_code)
               SELECT %s,%s,%s,%s,'pending',%s,%s, l.qr_code
               FROM string_labels l WHERE l.string_code = %s
               RETURNING id, string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                         qr_code, created_by, created_at, processed_at""",
            (code, voc, isc, ff, user["username"], now, code),
        ).fetchone()
        if row is None:
            reason = "还没贴现场码，禁止入队"
            conn.execute(
                """INSERT INTO scan_rejections (string_code, reason, attempted_by, attempted_at)
                   VALUES (%s,%s,%s,%s)""",
                (code, reason, user["username"], now),
            )
            conn.commit()
            raise HTTPException(status_code=400, detail=f"组串 {code} {reason}")
        conn.commit()
        return dump(row)


app = Litestar(route_handlers=[health, login, list_logs, get_log, label_board, create_label, create_log])
