"""連到 Supabase 的社群功能：匿名加入（取暱稱就好）、助力、動態、飯局、照片上傳。

只用 Supabase 的 HTTP API，不需要安裝額外套件：
  - 網頁版（瀏覽器裡的 Python）用 pyodide 的 pyfetch
  - 電腦版用 Python 內建的 urllib
所有規則（同圈子才看得到、一天助力一次……）都寫在資料庫函式裡（supabase/schema.sql），
這裡只負責把請求送過去、把錯誤翻成看得懂的中文。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

NTU_DOMAINS = ("ntu.edu.tw", "g.ntu.edu.tw")
PHOTO_BUCKET = "meal-photos"
TAIPEI = timezone(timedelta(hours=8))

FRIENDLY = {
    "NTU_EMAIL_ONLY": "目前只開放台大信箱（@ntu.edu.tw）",
    "Database error saving new user": "目前只開放台大信箱（@ntu.edu.tw）",
    "NO_PROFILE": "請先取個暱稱加入",
    "NAME_REQUIRED": "取一個暱稱吧",
    "anonymous_provider_disabled": "Supabase 還沒開啟匿名登入（Authentication → Sign In / Providers → Anonymous）",
    "Anonymous sign-ins are disabled": "Supabase 還沒開啟匿名登入（Authentication → Sign In / Providers → Anonymous）",
    "NOT_LOGGED_IN": "請先登入",
    "TOO_MANY_OPEN": "你已經開了 3 個飯局，先等它們結束再開新的",
    "BAD_TIME": "時間要在現在到 14 天內",
    "BAD_PHOTO_PATH": "照片上傳失敗，請再試一次",
    "NOT_FOUND": "找不到這筆資料，可能已經被刪除",
    "rate limit": "寄太多次了，請過幾分鐘再試",
    "Token has expired or is invalid": "驗證碼錯誤或已過期",
    "otp_expired": "驗證碼錯誤或已過期",
}


class CloudError(Exception):
    """給使用者看的錯誤，訊息已經是中文。"""


def friendly(text: str) -> str:
    for key, msg in FRIENDLY.items():
        if key.lower() in (text or "").lower():
            return msg
    return "連線出了點問題，請稍後再試"


def is_ntu_email(email: str) -> bool:
    email = (email or "").strip().lower()
    return "@" in email and email.rsplit("@", 1)[1] in NTU_DOMAINS


def to_taipei(iso: str | None) -> datetime | None:
    """資料庫回傳的時間（UTC）→ 台灣時間，去掉時區方便和 App 其他時間比較。"""
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TAIPEI).replace(tzinfo=None)


def from_taipei(dt: datetime) -> str:
    return dt.replace(tzinfo=TAIPEI).isoformat()


# ---------- 送出 HTTP 請求（網頁版／電腦版各一種做法） ----------
async def default_http(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, bytes]:
    try:
        from pyodide.http import pyfetch                     # 網頁版
    except ImportError:
        pyfetch = None
    if pyfetch is not None:
        kwargs = {"method": method, "headers": headers}
        if body is not None:
            from js import Uint8Array                        # bytes 要轉成 JS 的陣列
            arr = Uint8Array.new(len(body))
            arr.assign(memoryview(body))
            kwargs["body"] = arr
        resp = await pyfetch(url, **kwargs)
        return resp.status, await resp.bytes()

    import urllib.error
    import urllib.request

    def run():
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    return await asyncio.to_thread(run)


class Cloud:
    def __init__(self, url: str, key: str, http=default_http, clock=time.time):
        self.url = (url or "").rstrip("/")
        self.key = key or ""
        self.http = http
        self.clock = clock
        self.session: dict | None = None       # access_token, refresh_token, expires_at, user_id, email

    # ---------- 狀態 ----------
    @property
    def enabled(self) -> bool:
        return bool(self.url and self.key)

    @property
    def logged_in(self) -> bool:
        return bool(self.session and self.session.get("access_token"))

    @property
    def user_id(self) -> str:
        return (self.session or {}).get("user_id", "")

    def dump_session(self) -> str:
        return json.dumps(self.session or {})

    def load_session(self, text: str | None):
        try:
            data = json.loads(text or "{}")
        except ValueError:
            data = {}
        self.session = data if data.get("refresh_token") else None

    def public_url(self, path: str) -> str:
        return f"{self.url}/storage/v1/object/public/{PHOTO_BUCKET}/{path}" if path else ""

    # ---------- 底層 ----------
    async def _send(self, method: str, path: str, payload=None, raw: bytes | None = None,
                    content_type: str = "application/json", auth: bool = True):
        if not self.enabled:
            raise CloudError("社群功能尚未開通")
        headers = {"apikey": self.key, "Content-Type": content_type}
        token = (self.session or {}).get("access_token") if auth else None
        if token:                                   # 沒登入時只送 apikey（新舊兩種 Supabase 金鑰都適用）
            headers["Authorization"] = f"Bearer {token}"
        body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        try:
            status, data = await self.http(method, self.url + path, headers, body)
        except CloudError:
            raise
        except Exception as exc:                    # 沒網路、被擋……
            raise CloudError("連不上伺服器，請檢查網路") from exc
        text = data.decode("utf-8", "replace") if data else ""
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            parsed = text
        return status, parsed

    @staticmethod
    def _error_text(parsed) -> str:
        if isinstance(parsed, dict):
            return " ".join(str(parsed.get(k, "")) for k in ("message", "msg", "error_description", "error", "error_code", "code"))
        return str(parsed or "")

    def _save_session(self, data: dict):
        user = data.get("user") or {}
        self.session = {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": self.clock() + int(data.get("expires_in", 3600)),
            "user_id": user.get("id", self.user_id),
            "email": user.get("email", (self.session or {}).get("email", "")),
        }

    # ---------- 加入（匿名登入：不需要信箱，帳號跟著這支手機／這個瀏覽器） ----------
    async def sign_in_anonymously(self):
        status, parsed = await self._send("POST", "/auth/v1/signup", {"data": {}}, auth=False)
        if status >= 400 or not isinstance(parsed, dict) or "access_token" not in parsed:
            raise CloudError(friendly(self._error_text(parsed)) if status >= 400 else "加入失敗，請再試一次")
        self._save_session(parsed)

    # ---------- 信箱驗證碼登入（目前沒用到，留給之後改回台大信箱時使用） ----------
    async def send_code(self, email: str):
        email = email.strip().lower()
        if not is_ntu_email(email):
            raise CloudError(FRIENDLY["NTU_EMAIL_ONLY"])
        status, parsed = await self._send("POST", "/auth/v1/otp", {"email": email, "create_user": True}, auth=False)
        if status >= 400:
            raise CloudError(friendly(self._error_text(parsed)))

    async def verify_code(self, email: str, code: str):
        status, parsed = await self._send("POST", "/auth/v1/verify",
                                          {"type": "email", "email": email.strip().lower(), "token": code.strip()},
                                          auth=False)
        if status >= 400 or not isinstance(parsed, dict) or "access_token" not in parsed:
            raise CloudError(friendly(self._error_text(parsed)) if status >= 400 else "驗證失敗，請再試一次")
        self._save_session(parsed)

    async def refresh(self) -> bool:
        if not (self.session and self.session.get("refresh_token")):
            return False
        status, parsed = await self._send("POST", "/auth/v1/token?grant_type=refresh_token",
                                          {"refresh_token": self.session["refresh_token"]}, auth=False)
        if status >= 400 or not isinstance(parsed, dict) or "access_token" not in parsed:
            self.session = None
            return False
        self._save_session(parsed)
        return True

    async def ensure_fresh(self):
        if self.session and self.session.get("expires_at", 0) - self.clock() < 60:
            await self.refresh()

    def sign_out(self):
        self.session = None

    # ---------- 呼叫資料庫函式 ----------
    async def rpc(self, name: str, **params):
        if not self.logged_in:
            raise CloudError("請先登入")
        await self.ensure_fresh()
        if not self.logged_in:
            raise CloudError("登入已過期，請重新登入")
        status, parsed = await self._send("POST", f"/rest/v1/rpc/{name}", params)
        if status == 401 and await self.refresh():
            status, parsed = await self._send("POST", f"/rest/v1/rpc/{name}", params)
        if status >= 400:
            raise CloudError(friendly(self._error_text(parsed)))
        return parsed

    async def upload_photo(self, data: bytes) -> str:
        if not self.logged_in:
            raise CloudError("請先登入")
        await self.ensure_fresh()
        path = f"{self.user_id}/{uuid.uuid4().hex}.jpg"
        status, parsed = await self._send("POST", f"/storage/v1/object/{PHOTO_BUCKET}/{path}", raw=data,
                                          content_type="image/jpeg")
        if status >= 400:
            raise CloudError("照片上傳失敗：" + friendly(self._error_text(parsed)))
        return path

    # ---------- 給介面用的功能 ----------
    async def me(self):
        return await self.rpc("me")

    async def setup_profile(self, name: str, dept: str):
        return await self.rpc("setup_profile", p_name=name, p_dept=dept)

    async def set_title(self, title: str, tribe: str):
        return await self.rpc("set_title", p_title=title, p_tribe=tribe)

    async def delete_my_data(self):
        return await self.rpc("delete_my_data")

    async def boost(self, rid: str, name: str, area: str) -> bool:
        res = await self.rpc("boost", p_restaurant_id=rid, p_name=name, p_area=area)
        return bool((res or {}).get("new"))

    async def my_boosts_today(self) -> set[str]:
        return set(await self.rpc("my_boosts_today") or [])

    async def leaderboard(self, days: int = 7, limit: int = 20) -> list[dict]:
        return await self.rpc("leaderboard", p_days=days, p_limit=limit) or []

    async def share_post(self, rid: str, name: str, area: str, note: str, tags: list[str], photo_path: str) -> int:
        return await self.rpc("share_post", p_restaurant_id=rid, p_name=name, p_area=area, p_note=note,
                              p_tags=list(tags), p_photo=photo_path)

    async def toggle_cheer(self, post_id: int) -> bool:
        return bool(await self.rpc("toggle_cheer", p_post=post_id))

    async def feed(self, limit: int = 40) -> list[dict]:
        return await self.rpc("feed", p_limit=limit) or []

    async def create_meetup(self, rid: str, name: str, area: str, starts_at: datetime | None,
                            capacity: int, theme: str, radar: bool, friends_only: bool = False) -> int:
        return await self.rpc("create_meetup", p_restaurant_id=rid, p_name=name, p_area=area,
                              p_starts_at=from_taipei(starts_at) if starts_at else None,
                              p_capacity=capacity, p_theme=theme, p_radar=radar,
                              p_friends_only=friends_only)

    async def join_meetup(self, meetup_id: int) -> tuple[bool, str]:
        res = await self.rpc("join_meetup", p_id=meetup_id) or {}
        return bool(res.get("ok")), res.get("reason", "")

    async def leave_meetup(self, meetup_id: int):
        return await self.rpc("leave_meetup", p_id=meetup_id)

    async def open_meetups(self) -> list[dict]:
        return await self.rpc("open_meetups") or []

    async def meetup_members(self, meetup_id: int) -> list[dict]:
        return await self.rpc("meetup_members_of", p_id=meetup_id) or []

    async def report(self, target_type: str, target_id: str, reason: str):
        return await self.rpc("report", p_type=target_type, p_target=str(target_id), p_reason=reason)

    async def block_user(self, user_id: str):
        return await self.rpc("block_user", p_user=user_id)

    # ---- 好友 ----
    async def my_friend_code(self) -> str:
        return await self.rpc("my_friend_code") or ""

    async def add_friend_by_code(self, code: str) -> tuple[bool, str]:
        """成功時第二個值是對方暱稱，失敗時是原因。"""
        res = await self.rpc("add_friend_by_code", p_code=code) or {}
        return bool(res.get("ok")), (res.get("name") or "") if res.get("ok") else res.get("reason", "")

    async def request_friend(self, user_id: str) -> tuple[bool, str]:
        res = await self.rpc("request_friend", p_user=user_id) or {}
        return bool(res.get("ok")), res.get("reason", "")

    async def friend_requests(self) -> list[dict]:
        return await self.rpc("friend_requests_to_me") or []

    async def respond_friend(self, user_id: str, accept: bool):
        return await self.rpc("respond_friend", p_user=user_id, p_accept=accept)

    async def my_friends(self) -> list[dict]:
        return await self.rpc("my_friends") or []

    async def remove_friend(self, user_id: str):
        return await self.rpc("remove_friend", p_user=user_id)
