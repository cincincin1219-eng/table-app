import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.cloud import Cloud, CloudError, is_ntu_email, to_taipei  # noqa: E402
from core.cloud_fake import FakeCloud  # noqa: E402
from core.social import QUIZ, TRIBES, icebreaker_cards, score_quiz  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class MockHttp:
    """記錄每個請求，依網址回傳事先準備的回應。"""

    def __init__(self, routes):
        self.routes = routes            # [(網址片段, status, body)]，用過就移除
        self.calls = []

    async def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, json.loads(body) if body and body[:1] in b"{[" else body))
        for i, (frag, status, payload) in enumerate(self.routes):
            if frag in url:
                self.routes.pop(i)
                return status, json.dumps(payload).encode()
        raise AssertionError(f"沒有準備 {url} 的回應")


SESSION = {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600,
           "user": {"id": "uid-1", "email": "b11@ntu.edu.tw"}}


def test_ntu_email_check():
    assert is_ntu_email("B11000001@ntu.edu.tw") and is_ntu_email("r12@g.ntu.edu.tw")
    assert not is_ntu_email("a@gmail.com") and not is_ntu_email("ntu.edu.tw")


def test_disabled_without_config():
    c = Cloud("", "")
    assert not c.enabled
    with pytest.raises(CloudError):
        run(c.send_code("b11@ntu.edu.tw"))


def test_login_flow_and_rpc_headers():
    http = MockHttp([("/auth/v1/otp", 200, {}), ("/auth/v1/verify", 200, SESSION),
                     ("/rest/v1/rpc/boost", 200, {"new": True})])
    c = Cloud("https://x.supabase.co/", "ANON", http=http, clock=lambda: 1000)
    with pytest.raises(CloudError, match="台大信箱"):
        run(c.send_code("me@gmail.com"))             # 不送出請求
    run(c.send_code(" B11@ntu.edu.tw "))
    assert http.calls[0][3] == {"email": "b11@ntu.edu.tw", "create_user": True}
    run(c.verify_code("b11@ntu.edu.tw", "123456"))
    assert http.calls[1][3] == {"type": "email", "email": "b11@ntu.edu.tw", "token": "123456"}
    assert c.logged_in and c.user_id == "uid-1"
    assert run(c.boost("osm1", "巷尾麵舖", "公館")) is True
    method, url, headers, body = http.calls[2]
    assert url == "https://x.supabase.co/rest/v1/rpc/boost"
    assert headers["Authorization"] == "Bearer AT" and headers["apikey"] == "ANON"
    assert body == {"p_restaurant_id": "osm1", "p_name": "巷尾麵舖", "p_area": "公館"}


def test_expired_token_refreshes_then_retries():
    http = MockHttp([("/rest/v1/rpc/me", 401, {"message": "JWT expired"}),
                     ("grant_type=refresh_token", 200, dict(SESSION, access_token="AT2")),
                     ("/rest/v1/rpc/me", 200, {"display_name": "安安"})])
    c = Cloud("https://x.supabase.co", "ANON", http=http, clock=lambda: 0)
    c.load_session(json.dumps({"access_token": "OLD", "refresh_token": "RT", "expires_at": 99999, "user_id": "uid-1"}))
    assert run(c.me()) == {"display_name": "安安"}
    assert http.calls[-1][2]["Authorization"] == "Bearer AT2"


def test_errors_become_chinese():
    http = MockHttp([("/auth/v1/otp", 500, {"msg": "Database error saving new user"}),
                     ("/auth/v1/otp", 429, {"msg": "email rate limit exceeded"}),
                     ("/auth/v1/verify", 403, {"msg": "Token has expired or is invalid"})])
    c = Cloud("https://x.supabase.co", "ANON", http=http)
    with pytest.raises(CloudError, match="台大信箱"):
        run(c.send_code("b11@ntu.edu.tw"))
    with pytest.raises(CloudError, match="寄太多次"):
        run(c.send_code("b11@ntu.edu.tw"))
    with pytest.raises(CloudError, match="驗證碼"):
        run(c.verify_code("b11@ntu.edu.tw", "000000"))


def test_network_down_is_friendly():
    async def down(*a):
        raise OSError("no network")
    c = Cloud("https://x.supabase.co", "ANON", http=down)
    with pytest.raises(CloudError, match="連不上"):
        run(c.send_code("b11@ntu.edu.tw"))


def test_upload_path_is_in_own_folder():
    http = MockHttp([("/storage/v1/object/meal-photos/uid-1/", 200, {"Key": "ok"})])
    c = Cloud("https://x.supabase.co", "ANON", http=http, clock=lambda: 0)
    c.load_session(json.dumps({"access_token": "AT", "refresh_token": "RT", "expires_at": 99999, "user_id": "uid-1"}))
    path = run(c.upload_photo(b"\xff\xd8jpeg"))
    assert path.startswith("uid-1/") and path.endswith(".jpg")
    assert http.calls[0][2]["Content-Type"] == "image/jpeg" and http.calls[0][3] == b"\xff\xd8jpeg"
    assert c.public_url(path).endswith(f"/storage/v1/object/public/meal-photos/{path}")


def test_to_taipei():
    assert to_taipei("2026-11-19T04:10:00+00:00") == datetime(2026, 11, 19, 12, 10)
    assert to_taipei("2026-11-19T04:10:00Z") == datetime(2026, 11, 19, 12, 10)


