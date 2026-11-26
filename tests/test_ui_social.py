"""介面情境測試：用假的 Flet 和假的雲端，模擬兩位台大學生從登入到一起吃飯。"""
import asyncio
import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fakeflet"))
sys.path.insert(0, str(HERE.parent / "src"))

import flet as ft  # noqa: E402  （假的）

if not hasattr(ft, "UPDATES"):                      # 環境裡如果裝了真的 Flet 就略過
    import pytest
    pytest.skip("需要測試用的假 Flet", allow_module_level=True)

import main as app  # noqa: E402
from core.cloud_fake import FakeCloud  # noqa: E402


def walk(c, out, seen):
    if id(c) in seen:
        return
    seen.add(id(c))
    if isinstance(c, ft.Control):
        out.append(c)
        for v in list(c.__dict__.values()):
            if isinstance(v, ft.Control):
                walk(v, out, seen)
            elif isinstance(v, (list, tuple)):
                for x in v:
                    if isinstance(x, ft.Control):
                        walk(x, out, seen)
                    elif isinstance(x, (list, tuple)):
                        for y in x:
                            if isinstance(y, ft.Control):
                                walk(y, out, seen)


def controls(page):
    out, seen = [], set()
    walk(page.controls[0], out, seen)
    for d in page.dialogs:
        walk(d, out, seen)
    return out


def texts(c):
    out = []
    walk(c, out, set())
    return [text_of(x) for x in out if type(x).__name__ == "Text"]


def text_of(t):
    v = t.__dict__.get("value")
    return v if v is not None else (t.args[0] if t.args else "")


async def call(handler, event=None):
    r = handler(event)
    if inspect.isawaitable(r):
        await r


async def click(page, label, nth=0):
    hits = [c for c in controls(page) if callable(getattr(c, "on_click", None)) and label in texts(c)]
    hits += [c for c in page.dialogs[-1:] for c in controls(page) if type(c).__name__ == "TextButton"
             and getattr(c, "content", None) == label]
    assert hits, f"找不到按鈕「{label}」；畫面上的字：{all_text(page)[:60]}"
    hits.sort(key=lambda c: len(texts(c)))                # 最貼近那幾個字的按鈕，而不是整張卡片
    await call(hits[nth].on_click)


def all_text(page):
    return [text_of(c) for c in controls(page) if type(c).__name__ == "Text"]


class Ev:
    def __init__(self, control):
        self.control = control


async def type_into(page, hint, value):
    field = next(c for c in controls(page) if type(c).__name__ == "TextField" and getattr(c, "hint_text", "") == hint)
    field.value = value
    await call(field.on_change, Ev(field))


def toasts(page):
    return [d.args[0].args[0] for d in page.dialogs if type(d).__name__ == "SnackBar"]


async def join(page, name, dept):
    await click(page, "我的")
    await click(page, "取個暱稱加入")
    await type_into(page, "暱稱（20 字內）", name)
    await type_into(page, "系所，例如：資工系（可略過）", dept)
    await click(page, "加入")


async def open_app(cloud, session="", route=""):
    """模擬一支手機打開 App：每支手機有自己的儲存空間（裡面記著自己的帳號）。"""
    ft._PREFS.clear()
    if session:
        ft._PREFS["table.session"] = session
    page = ft.Page()
    page.route = route
    await app.main(page, cloud=cloud)
    return page


