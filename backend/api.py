import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from passlib.context import CryptContext
from psycopg.errors import UniqueViolation

from db import SCHEMA, connect
from rules import judge

SECRET = os.environ.get("JWT_SECRET", "pvivscan-dev-secret")
REASON_NO_CODE = "还没贴现场码"
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "scanner": {"role": "writer", "password_hash": pwd.hash("scan123456")},
    "watcher": {"role": "reader", "password_hash": pwd.hash("watch123456")},
}


def dump(row):
    out = dict(row)
    for key, val in list(out.items()):
        if hasattr(val, "isoformat"):
            out[key] = val.isoformat()
    return out


def seed():
    with connect() as conn:
        conn.execute(SCHEMA)
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
        m = conn.execute("SELECT COUNT(*) AS n FROM string_roster").fetchone()["n"]
        if m == 0:
            for code in ("阵列A-串03", "阵列B-串11", "阵列C-串05"):
                conn.execute(
                    "INSERT INTO string_roster (string_code) VALUES (%s) ON CONFLICT DO NOTHING",
                    (code,),
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


def need_writer(request: Request, detail: str = "仅扫描员可提交IV扫描"):
    user = need_login(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail=detail)
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
        binding = conn.execute(
            "SELECT qr_code FROM string_code_bindings WHERE string_code = %s", (code,)
        ).fetchone()
        if binding is None:
            # 没贴现场二维码就禁止入队：退回并写清原因，同一次写入留下退回记录
            conn.execute(
                "INSERT INTO string_roster (string_code) VALUES (%s) ON CONFLICT DO NOTHING",
                (code,),
            )
            conn.execute(
                """INSERT INTO scan_rejections (string_code, reason, attempted_by, created_at)
                   VALUES (%s,%s,%s,%s)""",
                (code, REASON_NO_CODE, user["username"], now),
            )
            conn.commit()
            raise HTTPException(status_code=400, detail=REASON_NO_CODE)
        row = conn.execute(
            """INSERT INTO iv_scans
               (string_code, voc_v, isc_a, fill_factor, status, qr_code, created_by, created_at)
               VALUES (%s,%s,%s,%s,'pending',%s,%s,%s)
               RETURNING id, string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                         qr_code, created_by, created_at, processed_at""",
            (code, voc, isc, ff, binding["qr_code"], user["username"], now),
        ).fetchone()
        conn.commit()
        return dump(row)


@get("/api/codes/board")
async def codes_board(request: Request) -> dict:
    need_login(request)
    with connect() as conn:
        pending = conn.execute(
            """SELECT r.string_code FROM string_roster r
               LEFT JOIN string_code_bindings b ON b.string_code = r.string_code
               WHERE b.id IS NULL ORDER BY r.string_code"""
        ).fetchall()
        pasted = conn.execute(
            """SELECT id, string_code, qr_code, pasted_by, pasted_at
               FROM string_code_bindings ORDER BY id DESC"""
        ).fetchall()
        rejections = conn.execute(
            """SELECT id, string_code, reason, attempted_by, created_at
               FROM scan_rejections ORDER BY id DESC"""
        ).fetchall()
        return {
            "pending": [r["string_code"] for r in pending],
            "pasted": [dump(r) for r in pasted],
            "rejections": [dump(r) for r in rejections],
        }


@post("/api/codes/paste", status_code=201)
async def paste_code(request: Request) -> dict:
    user = need_writer(request, detail="仅扫描员可贴码")
    data = await request.json()
    code = (data.get("string_code") or "").strip()
    qr = (data.get("qr_code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="组串编号不能为空")
    if not qr:
        raise HTTPException(status_code=400, detail="现场码号不能为空")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        try:
            # 贴码和入队必须同一次写入：绑定与名册归位在同一事务里一次提交
            with conn.transaction():
                row = conn.execute(
                    """INSERT INTO string_code_bindings
                       (string_code, qr_code, pasted_by, pasted_at)
                       VALUES (%s,%s,%s,%s)
                       RETURNING id, string_code, qr_code, pasted_by, pasted_at""",
                    (code, qr, user["username"], now),
                ).fetchone()
                conn.execute(
                    "INSERT INTO string_roster (string_code) VALUES (%s) ON CONFLICT DO NOTHING",
                    (code,),
                )
        except UniqueViolation as exc:
            name = exc.diag.constraint_name if exc.diag else ""
            if name == "uq_binding_qr":
                detail = "该码已被占用，贴码失败"
            elif name == "uq_binding_string":
                detail = "该组串已贴过现场码"
            else:
                detail = "该码已被占用，贴码失败"
            raise HTTPException(status_code=409, detail=detail)
        conn.commit()
        return dump(row)


app = Litestar(
    route_handlers=[health, login, list_logs, create_log, codes_board, paste_code]
)