def test_quiz_titles():
    assert len(QUIZ) == 8
    tribe, title, _ = score_quiz([0, 0, 0, 3, 0, 3, 0, 1])
    assert tribe == "taro" and title == TRIBES["taro"][0]
    assert score_quiz([1, 1, 2, 1, 0, 1, 1, 2])[0] == "explorer"


def test_icebreaker_is_stable_per_meetup_and_uses_shared_points():
    a = icebreaker_cards(7, "巷尾麵舖", "公館", ["冬至食堂"], ["芋頭派守護神"])
    b = icebreaker_cards(7, "巷尾麵舖", "公館", ["冬至食堂"], ["芋頭派守護神"])
    assert a == b and len(a[0]) == 8 and len(a[1]) == 2
    assert "冬至食堂" in a[0][0] and any("芋頭派守護神" in c for c in a[0])
    assert all("{" not in c for c in a[0])


def test_fake_cloud_rules():
    now = datetime(2026, 11, 19, 12, 0)
    fc = FakeCloud(now=lambda: now)

    async def login(email, name, dept):
        fc.sign_out()
        await fc.send_code(email)
        await fc.verify_code(email, "123456")
        if not await fc.me():
            await fc.setup_profile(name, dept)
        return fc.user_id

    async def scenario():
        an = await login("b1@ntu.edu.tw", "安安", "資工系")
        assert await fc.boost("osm1", "巷尾麵舖", "公館") and not await fc.boost("osm1", "巷尾麵舖", "公館")
        mid = await fc.create_meetup("osm1", "巷尾麵舖", "公館", now + timedelta(hours=3), 2, "宵夜", False)
        await login("b2@ntu.edu.tw", "小魚", "資工系")
        await fc.boost("osm1", "巷尾麵舖", "公館")
        rows = await fc.open_meetups()
        assert rows[0]["shared_places"] == ["巷尾麵舖"] and rows[0]["same_dept"] == 1
        assert await fc.join_meetup(mid) == (True, "")
        await login("b3@ntu.edu.tw", "Leo", "經濟系")
        assert await fc.join_meetup(mid) == (False, "人數已滿")
        await fc.block_user(an)
        assert all(r["actor_name"] != "安安" for r in await fc.feed())
        board = await fc.leaderboard()
        assert board[0]["restaurant_name"] == "巷尾麵舖" and board[0]["score"] == 2

    run(scenario())


def test_anonymous_join():
    http = MockHttp([("/auth/v1/signup", 200, SESSION), ("/rest/v1/rpc/setup_profile", 200, {"display_name": "安安"}),
                     ("/auth/v1/signup", 422, {"error_code": "anonymous_provider_disabled",
                                                "msg": "Anonymous sign-ins are disabled"})])
    c = Cloud("https://x.supabase.co", "ANON", http=http, clock=lambda: 0)
    run(c.sign_in_anonymously())
    assert http.calls[0][3] == {"data": {}} and "Authorization" not in http.calls[0][2]
    assert c.logged_in and run(c.setup_profile("安安", ""))["display_name"] == "安安"
    with pytest.raises(CloudError, match="匿名登入"):
        run(Cloud("https://x.supabase.co", "ANON", http=http).sign_in_anonymously())


def test_fake_cloud_friends():
    now = datetime(2026, 11, 25, 12, 0)
    fc = FakeCloud(now=lambda: now)

    async def login(email, name):
        fc.sign_out()
        await fc.send_code(email)
        await fc.verify_code(email, "123456")
        if not await fc.me():
            await fc.setup_profile(name, "")
        return fc.user_id

    async def scenario():
        an = await login("f1@ntu.edu.tw", "安安")
        code = await fc.my_friend_code()
        mid = await fc.create_meetup("osm1", "築本屋", "公館", now + timedelta(hours=3), 4, "", False, True)
        await login("f2@ntu.edu.tw", "小魚")
        assert not [m for m in await fc.open_meetups() if m["id"] == mid]          # 還不是好友：看不到
        assert await fc.join_meetup(mid) == (False, "這是好友限定的飯局")
        assert await fc.add_friend_by_code(code.lower()) == (True, "安安")
        rows = [m for m in await fc.open_meetups() if m["id"] == mid]
        assert rows[0]["friends_only"] and rows[0]["host_is_friend"]
        assert await fc.join_meetup(mid) == (True, "")
        assert all(a.get("ref_id") != mid for a in await fc.feed())                  # 不上校園動態
        leo = await login("f3@ntu.edu.tw", "Leo")
        assert await fc.request_friend(an) == (False, "一起吃過飯局才能加好友")
        pub = await fc.create_meetup("osm2", "好呷拉麵", "公館", now + timedelta(hours=2), 4, "", False)
        await login("f1@ntu.edu.tw", "安安")
        await fc.join_meetup(pub)
        assert await fc.request_friend(leo) == (True, "已送出邀請")
        await login("f3@ntu.edu.tw", "Leo")
        assert [r["display_name"] for r in await fc.friend_requests()] == ["安安"]
        await fc.respond_friend(an, True)
        assert [f["display_name"] for f in await fc.my_friends()] == ["安安"]

    run(scenario())