def test_two_students_meet_up():
    cloud = FakeCloud()

    async def scenario():
        page = await open_app(cloud)
        assert "看看台大今天吃什麼" in all_text(page)           # 還沒加入：邀請卡＋範例

        # 安安的手機：取暱稱加入、助力、開飯局、分享一餐
        await join(page, "安安", "資工系")
        assert "安安" in all_text(page) and any("歡迎加入" in t for t in toasts(page))
        an_session = cloud.dump_session()
        await click(page, "探索")
        await click(page, "公館捷運站")            # 店變多了，從公館出發大狗麵線才排得進前 20 家
        await click(page, "大狗麵線")
        await click(page, "助力")
        assert any("助力 +1" in t for t in toasts(page))
        await click(page, "揪人一起吃")
        await click(page, "我同意飯局公約")
        await click(page, "開團")
        assert any("飯局開好了" in t for t in toasts(page))
        await call(next(c for c in controls(page) if getattr(c, "tooltip", "") == "記錄這一餐").on_click)
        await type_into(page, "店名，例如：巷尾麵舖", "大狗麵線")
        await type_into(page, "一兩句就好：今天的主角是什麼？", "麵線很滑，下雨天剛好")
        await click(page, "記下這一餐")
        assert any("分享到校園動態" in t for t in toasts(page))
        assert "麵線很滑，下雨天剛好" in all_text(page)

        # 小魚的手機：加入、看動態、同感、加入飯局（第一次要同意公約）、翻字卡、做測驗
        page = await open_app(cloud)
        await join(page, "小魚", "資工系")
        await click(page, "動態")
        text = all_text(page)
        assert any("安安 幫「大狗麵線」助力" in t for t in text) and "麵線很滑，下雨天剛好" in text
        await click(page, "同感")
        await click(page, "飯局")
        assert any("1 位同系" in t for t in all_text(page))
        await click(page, "加入")
        await click(page, "我同意")
        assert any("加入了" in t for t in toasts(page))
        await click(page, "查看")
        assert "破冰字卡，大家輪流抽" in " ".join(all_text(page))
        first = [t for t in all_text(page) if t.startswith("CARD")][0]
        await click(page, "下一張")
        assert [t for t in all_text(page) if t.startswith("CARD")][0] != first
        await click(page, "退出飯局")
        await click(page, "我的")
        await click(page, "吃貨派別測驗")
        for _ in range(8):
            option = [c for c in controls(page) if callable(getattr(c, "on_click", None))
                      and type(c).__name__ == "Container" and getattr(c, "border", None) is not None
                      and len(texts(c)) == 2][0]
            await call(option.on_click)
        assert "YOUR TABLE TYPE · 你的吃貨派別".upper() in all_text(page)
        await click(page, "設為我的稱號")
        await call(next(c for c in controls(page) if getattr(c, "tooltip", "") == "關閉").on_click)
        await click(page, "改暱稱")
        await type_into(page, "暱稱（20 字內）", "小魚兒")
        await click(page, "儲存")
        assert "小魚兒" in all_text(page)

        # 安安再打開 App：自動還是安安，看到稱號動態，排行榜有大狗麵線
        page = await open_app(cloud, an_session)
        assert "看看台大今天吃什麼" not in all_text(page)
        assert any("小魚兒 測出「" in t for t in all_text(page))
        await click(page, "探索")
        assert "1 人助力" in " ".join(all_text(page))

    asyncio.run(scenario())


def test_without_cloud_config_app_still_works():
    async def scenario():
        ft._PREFS.clear()
        page = ft.Page()
        await app.main(page)                                   # config.py 空白
        assert "我的餐桌" in all_text(page)
        await click(page, "飯局")
        assert "社群功能還沒開通" in all_text(page)
        await click(page, "探索")
        assert "社群功能還沒開通" in all_text(page)

    asyncio.run(scenario())


def test_navigation_uses_shop_name_except_chains():
    """導航用「店名＋地區」讓 Google 地圖找到正確位置；連鎖店才用座標，避免帶去別家分店。"""
    import main
    from core.data import load_restaurants
    rs = {r.name: r for r in load_restaurants()}
    url = main.walk_url(rs["築本屋"])
    assert "travelmode=walking" in url and "%E7%AF%89%E6%9C%AC%E5%B1%8B" in url    # 築本屋
    assert main.place_query(rs["麥當勞"]).replace(".", "").replace(",", "").isdigit()


def test_friend_link_and_friends_only_meetup():
    """訪談：有人覺得跟陌生人吃飯不自在 → 好友連結＋只給好友看的飯局。"""
    cloud = FakeCloud()

    async def scenario():
        page = await open_app(cloud)
        await join(page, "安安", "資工系")
        await click(page, "好友")
        code = await cloud.my_friend_code()
        link = next(t for t in all_text(page) if "/#/friend/" in t)
        assert link.endswith(code)
        assert any(type(c).__name__ == "Image" for c in controls(page))          # QR code
        an_session = cloud.dump_session()

        # 小魚打開好友連結：先取暱稱，加入後自動成為好友
        page = await open_app(cloud, route=f"/friend/{code}")
        assert any("先取個暱稱加入" in t for t in toasts(page))
        await type_into(page, "暱稱（20 字內）", "小魚")
        await click(page, "加入")
        assert any("你和 安安 成為好友了" in t for t in toasts(page))
        yu_session = cloud.dump_session()

        # 安安開「只給好友」的飯局
        page = await open_app(cloud, an_session)
        await click(page, "飯局")
        await click(page, "開一個飯局")
        await type_into(page, "店名，從清單裡選一家", "築本屋")
        await click(page, "只給好友")
        await click(page, "我同意飯局公約")
        await click(page, "開團")
        assert any("只有好友看得到" in t for t in toasts(page))

        # 不是好友的 Leo 看不到
        page = await open_app(cloud)
        await join(page, "Leo", "經濟系")
        await click(page, "飯局")
        assert "築本屋" not in all_text(page)

        # 小魚看得到、有「好友限定」
        page = await open_app(cloud, yu_session)
        await click(page, "飯局")
        assert "築本屋" in all_text(page) and any("好友限定" in t for t in all_text(page))
        await click(page, "我的")
        await click(page, "好友")
        assert "安安" in all_text(page)

    asyncio.run(scenario())
