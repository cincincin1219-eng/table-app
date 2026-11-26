"""Table / 席間 ── 台大附近的餐桌（Flet 介面）

下方毛玻璃導覽列：
  動態     校園動態（大家的食記、助力、飯局、稱號）／我的餐桌
  探索     30 秒決定一餐 ＋ 愛店排行榜（助力）＋ 台大附近現在有開的店
  ＋       記錄這一餐：店名、照片、標籤、短評、人均、人數；可以分享到校園動態
  飯局     吃飯雷達（1 小時內有效）、2～6 人飯局、破冰字卡
  我的     個人資料與稱號、紀錄牆、每月 Dump、想去清單

社群功能（登入、助力、動態、飯局）用 Supabase，設定在 config.py；沒設定時 App 照常運作。
自己的飯紀錄、照片、想去清單仍然只存在使用者自己的手機或瀏覽器。

執行：
  flet run --web src/main.py    # 瀏覽器
  flet run src/main.py          # 桌面視窗
"""
from __future__ import annotations

import base64
import json
import random
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import flet as ft

from config import SITE_URL, SUPABASE_ANON_KEY, SUPABASE_URL
from core import journal
from core.cloud import Cloud, CloudError, to_taipei
from core.data import load_buildings, load_restaurants
from core.filters import crowd_hint, minutes_until_close, walking_minutes
from core.models import DAYS, Query, Recommendation, Restaurant
from core.recommend import explain_empty, recommend, surprise
from core.qr import qr_png
from core.social import QUIZ, icebreaker_cards, score_quiz

try:                                   # 回顧圖與照片縮圖需要 Pillow
    from core.recap import (ensure_serif_font, make_thumbnail, render_photo_dump, render_stats_card,
                            render_title_card, serif_ready)
    HAS_PILLOW = True
except ImportError:                    # 沒裝 Pillow 時其他功能照常
    HAS_PILLOW = False

# ---------- 設計規範（跟設計稿一致） ----------
BG = "#EFE8DE"          # 奶茶米：毛玻璃後面的底色
BG_TOP = "#F6F1EA"      # 背景漸層（上）
BG_BOTTOM = "#E8DED1"   # 背景漸層（下）
CARD = "#FFFFFF"        # 紙白
LINE = "#E4DBCE"        # 暖灰線
LINE_SOFT = "#EFE8DE"
INK = "#2C2A25"         # 深炭灰
BODY = "#47443D"
MUTED = "#7A756B"       # 霧灰（對比度夠）
OLIVE = "#73725A"       # 橄欖綠：主要按鈕、選中的標籤
OLIVE_DARK = "#5C5B46"
ON_OLIVE = "#F8F4EC"    # 橄欖綠上的字
ACCENT = "#B85D43"      # 陶土紅：只用在「同感」「想去」
EMPTY = "#EFE9DF"       # 沒照片時的底色
AVATAR_COLORS = ["#EFE6DA", "#E4E8DD", "#F1E1D8", "#E9E3EC", "#E2E6EA"]
PAD = 20                # 螢幕左右留白
GAP = 28                # 卡片間距
MAX_W = 440             # 電腦上看時，畫面最寬 440

ASSETS = Path(__file__).parent / "assets"
SERIF_FILE = ASSETS / "fonts" / "NotoSerifTC-Medium.otf"
LOGO_FILE = ASSETS / "fonts" / "Logo-Italic.ttf"
PACKAGE_FONTS = Path(__file__).parent / "core" / "fonts"

TAIPEI = timezone(timedelta(hours=8))   # 台灣沒有日光節約時間，固定 UTC+8
KEY_ENTRIES = "ntu_meal.entries"
KEY_WISH = "ntu_meal.wishlist"
KEY_CHEERS = "ntu_meal.cheers"
KEY_SESSION = "table.session"
KEY_PACT = "table.pact"
WEEKDAYS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
WEEKDAYS_EN = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
MONTHS_EN = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

PRESET_TAGS = ["一人食", "便當", "麵", "飯", "素食", "早午餐", "咖啡", "甜點", "宵夜", "聚餐", "平價", "排隊"]
TIME_OPTIONS = [(30, "30 分鐘", "趕時間"), (45, "45 分鐘", "有點趕"), (60, "1 小時", "正常吃"),
                (90, "1.5 小時", "慢慢吃"), (120, "2 小時", "很閒")]
BUDGET_OPTIONS = [(80, "80 元內", "省錢模式"), (100, "100 元內", "學生價"), (150, "150 元內", "小確幸"),
                  (200, "200 元內", "吃好一點"), (9999, "不設限", "犒賞自己")]
PARTY_OPTIONS = [(1, "一個人", "自己吃"), (2, "兩個人", ""), (4, "三到四人", "小團體"), (6, "五人以上", "聚餐")]
DIET_OPTIONS = [("vegetarian", "素食"), ("vegan", "全素"), ("not_spicy", "不吃辣"), ("high_protein", "高蛋白")]
ALLERGY_OPTIONS = [("peanut", "花生"), ("shellfish", "甲殼類"), ("dairy", "乳製品"), ("egg", "蛋"), ("gluten", "麩質")]
QUESTIONS = 5


def taipei_now() -> datetime:
    # 不依賴電腦或瀏覽器的時區：發佈成網站後在瀏覽器裡跑，系統時區可能是 UTC。
    return datetime.now(TAIPEI).replace(tzinfo=None)


# 連鎖店附近有好幾家分店，用店名找可能帶去別家，所以改用座標
CHAINS = {"麥當勞", "摩斯漢堡", "頂呱呱", "CoCo壹番屋", "壽司郎", "八方雲集", "食其家", "吉野家", "漢堡王",
          "肯德基", "Subway", "bb.q Chicken", "星巴克", "路易莎咖啡", "85度C"}
# 加上地區，讓 Google 地圖找到台大附近那一家
AREA_HINT = {"校內": "國立臺灣大學", "公館": "台北市 公館", "溫州街": "台北市 溫州街",
             "科技大樓/和平東路": "台北市 和平東路", "台科大/基隆路": "台北市 基隆路"}


def place_query(r: Restaurant) -> str:
    """給 Google 地圖的目的地：一般店用「店名＋地區」，讓 Google 用它自己的店家位置；
    連鎖店用座標，才不會被帶到別家分店。"""
    if r.name in CHAINS:
        return f"{r.lat},{r.lng}"
    return f"{r.name} {AREA_HINT.get(r.area, '台北市')}"


def walk_url(r: Restaurant) -> str:
    return ("https://www.google.com/maps/dir/?api=1&travelmode=walking&destination="
            + urllib.parse.quote(place_query(r)))


def map_url(r: Restaurant) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(place_query(r))


def time_of_day(h: int) -> str:
    return "早上" if h < 11 else "中午" if h < 14 else "下午" if h < 17 else "晚上" if h < 21 else "深夜"


def relative_time(dt: datetime, now: datetime) -> str:
    """大安區 · 昨晚 這種說法。"""
    days = (now.date() - dt.date()).days
    tod = time_of_day(dt.hour)
    if days <= 0:
        return "今天" + tod
    if days == 1:
        return "昨晚" if tod in ("晚上", "深夜") else "昨天" + tod
    if days < 7:
        return f"{days} 天前"
    return f"{dt.month}/{dt.day}"


def full_date(dt: datetime) -> str:
    return f"{dt.month} 月 {dt.day} 日 {WEEKDAYS[dt.weekday()]} {time_of_day(dt.hour)}"


def fmt_minutes(m: int) -> str:
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def hours_today(r: Restaurant, now: datetime) -> str:
    spans = r.hours.get(DAYS[now.weekday()], [])
    if not spans:
        return "今天公休"
    return "今天 " + "、".join(f"{fmt_minutes(s)}–{fmt_minutes(e)}" for s, e in spans)


def price_text(r: Restaurant, prefix: str = "約 ") -> str:
    """價格 0 = 還沒填；資料標記「估價」的價格後面加（估）。"""
    if r.price <= 0:
        return "價格未填"
    return f"{prefix}{r.price} 元" + ("（估）" if "估" in r.last_checked else "")


def unverified(r: Restaurant) -> bool:
    lc = r.last_checked
    return any(k in lc for k in ("預覽", "OSM", "估", "待確認", "約略"))


def data_note(r: Restaurant) -> str:
    """說明這家店的資料從哪來、哪裡還沒確認。"""
    lc, bits = r.last_checked, []
    if "圖鑑" in lc:
        bits.append("價格來自台大美食圖鑑實測")
    elif "估" in lc:
        bits.append("價格是估計")
    if "OSM" in lc:
        bits.append("營業時間來自 OpenStreetMap")
    elif "待確認" in lc:
        bits.append("營業時間是推估")
    if "約略" in lc:
        bits.append("位置是約略的")
    if not bits and unverified(r):
        bits.append("資料還沒人工確認")
    if bits:
        return "、".join(bits) + "；過敏資訊請向店家確認。"
    return "過敏與營業資訊僅供參考，請向店家確認。"


def color_for(text: str) -> str:
    return AVATAR_COLORS[sum(ord(c) for c in text) % len(AVATAR_COLORS)]


# ---------- 一篇食記（自己的紀錄或好友範例，畫面上用同一種卡片） ----------
@dataclass
class Post:
    id: str
    author: str
    initial: str
    at: datetime
    place: str
    area: str = ""
    tags: list = field(default_factory=list)
    note: str = ""
    photo: object = None            # bytes（自己拍的）或 assets 路徑（範例）
    extra_photos: list = field(default_factory=list)
    price: int = 0
    party: int = 0
    walk: int = 0
    restaurant_id: str = ""
    entry: journal.MealEntry | None = None
    demo: bool = False
    quote: str = ""
    dishes: list = field(default_factory=list)
    cheered_by: list = field(default_factory=list)
    cloud_id: int | None = None     # 校園動態裡的食記
    cheered: bool = False
    own: bool = False               # 自己分享到校園的
    dept: str = ""
    actor_id: str = ""

    @property
    def mine(self) -> bool:
        return self.entry is not None


def demo_posts(now: datetime) -> list[Post]:
    """好友動態範例（虛構的人與店）。等有帳號系統後換成真的好友。"""
    return [
        Post("demo-a", "安安", "安", now - timedelta(days=1, hours=2), "小島酒室", "大安區",
             ["自然酒", "季節料理"], "炭烤白蘆筍配發酵奶油，酸度剛剛好。適合一個人坐吧台，慢慢喝完一杯。\n"
             "店主推薦的橘酒很乾淨，不搶味道。最後用酸種麵包把盤子上的奶油抹乾淨。",
             "demo/feed_wine.jpg", ["demo/detail_bread.jpg"], price=0, party=1, demo=True,
             quote="好的小店，會讓你想一個人再來一次。",
             dishes=[("炭烤白蘆筍", "發酵奶油"), ("酸種麵包", "可續"), ("橘酒一杯", "店主推薦")],
             cheered_by=["小魚", "Leo"]),
        Post("demo-b", "小魚", "魚", now - timedelta(days=2, hours=1), "冬至食堂", "中正區",
             ["定食", "一人食"], "味噌湯是今晚的主角。下雨天，這裡的燈很溫柔。",
             "demo/feed_teishoku.jpg", price=0, party=1, demo=True,
             dishes=[("鹽烤鯖魚定食", "附味噌湯"), ("玉子燒", "")], cheered_by=["安安"]),
        Post("demo-c", "Leo", "L", now - timedelta(days=3, hours=-3), "巷尾麵舖", "公館",
             ["手打麵", "宵夜"], "清湯，麵條很有嚼勁。十點過後的公館，只剩這一盞燈還亮著。",
             "demo/feed_noodle.jpg", price=0, party=2, demo=True,
             dishes=[("清湯手打麵", "加蛋"), ("燙青菜", "")]),
    ]


# ---------- 資料存取：存在使用者自己的手機或瀏覽器 ----------
class Store:
    def __init__(self):
        self.prefs = ft.SharedPreferences()
        self.entries: list[journal.MealEntry] = []
        self.photos: dict[str, bytes] = {}
        self.wish: list[dict] = []          # [{"key","name","area","lat","lng"}]
        self.cheers: set[str] = set()
        self.pact = False                   # 是否同意過飯局公約

    @staticmethod
    def photo_key(entry_id: str) -> str:
        return f"ntu_meal.photo.{entry_id}"

    async def _get(self, key):
        try:
            return await self.prefs.get(key)
        except Exception:
            return None

    async def load(self):
        self.entries = journal.loads(await self._get(KEY_ENTRIES))
        for e in self.entries:
            if not e.has_photo:
                continue
            b64 = await self._get(self.photo_key(e.id))
            if b64:
                self.photos[e.id] = base64.b64decode(b64)
            else:
                e.has_photo = False
        try:
            self.wish = [w for w in json.loads(await self._get(KEY_WISH) or "[]") if isinstance(w, dict)]
        except ValueError:
            self.wish = []
        try:
            self.cheers = set(json.loads(await self._get(KEY_CHEERS) or "[]"))
        except ValueError:
            self.cheers = set()
        self.pact = (await self._get(KEY_PACT)) == "1"

    async def set_pact(self):
        if not self.pact:
            self.pact = True
            try:
                await self.prefs.set(KEY_PACT, "1")
            except Exception:
                pass

    async def save(self):
        await self.prefs.set(KEY_ENTRIES, journal.dumps(self.entries))

    async def add(self, entry: journal.MealEntry):
        self.entries.append(entry)
        await self.save()

    async def set_photo(self, entry: journal.MealEntry, data: bytes):
        thumb = make_thumbnail(data) if HAS_PILLOW else data
        await self.prefs.set(self.photo_key(entry.id), base64.b64encode(thumb).decode())
        self.photos[entry.id] = thumb
        entry.has_photo = True
        await self.save()

    async def delete(self, entry: journal.MealEntry):
        self.entries = [e for e in self.entries if e.id != entry.id]
        if entry.id in self.photos:
            self.photos.pop(entry.id)
            try:
                await self.prefs.remove(self.photo_key(entry.id))
            except Exception:
                pass
        await self.save()

    # 想去清單
    def wished(self, key: str) -> bool:
        return any(w["key"] == key for w in self.wish)

    async def toggle_wish(self, item: dict) -> bool:
        if self.wished(item["key"]):
            self.wish = [w for w in self.wish if w["key"] != item["key"]]
        else:
            self.wish.insert(0, item)
        await self.prefs.set(KEY_WISH, json.dumps(self.wish, ensure_ascii=False))
        return self.wished(item["key"])

    async def toggle_cheer(self, post_id: str) -> bool:
        self.cheers ^= {post_id}
        await self.prefs.set(KEY_CHEERS, json.dumps(sorted(self.cheers)))
        return post_id in self.cheers


# ==================== 小元件 ====================
def border_all(width: float, color: str):
    try:
        return ft.Border.all(width, color)
    except AttributeError:                  # 舊版 Flet
        return ft.border.all(width, color)


def hairline(color: str = LINE):
    return border_all(1, color)


def set_icon(icon_control, value):
    """Flet 1.x 的 Icon 屬性叫 icon，舊版叫 name。"""
    if hasattr(icon_control, "icon"):
        icon_control.icon = value
    else:
        icon_control.name = value


def bottom_line(color: str = LINE):
    return ft.Border(bottom=ft.BorderSide(1, color))


def top_line(color: str = LINE_SOFT):
    return ft.Border(top=ft.BorderSide(1, color))


def pad(left=0, top=0, right=0, bottom=0):
    return ft.Padding(left=left, top=top, right=right, bottom=bottom)


async def main(page: ft.Page, cloud=None):
    page.title = "Table / 席間｜台大附近的餐桌"
    page.bgcolor = BG
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=INK)

    # 路徑不加開頭的「/」：網站放在子路徑（例如 GitHub Pages 的 /table-app/）時，
    # "/fonts/…" 會指到網域根目錄而 404；"fonts/…" 會跟著網站所在的位置走。
    # 網頁版的 Python 讀不到 assets/：宋體由瀏覽器直接從網站載入，Logo 則檢查 core/fonts/ 裡的那份。
    fonts = {}
    if SERIF_FILE.exists() or page.web:
        fonts["Serif"] = "fonts/" + SERIF_FILE.name
    if LOGO_FILE.exists() or (PACKAGE_FONTS / LOGO_FILE.name).exists():
        fonts["Logo"] = "fonts/" + LOGO_FILE.name
    if fonts:
        page.fonts = fonts
    # 沒下載字體時：Mac 桌面版用內建的「宋體」，網頁版用預設字體
    serif_family = "Serif" if "Serif" in fonts else (None if page.web else "Songti TC")
    logo_family = "Logo" if "Logo" in fonts else serif_family

    restaurants = load_restaurants()
    buildings = load_buildings()
    by_id = {r.id: r for r in restaurants}
    store = Store()
    await store.load()
    if cloud is None:
        cloud = Cloud(SUPABASE_URL, SUPABASE_ANON_KEY)
    if cloud.enabled:
        cloud.load_session(await store._get(KEY_SESSION))

    now0 = taipei_now()
    state = {
        "tab": "feed", "overlay": None, "feed_scope": "campus" if cloud.enabled else "mine",
        "profile": None, "feed": None, "meetups": None, "board": None, "board_days": 7, "boosted": set(),
        "origin": "lib", "area": "全部", "explore_limit": 20,
        "step": 1, "minutes": None, "budget": None, "party": None, "tags": set(), "allergens": set(),
        "journal_view": "grid", "recap_year": now0.year, "recap_month": now0.month, "recap_kind": "dump",
        "friends": None, "pending_friend": None,
    }

    def content_width() -> int:
        w = getattr(page, "width", None) or 390
        return int(min(w, MAX_W))

    # ---------- 文字 ----------
    def sans(value, size=14, color=INK, weight=None, max_lines=None, height=None, center=False, spacing=None):
        style = ft.TextStyle(height=height, letter_spacing=spacing) if (height or spacing) else None
        return ft.Text(str(value), size=size, color=color, weight=weight, max_lines=max_lines,
                       overflow=ft.TextOverflow.ELLIPSIS if max_lines else None, style=style,
                       text_align=ft.TextAlign.CENTER if center else None)

    def serif(value, size=21, color=INK, weight=ft.FontWeight.W_500, max_lines=None, height=1.4, center=False):
        return ft.Text(str(value), size=size, color=color, weight=weight, font_family=serif_family,
                       max_lines=max_lines, overflow=ft.TextOverflow.ELLIPSIS if max_lines else None,
                       style=ft.TextStyle(height=height, letter_spacing=size * 0.02),
                       text_align=ft.TextAlign.CENTER if center else None)

    def caps(value, size=11, color=MUTED):
        """英文大寫小標：字距 0.08em。"""
        return sans(str(value).upper(), size, color, spacing=size * 0.08 + 0.6)

    def toast(message: str):
        page.show_dialog(ft.SnackBar(sans(message, 14, BG), bgcolor=INK))

    def link_button(label: str, url: str, filled: bool = True, expand: bool = False, icon=None, height: int = 48):
        """打開外部連結（導航、地圖）的按鈕。用按鈕內建的 url，瀏覽器才不會當成彈出視窗擋掉。"""
        fg = ON_OLIVE if filled else INK
        row = [ft.Icon(icon, size=18, color=fg)] if icon else []
        row.append(sans(label, 14 if height >= 44 else 13, fg, ft.FontWeight.W_500, spacing=0.6))
        return ft.Button(
            content=ft.Row(row, spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            url=url, expand=expand, height=height, color=fg,
            bgcolor=OLIVE if filled else ft.Colors.with_opacity(0.55, "#FFFFFF"),
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=height / 2), elevation=0,
                                 side=None if filled else ft.BorderSide(1, ft.Colors.with_opacity(0.9, "#FFFFFF"))),
        )

    def avatar(initial: str, size: int = 28, bg: str | None = None):
        return ft.Container(width=size, height=size, border_radius=size / 2, bgcolor=bg or color_for(initial),
                            alignment=ft.Alignment.CENTER, content=serif(initial, size * 0.46, height=1.0))

    def pill(label: str, on_click, filled: bool = True, expand: bool = False, icon=None, accent: bool = False,
             trailing=None):
        """主要按鈕＝橄欖綠漸層；次要按鈕＝毛玻璃。（accent 參數保留給舊程式，樣式已統一）"""
        fg = ON_OLIVE if filled else INK
        row = [ft.Icon(icon, size=19, color=fg)] if icon else []
        row.append(sans(label, 15, fg, ft.FontWeight.W_500, spacing=1.2))
        if trailing:
            row.append(ft.Icon(trailing, size=18, color=fg))
        return ft.Container(
            height=52, border_radius=26, expand=expand, on_click=on_click, ink=True,
            **(olive_fill() if filled else GLASS_KW),
            padding=pad(22, 0, 22, 0), alignment=ft.Alignment.CENTER,
            content=ft.Row(row, spacing=10, tight=True, alignment=ft.MainAxisAlignment.CENTER),
        )

    def text_tab(label: str, selected: bool, on_click):
        return ft.Container(
            on_click=on_click, padding=pad(0, 10, 0, 10),
            border=ft.Border(bottom=ft.BorderSide(1.5, INK if selected else "#00000000")),
            content=sans(label, 14, INK if selected else MUTED, ft.FontWeight.W_500 if selected else None),
        )

    def chip(label: str, selected: bool, on_click, icon=None):
        fg = ON_OLIVE if selected else INK
        row = [ft.Icon(icon, size=17, color=fg)] if (icon and selected) else []
        row.append(sans(label, 13.5, fg, spacing=1.0))
        return ft.Container(
            height=40, border_radius=20, padding=pad(16, 0, 16, 0), alignment=ft.Alignment.CENTER,
            on_click=on_click, **(olive_fill() if selected else GLASS_KW),
            content=ft.Row(row, spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER),
        )

    def section_label(en: str, zh: str):
        return caps(f"{en} · {zh}")

    # ---------- 毛玻璃風格 ----------
    GLASS_KW = {"bgcolor": ft.Colors.with_opacity(0.52, "#FFFFFF"),
                "border": border_all(1, ft.Colors.with_opacity(0.9, "#FFFFFF")),
                "shadow": ft.BoxShadow(blur_radius=28, spread_radius=-6,
                                       color=ft.Colors.with_opacity(0.10, "#5C4B36"), offset=ft.Offset(0, 10))}

    def olive_fill() -> dict:
        return {"gradient": ft.LinearGradient(begin=ft.Alignment(-1, -1), end=ft.Alignment(1, 1),
                                              colors=[OLIVE, OLIVE_DARK]),
                "shadow": ft.BoxShadow(blur_radius=18, spread_radius=-4,
                                       color=ft.Colors.with_opacity(0.35, OLIVE_DARK), offset=ft.Offset(0, 8))}

    def thumb(rid: str, name: str, size: int = 64):
        """店家小圖：自己拍過的照片 → 同學分享的照片 → 店名第一個字。"""
        src = None
        for e in journal.sort_newest_first(store.entries):
            if e.restaurant_id == rid and store.photos.get(e.id) is not None:
                src = store.photos[e.id]
                break
        if src is None:
            for a in state["feed"] or []:
                if a.get("restaurant_id") == rid and a.get("photo_path"):
                    src = cloud.public_url(a["photo_path"])
                    break
        frame_kw = {"width": size, "height": size, "border_radius": 16,
                    "border": border_all(2, ft.Colors.with_opacity(0.9, "#FFFFFF"))}
        if src is not None:
            return ft.Container(**frame_kw, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                                content=ft.Image(src=src, width=size, height=size, fit=ft.BoxFit.COVER))
        return ft.Container(**frame_kw, alignment=ft.Alignment.CENTER,
                            gradient=ft.LinearGradient(begin=ft.Alignment(-1, -1), end=ft.Alignment(1, 1),
                                                       colors=["#F3E9DC", "#E2D3BF"]),
                            content=serif((name or "席")[:1], size * 0.38, OLIVE_DARK, height=1.0))

    def photo_box(src, width: float, ratio: float = 1.25, radius: int = 16, initial: str = "", small=False):
        """4:5 照片；沒有照片時用暖色底＋店名第一個字。"""
        h = width * ratio
        if src is not None:
            return ft.Container(
                width=width, height=h, border_radius=radius, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=ft.Image(src=src, width=width, height=h, fit=ft.BoxFit.COVER),
            )
        return ft.Container(
            width=width, height=h, border_radius=radius, bgcolor=EMPTY, alignment=ft.Alignment.CENTER,
            content=serif(initial[:1] or "席", 26 if small else 64, MUTED, height=1.0),
        )

    # ---------- 想去／同感（就地更新，不會讓畫面跳回最上面） ----------
    def wish_item_from_restaurant(r: Restaurant) -> dict:
        return {"key": r.id, "name": r.name, "area": r.area, "lat": r.lat, "lng": r.lng}

    def wish_item_from_post(p: Post) -> dict:
        r = by_id.get(p.restaurant_id)
        if r:
            return wish_item_from_restaurant(r)
        return {"key": "name:" + p.place, "name": p.place, "area": p.area}

    def wish_button(item: dict, mine: bool = False, big: bool = False):
        icon = ft.Icon(ft.Icons.BOOKMARK_BORDER, size=19)
        label = sans("", 13, spacing=0.5)
        box = ft.Container(content=ft.Row([icon, label], spacing=6, tight=True,
                                          alignment=ft.MainAxisAlignment.CENTER))
        idle, done = ("想再去", "已想去") if mine else ("想去", "已想去")
        if big:
            idle = "加入想去清單"

        def paint():
            on = store.wished(item["key"])
            set_icon(icon, ft.Icons.BOOKMARK if on else ft.Icons.BOOKMARK_BORDER)
            if big:
                icon.color = CARD if on else ACCENT
                label.color = CARD if on else ACCENT
                box.bgcolor = ACCENT if on else None
                box.border = hairline(ACCENT)
            else:
                icon.color = label.color = ACCENT if on else INK
            label.value = (done + "清單" if big else done) if on else idle

        async def toggle(e):
            on = await store.toggle_wish(item)
            paint()
            box.update()
            if on:
                toast(f"「{item['name']}」放進想去清單了")

        paint()
        box.on_click = toggle
        box.height = 48 if big else 44
        box.padding = pad(20, 0, 20, 0) if big else pad(8, 0, 8, 0)
        box.border_radius = 24
        return box

    def cheer_button(p: Post, quiet: ft.Text | None = None):
        icon = ft.Icon(ft.Icons.WINE_BAR_OUTLINED, size=20)
        label = sans("同感", 13, spacing=0.5)
        box = ft.Container(height=44, padding=pad(0, 0, 8, 0),
                           content=ft.Row([icon, label], spacing=6, tight=True))

        def paint():
            on = cheered(p)
            set_icon(icon, ft.Icons.WINE_BAR if on else ft.Icons.WINE_BAR_OUTLINED)
            icon.color = label.color = ACCENT if on else INK
            if quiet is not None:
                quiet.value = cheer_line(p, short=True)

        async def toggle(e):
            if p.cloud_id is not None:
                ok, on = await cloud_call(cloud.toggle_cheer(p.cloud_id))
                if not ok:
                    return
                p.cheered = on
            else:
                await store.toggle_cheer(p.id)
            paint()
            box.update()
            if quiet is not None:
                quiet.update()

        paint()
        box.on_click = toggle
        return box

    def cheered(p: Post) -> bool:
        return p.cheered if p.cloud_id is not None else p.id in store.cheers

    def cheer_line(p: Post, short: bool = False) -> str:
        names = (["你"] if cheered(p) else []) + p.cheered_by
        if not names:
            return ""
        if short:
            return "你與" + p.author + "同感" if cheered(p) else ""
        return "、".join(names[:-1]) + (" 與 " if len(names) > 1 else "") + names[-1] + " 對這一餐有同感"

    # ---------- 檔案：選照片、存圖片 ----------
    async def pick_photo() -> bytes | None:
        try:
            files = await ft.FilePicker().pick_files(
                dialog_title="選一張食物照片", file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["jpg", "jpeg", "png", "webp"], with_data=True,
            )
        except Exception:
            toast("沒辦法開啟相簿")
            return None
        if not files:
            return None
        f = files[0]
        if getattr(f, "bytes", None):
            return f.bytes
        if getattr(f, "path", None):
            return Path(f.path).read_bytes()
        return None

    async def save_png(data: bytes, file_name: str):
        try:
            path = await ft.FilePicker().save_file(
                dialog_title="存成圖片", file_name=file_name, src_bytes=data,
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["png"],
            )
        except Exception:
            toast("存檔失敗，請再試一次")
            return
        if path and not page.web and not page.platform.is_mobile():
            Path(path).write_bytes(data)            # 桌面版只回傳路徑，要自己寫檔
        if path or page.web:
            toast("存好了。打開 IG 限動選這張圖就能分享")

    # ---------- 自己的紀錄 → Post ----------
    def post_from_entry(e: journal.MealEntry) -> Post:
        return Post(
            id=e.id, author="你", initial="我", at=e.when, place=e.name, area=e.area, tags=list(e.tags),
            note=e.note, photo=store.photos.get(e.id), price=e.price, party=e.party,
            walk=e.walk_minutes, restaurant_id=e.restaurant_id, entry=e,
        )

    # ==================== 動態 ====================
    def feed_card(p: Post, cw: int):
        inner = cw - PAD * 2 - 30
        meta = " · ".join(x for x in [p.dept, p.area, relative_time(p.at, taipei_now())] if x)
        corner = caps("範例") if p.demo else ft.Container()
        if p.cloud_id is not None and not p.own:
            corner = ft.IconButton(icon=ft.Icons.MORE_HORIZ, icon_color=MUTED, icon_size=18, tooltip="檢舉或封鎖",
                                   on_click=lambda e: report_dialog("post", p.cloud_id, p.actor_id, p.author))
        author_row = ft.Row(
            spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                avatar(p.initial, 28, "#E8E1D6" if (p.mine or p.own) else None),
                ft.Column([sans(p.author, 13, weight=ft.FontWeight.W_500), sans(meta, 11, MUTED, spacing=0.4)],
                          spacing=1, expand=True),
                corner,
            ],
        )
        right = f"NT$ {p.price}" if p.price else (f"走 {p.walk} 分" if p.walk else "")
        text_block = [
            ft.Row([ft.Container(serif(p.place, 21, max_lines=1), expand=True), caps(right)],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ]
        if p.tags:
            text_block.append(ft.Row([sans("#" + t, 12, MUTED, spacing=1) for t in p.tags[:2]], spacing=12))
        if p.note:
            text_block.append(sans(p.note.replace("\n", " "), 14, BODY, max_lines=2, height=1.8))
        body = ft.Container(
            on_click=lambda e: open_overlay("post", post=p),
            content=ft.Column(spacing=12, controls=[
                photo_box(p.photo, inner, 1.25 if p.photo is not None else 0.62, 16, p.place),
                ft.Container(padding=pad(4, 2, 4, 0), content=ft.Column(text_block, spacing=8)),
            ]),
        )
        quiet = sans(cheer_line(p, short=True), 11, MUTED)
        actions = ([] if (p.mine or p.own) else [cheer_button(p, quiet)]) + [wish_button(wish_item_from_post(p), p.mine or p.own)]
        if p.mine and p.photo is None:
            async def add_photo(e):
                await attach_photo(p.entry)
            actions.append(ft.Container(height=44, padding=pad(8, 0, 8, 0), on_click=add_photo,
                                        content=ft.Row([ft.Icon(ft.Icons.ADD_A_PHOTO_OUTLINED, size=18, color=INK),
                                                        sans("補照片", 13, spacing=0.5)], spacing=6, tight=True)))
        action_row = ft.Container(
            margin=pad(4, 0, 4, 0), border=top_line(),
            content=ft.Row([*actions, ft.Container(expand=True), quiet], spacing=4,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        return ft.Container(
            **GLASS_KW, border_radius=22, padding=pad(14, 14, 14, 4),
            content=ft.Column([author_row, body, action_row], spacing=14),
        )

    def feed_screen(cw: int):
        now = taipei_now()
        campus = state["feed_scope"] == "campus"

        def toggle_scope(e):
            state["feed_scope"] = "mine" if campus else "campus"
            render()

        async def refresh(e):
            state["feed"] = None
            render(keep_scroll=True)
            await load_feed()
            render(keep_scroll=True)

        logo = ft.Row(
            spacing=10, vertical_alignment=ft.CrossAxisAlignment.END,
            controls=[ft.Text("Table", size=34, italic=True, weight=ft.FontWeight.W_600, color=INK,
                              font_family=logo_family, style=ft.TextStyle(height=1.0)),
                      ft.Container(padding=pad(0, 0, 0, 4), content=sans("席間", 14, MUTED, spacing=4.5))],
        )
        tools = [ft.Container(height=44, padding=pad(10, 0, 6, 0), on_click=toggle_scope, tooltip="切換校園／我的",
                              content=ft.Row([ft.Icon(ft.Icons.TUNE, size=20, color=INK),
                                              caps("校園" if campus else "我的", 12)], spacing=6, tight=True))]
        if campus and ready():
            tools.append(ft.IconButton(icon=ft.Icons.REFRESH, icon_color=INK, icon_size=21, tooltip="重新整理",
                                       on_click=refresh))
        tools.append(ft.IconButton(icon=ft.Icons.MAP_OUTLINED, icon_color=INK, icon_size=21, tooltip="地圖模式",
                                   on_click=tab_handler("explore")))
        top = ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                     controls=[logo, ft.Row(spacing=0, controls=tools)])
        date_row = ft.Container(
            border=bottom_line(), padding=pad(0, 0, 0, 14),
            content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                caps(f"{WEEKDAYS_EN[now.weekday()]} · {now.day} {MONTHS_EN[now.month - 1]}"),
                serif(f"{time_of_day(now.hour)}，台大吃了什麼" if campus else "我的餐桌", 13, MUTED, height=1.2),
            ]),
        )

        cards = []
        if not campus:
            posts = [post_from_entry(e) for e in journal.sort_newest_first(store.entries)]
            cards = [feed_card(p, cw) for p in posts]
            if not store.entries:
                cards.insert(0, ft.Container(
                    **GLASS_KW, border_radius=22, padding=22,
                    on_click=lambda e: open_overlay("record"),
                    content=ft.Column(spacing=8, controls=[
                        caps("YOUR FIRST TABLE"),
                        serif("記下你的第一餐", 22),
                        sans("拍一張照、寫一句話就好。月底會幫你做成一張「飯 Dump」。", 14, BODY, height=1.7),
                        ft.Container(height=4),
                        ft.Row([pill("＋ 記錄這一餐", lambda e: open_overlay("record"))]),
                    ]),
                ))
        elif not ready():
            cards.append(login_card("看看台大今天吃什麼", "加入後可以看到大家分享的食記、誰幫哪家店助力、"
                                                          "誰正在找人吃飯。下面先放幾則範例。"))
            cards += [feed_card(p, cw) for p in demo_posts(now)]
        elif state["feed"] is None:
            cards.append(sans("載入中…", 13, MUTED))
        elif not state["feed"]:
            cards.append(ft.Container(
                **GLASS_KW, border_radius=22, padding=22,
                content=ft.Column(spacing=8, controls=[
                    serif("校園動態還很安靜", 20),
                    sans("當第一個分享的人吧：按下方的＋記一餐，或到探索幫愛店助力。", 14, BODY, height=1.7)]),
            ))
        else:
            rows = []                                   # 助力、稱號這類短動態合成一個區塊，不佔太多版面
            for a in state["feed"]:
                item = cloud_feed_item(a, cw)
                if a["verb"] == "post":
                    if rows:
                        cards.append(ft.Column(rows, spacing=0))
                        rows = []
                    cards.append(item)
                else:
                    rows.append(item)
            if rows:
                cards.append(ft.Column(rows, spacing=0))
        cards.append(ft.Container(padding=pad(0, 0, 0, 8), alignment=ft.Alignment.CENTER,
                                  content=ft.Text("— 今天就到這裡 —", italic=True, size=15, color=MUTED,
                                                  font_family=logo_family)))
        return [
            ft.Container(padding=pad(PAD, 20, PAD, 0), content=ft.Column([top, date_row], spacing=16)),
            ft.Container(padding=pad(PAD, 24, PAD, 0), content=ft.Column(cards, spacing=GAP)),
        ]

    # ==================== 食記詳情 ====================
    async def attach_photo(entry: journal.MealEntry):
        data = await pick_photo()
        if not data:
            return
        try:
            await store.set_photo(entry, data)
        except Exception:
            toast("這張照片讀不進來，換一張試試")
            return
        toast("照片加好了")
        if state["overlay"] and state["overlay"].get("post") and state["overlay"]["post"].entry is entry:
            state["overlay"]["post"] = post_from_entry(entry)
            state["overlay"]["photo_index"] = 0
        render(keep_scroll=True)

    def entry_menu(p: Post):
        e = p.entry

        async def change_photo(ev):
            page.pop_dialog()
            await attach_photo(e)

        def ask_delete(ev):
            page.pop_dialog()

            async def do_delete(ev2):
                page.pop_dialog()
                await store.delete(e)
                state["overlay"] = None
                toast("已刪除這篇食記")
                render()

            page.show_dialog(ft.AlertDialog(
                bgcolor=BG, title=serif("要刪除這篇食記嗎？", 20),
                content=sans(f"{e.name} · {full_date(e.when)}\n刪除後就找不回來了。", 14, MUTED, height=1.7),
                actions=[ft.TextButton(content="刪除", on_click=do_delete),
                         ft.TextButton(content="取消", on_click=lambda ev2: page.pop_dialog())],
            ))

        page.show_dialog(ft.AlertDialog(
            bgcolor=BG, title=serif(e.name, 20),
            actions=[ft.TextButton(content="換照片" if p.photo is not None else "加照片", on_click=change_photo),
                     ft.TextButton(content="刪除", on_click=ask_delete),
                     ft.TextButton(content="關閉", on_click=lambda ev: page.pop_dialog())],
        ))

    def round_glass_button(icon, on_click, tooltip: str):
        return ft.Container(
            width=44, height=44, border_radius=22, bgcolor=ft.Colors.with_opacity(0.8, BG),
            blur=ft.Blur(16, 16), alignment=ft.Alignment.CENTER, on_click=on_click, tooltip=tooltip,
            content=ft.Icon(icon, size=20, color=INK),
        )

    def detail_screen(cw: int):
        ov = state["overlay"]
        p: Post = ov["post"]
        photos = ([p.photo] if p.photo is not None else []) + list(p.extra_photos)
        idx = ov.get("photo_index", 0) % max(1, len(photos))

        def next_photo(e):
            ov["photo_index"] = idx + 1
            render(keep_scroll=True)

        hero_h = cw * 1.25 if photos else cw * 0.62
        hero = [photo_box(photos[idx] if photos else None, cw, hero_h / cw, 0, p.place)]
        if len(photos) > 1:
            hero.append(ft.Container(right=16, bottom=40, padding=pad(10, 4, 10, 4), border_radius=12,
                                     bgcolor=ft.Colors.with_opacity(0.46, INK),
                                     content=sans(f"{idx + 1} / {len(photos)}", 11, BG, spacing=0.9)))
        hero += [
            ft.Container(left=0, right=0, bottom=0, height=24, bgcolor=BG,
                         border_radius=ft.BorderRadius(top_left=24, top_right=24, bottom_left=0, bottom_right=0)),
            ft.Container(left=16, top=16, content=round_glass_button(ft.Icons.ARROW_BACK_IOS_NEW, lambda e: close_overlay(), "返回")),
        ]
        if p.mine:
            hero.append(ft.Container(right=16, top=16, content=round_glass_button(
                ft.Icons.MORE_HORIZ, lambda e: entry_menu(p), "更多")))
        hero_stack = ft.Container(height=hero_h, on_click=next_photo if len(photos) > 1 else None,
                                  content=ft.Stack(hero))

        r = by_id.get(p.restaurant_id)
        kicker = " · ".join(x for x in [p.area, "台大附近" if r else ("範例" if p.demo else "")] if x)
        blocks = [
            ft.Row(spacing=10, controls=[
                avatar(p.initial, 32, "#E8E1D6" if p.mine else None),
                ft.Column(spacing=1, controls=[
                    sans(f"{'我' if p.mine else p.author} 的食記", 13, weight=ft.FontWeight.W_500),
                    sans(full_date(p.at), 11, MUTED, spacing=0.4)]),
            ]),
            ft.Column(spacing=10, controls=[
                caps(kicker) if kicker else ft.Container(),
                serif(p.place, 32, weight=ft.FontWeight.W_600, height=1.3),
                ft.Row([sans("#" + t, 12, MUTED, spacing=1) for t in p.tags], spacing=14, wrap=True)
                if p.tags else ft.Container(),
            ]),
        ]

        def fact(label, value, first=False):
            return ft.Container(
                expand=True, padding=pad(0 if first else 12, 14, 0, 14),
                border=None if first else ft.Border(left=ft.BorderSide(1, LINE)),
                content=ft.Column([caps(label, 10), sans(value, 14)], spacing=4),
            )

        party = {1: "一個人", 2: "兩個人"}.get(p.party, f"{p.party} 人" if p.party else "—")
        third = ("WALK", f"走 {p.walk} 分") if p.walk else ("WHEN", time_of_day(p.at.hour))
        blocks.append(ft.Container(
            border=ft.Border(top=ft.BorderSide(1, LINE), bottom=ft.BorderSide(1, LINE)),
            content=ft.Row([fact("PRICE", f"人均 {p.price}" if p.price else "—", True),
                            fact("PARTY", party), fact(*third)], spacing=0),
        ))
        if p.note:
            blocks.append(ft.Column([sans(para, 15, "#2E2C28", height=1.95) for para in p.note.split("\n") if para.strip()],
                                    spacing=16))
        elif p.mine:
            blocks.append(sans("還沒寫短評。按右上角「⋯」可以補照片。", 14, MUTED, height=1.8))
        if p.quote:
            blocks.append(ft.Container(padding=pad(8, 12, 8, 12), alignment=ft.Alignment.CENTER, content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6, controls=[
                    ft.Text("“", size=40, color=ACCENT, italic=True, font_family=logo_family, style=ft.TextStyle(height=0.8)),
                    serif(p.quote, 19, center=True, height=1.75)])))
        if p.dishes:
            rows = [caps("THIS MEAL · 這一餐點了")]
            for dish, note in p.dishes:
                rows.append(ft.Container(
                    border=bottom_line(), padding=pad(0, 10, 0, 10),
                    content=ft.Row([serif(dish, 16, height=1.3),
                                    ft.Container(expand=True, height=1, margin=pad(6, 6, 6, 0),
                                                 border=ft.Border(bottom=ft.BorderSide(1, "#D9D3C9"))),
                                    sans(note, 12, MUTED)],
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER)))
            blocks.append(ft.Column(rows, spacing=4))
        if r:
            now = taipei_now()
            left = minutes_until_close(r, now)
            status = f"營業中，還有 {left} 分打烊" if left is not None else "現在休息中"
            blocks.append(place_card(r, f"{r.area} · {hours_today(r, now)}\n{status}"))
        if p.cheered_by or p.id in store.cheers:
            blocks.append(ft.Row(spacing=12, controls=[
                ft.Row([avatar(n[:1], 26) for n in p.cheered_by[:3]], spacing=2),
                sans(cheer_line(p), 12, MUTED)]))
        if p.demo:
            blocks.append(sans("這是範例食記，人和店都是虛構的。好友功能需要帳號系統，下一版加入。", 12, MUTED, height=1.7))

        article = ft.Container(padding=pad(PAD, 2, PAD, 0), content=ft.Column(blocks, spacing=22))
        return [hero_stack, article]

    def place_card(r: Restaurant, info: str):
        return ft.Container(
            **GLASS_KW, border_radius=20, padding=18,
            content=ft.Column(spacing=14, controls=[
                ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                    ft.Column([serif(r.name, 17), sans(info, 12, MUTED, height=1.6)], spacing=4, expand=True),
                    ft.Icon(ft.Icons.PLACE_OUTLINED, size=22, color=MUTED)]),
                ft.Row([link_button("在地圖上看", map_url(r), filled=False, expand=True),
                        link_button("導航過去", walk_url(r), expand=True,
                                    icon=ft.Icons.DIRECTIONS_WALK)], spacing=10),
            ]),
        )

    def detail_bar(p: Post):
        controls = []
        if p.mine:
            async def add_photo(e):
                await attach_photo(p.entry)
            controls.append(ft.Container(height=48, padding=pad(12, 0, 12, 0), on_click=add_photo, content=ft.Row(
                [ft.Icon(ft.Icons.ADD_A_PHOTO_OUTLINED, size=19, color=INK),
                 sans("換照片" if p.photo is not None else "加照片", 13, spacing=0.5)], spacing=6, tight=True)))
        else:
            controls.append(ft.Container(padding=pad(12, 0, 0, 0), content=cheer_button(p)))
        controls += [ft.Container(expand=True), wish_button(wish_item_from_post(p), p.mine, big=True)]
        return ft.Row(controls, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # ==================== 記錄這一餐 ====================
    def record_screen(cw: int):
        ov = state["overlay"]
        draft = ov.setdefault("draft", {"name": "", "restaurant": None, "photo": None, "tags": set(),
                                        "note": "", "price": "", "party": 1, "walk": 0, "surprise": False})
        draft.setdefault("share", ready())
        if ov.get("restaurant") and not draft["name"]:
            r0 = ov["restaurant"]
            draft.update(name=r0.name, restaurant=r0, walk=ov.get("walk", 0), surprise=ov.get("surprise", False))

        suggest_row = ft.Row(wrap=True, spacing=8, run_spacing=8)

        def pick_suggestion(r: Restaurant):
            def handler(e):
                draft["name"], draft["restaurant"] = r.name, r
                name_field.value = r.name
                suggest_row.controls = []
                name_field.update()
                suggest_row.update()
            return handler

        def refresh_suggestions(update=True):
            q = (draft["name"] or "").strip()
            hits = [r for r in restaurants if q and q in r.name and r.name != q][:6]
            suggest_row.controls = [chip(r.name, False, pick_suggestion(r)) for r in hits]
            if update:
                suggest_row.update()

        def on_name(e):
            draft["name"] = name_field.value or ""
            r = next((x for x in restaurants if x.name == draft["name"].strip()), None)
            draft["restaurant"] = r
            refresh_suggestions()

        name_field = ft.TextField(
            value=draft["name"], hint_text="店名，例如：巷尾麵舖", border=ft.InputBorder.UNDERLINE,
            border_color=LINE, focused_border_color=INK, cursor_color=ACCENT, on_change=on_name,
            text_style=ft.TextStyle(size=22, font_family=serif_family, color=INK),
            hint_style=ft.TextStyle(size=20, font_family=serif_family, color="#B5B0A7"),
        )
        refresh_suggestions(update=False)

        photo_w = cw - PAD * 2
        photo_slot = ft.Container()

        def paint_photo():
            if draft["photo"]:
                photo_slot.content = photo_box(draft["photo"], photo_w, 1.25, 16)
            else:
                photo_slot.content = ft.Container(
                    width=photo_w, height=180, border_radius=16, bgcolor=EMPTY, alignment=ft.Alignment.CENTER,
                    content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8, tight=True,
                                      controls=[ft.Icon(ft.Icons.ADD_A_PHOTO_OUTLINED, size=26, color=MUTED),
                                                sans("加一張照片（可略過）", 13, MUTED)]),
                )

        async def choose_photo(e):
            data = await pick_photo()
            if data:
                draft["photo"] = make_thumbnail(data) if HAS_PILLOW else data
                paint_photo()
                photo_slot.update()

        paint_photo()
        photo_slot.on_click = choose_photo

        tag_row = ft.Row(wrap=True, spacing=8, run_spacing=8)

        def paint_tags():
            tag_row.controls = [chip("#" + t, t in draft["tags"], toggle_tag(t)) for t in PRESET_TAGS]

        def toggle_tag(t):
            def handler(e):
                draft["tags"] ^= {t}
                paint_tags()
                tag_row.update()
            return handler

        paint_tags()

        def on_note(e):
            draft["note"] = note_field.value or ""

        note_field = ft.TextField(
            value=draft["note"], hint_text="一兩句就好：今天的主角是什麼？", multiline=True, min_lines=3, max_lines=6,
            border_color=LINE, focused_border_color=INK, cursor_color=ACCENT, bgcolor=CARD, border_radius=14,
            text_style=ft.TextStyle(size=15, height=1.7, color=INK), on_change=on_note,
        )

        def on_price(e):
            draft["price"] = price_field.value or ""

        price_field = ft.TextField(
            value=draft["price"], hint_text="人均（元）", keyboard_type=ft.KeyboardType.NUMBER, width=130,
            border=ft.InputBorder.UNDERLINE, border_color=LINE, focused_border_color=INK, on_change=on_price,
            text_style=ft.TextStyle(size=16, color=INK),
        )
        party_row = ft.Row(spacing=8, wrap=True)

        def paint_party():
            party_row.controls = [chip(label, draft["party"] == n, set_party(n))
                                  for n, label in [(1, "1 人"), (2, "2 人"), (4, "3–4 人"), (6, "5+")]]

        def set_party(n):
            def handler(e):
                draft["party"] = n
                paint_party()
                party_row.update()
            return handler

        paint_party()

        async def save(e):
            name = (draft["name"] or "").strip()
            if not name:
                toast("先寫下店名")
                return
            r = draft["restaurant"] or next((x for x in restaurants if x.name == name), None)
            try:
                price = int("".join(ch for ch in draft["price"] if ch.isdigit()) or 0)
            except ValueError:
                price = 0
            entry = journal.new_entry(
                taipei_now(), name, area=r.area if r else "", restaurant_id=r.id if r else "",
                walk_minutes=draft["walk"] or (walking_minutes(origin_building(), r) if r else 0),
                surprise=draft["surprise"], note=(draft["note"] or "").strip(),
                tags=sorted(draft["tags"], key=PRESET_TAGS.index) if draft["tags"] else [],
                price=price, party=draft["party"],
            )
            await store.add(entry)
            if draft["photo"]:
                try:
                    await store.set_photo(entry, draft["photo"])
                except Exception:
                    toast("照片存不進去，紀錄已保存")
            shared = False
            if draft["share"] and ready():
                photo_path = ""
                if entry.id in store.photos and HAS_PILLOW:      # 縮圖已是 JPEG，約 50 KB
                    ok, path = await cloud_call(cloud.upload_photo(store.photos[entry.id]))
                    photo_path = path if ok else ""
                ok, _ = await cloud_call(cloud.share_post(entry.restaurant_id, entry.name, entry.area, entry.note,
                                                          entry.tags, photo_path))
                shared = ok
            state["overlay"] = None
            state["tab"] = "feed"
            state["feed_scope"] = "campus" if shared else "mine"
            state["feed"] = None
            toast("記下了，也分享到校園動態" if shared else "記下了。這一餐會出現在月底的飯 Dump")
            render()
            if shared:
                await load_feed()
                render(keep_scroll=True)

        share_icon = ft.Icon(ft.Icons.CHECK_BOX_OUTLINE_BLANK, size=20)
        share_text = sans("", 14, weight=ft.FontWeight.W_500)
        share_toggle = ft.Container(bgcolor=CARD, border_radius=16, padding=16,
                                    content=ft.Row([share_icon, ft.Column([
                                        share_text, sans("照片、店名和短評會出現在台大的校園動態。", 12, MUTED, height=1.6)],
                                        spacing=4, expand=True)], vertical_alignment=ft.CrossAxisAlignment.START))

        def paint_share():
            on = draft["share"]
            set_icon(share_icon, ft.Icons.CHECK_BOX if on else ft.Icons.CHECK_BOX_OUTLINE_BLANK)
            share_icon.color = ACCENT if on else MUTED
            share_text.value = "分享到校園動態" if ready() else "取個暱稱加入後，可以分享到校園動態"
            share_toggle.border = hairline(ACCENT if on else LINE)

        def toggle_share(e):
            if not ready():
                open_overlay("login")
                return
            draft["share"] = not draft["share"]
            paint_share()
            share_toggle.update()

        paint_share()
        share_toggle.on_click = toggle_share
        if not cloud.enabled:
            share_toggle = ft.Container()

        head = ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.IconButton(icon=ft.Icons.CLOSE, icon_color=INK, tooltip="取消", on_click=lambda e: close_overlay()),
            ft.Container(expand=True, alignment=ft.Alignment.CENTER, content=serif("記錄這一餐", 18, height=1.2)),
            ft.TextButton(content=sans("儲存", 14, ACCENT, ft.FontWeight.W_500), on_click=save),
        ])
        now = taipei_now()
        form = ft.Column(spacing=22, controls=[
            caps(f"{WEEKDAYS_EN[now.weekday()]} · {now.day} {MONTHS_EN[now.month - 1]} · {time_of_day(now.hour)}"),
            ft.Column([section_label("WHERE", "在哪裡吃"), name_field, suggest_row], spacing=8),
            photo_slot,
            ft.Column([section_label("TAGS", "標籤，最多顯示兩個"), tag_row], spacing=10),
            ft.Column([section_label("NOTE", "短評"), note_field], spacing=10),
            ft.Column([section_label("DETAILS", "人均與人數"),
                       ft.Row([price_field, ft.Container(width=8), party_row], wrap=True,
                              vertical_alignment=ft.CrossAxisAlignment.CENTER)], spacing=10),
            share_toggle,
            ft.Row([pill("記下這一餐", save, expand=True)]),
            sans("沒有勾選分享時，紀錄和照片只存在你的手機或瀏覽器。", 12, MUTED, center=True),
        ])
        return [ft.Container(padding=pad(8, 8, 8, 0), content=head),
                ft.Container(padding=pad(PAD, 8, PAD, 0), content=form)]

    # ==================== 探索 ====================
    def origin_building():
        return next((b for b in buildings if b.id == state["origin"]), buildings[0])

    def restaurant_status(r: Restaurant, now: datetime) -> tuple[str, bool]:
        left = minutes_until_close(r, now)
        if left is None:
            return "休息中", False
        if left < 45:
            return f"{left} 分後打烊", True
        return "營業中", True

    def explore_row(r: Restaurant, now: datetime):
        walk = walking_minutes(origin_building(), r)
        status, is_open = restaurant_status(r, now)
        price = f" · {price_text(r)}" if r.price > 0 else ""
        return ft.Container(
            **GLASS_KW, border_radius=26, padding=pad(12, 12, 6, 12),
            on_click=lambda e: open_overlay("place", restaurant=r),
            content=ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=14, controls=[
                thumb(r.id, r.name, 56),
                ft.Column(spacing=4, expand=True, controls=[
                    serif(r.name, 18, max_lines=1, height=1.3),
                    sans(f"{r.area} · 走 {walk} 分 · {status}{price}", 12, MUTED if is_open else "#9C978E",
                         spacing=0.4, max_lines=1)]),
                wish_button(wish_item_from_restaurant(r)),
            ]),
        )

    def explore_screen(cw: int):
        now = taipei_now()
        open_now = [r for r in restaurants if minutes_until_close(r, now) is not None]
        counts: dict[str, int] = {}
        for r in restaurants:
            counts[r.area] = counts.get(r.area, 0) + 1
        areas = ["全部"] + [a for a, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:5]]

        def set_origin(bid):
            def handler(e):
                state["origin"] = bid
                render(keep_scroll=True)
            return handler

        def set_area(a):
            def handler(e):
                state["area"], state["explore_limit"] = a, 20
                render(keep_scroll=True)
            return handler

        def more(e):
            state["explore_limit"] += 20
            render(keep_scroll=True)

        b = origin_building()
        pool = [r for r in open_now if state["area"] in ("全部", r.area)]
        pool.sort(key=lambda r: walking_minutes(b, r))
        shown = pool[: state["explore_limit"]]

        def start_quiz(e):
            state["step"] = 2
            open_overlay("quiz")

        hero = ft.Container(
            **GLASS_KW, border_radius=30, padding=24, blur=ft.Blur(18, 18),
            content=ft.Column(spacing=8, controls=[
                caps("QUICK PICK · 30 秒決定"),
                serif("下一餐，交給我們挑。", 26, weight=ft.FontWeight.W_600),
                sans(f"從「{b.name}」出發。回答 4 個小問題，只推薦現在有開、走得到的店。", 14, BODY, height=1.7),
                ft.Container(height=6),
                ft.Row([ft.Container(expand=3, content=pill("開始", start_quiz, expand=True,
                                                             trailing=ft.Icons.CHEVRON_RIGHT)),
                        ft.Container(expand=2, content=pill("驚喜一下", lambda e: open_surprise(default_query()),
                                                             filled=False, expand=True, icon=ft.Icons.CASINO_OUTLINED))],
                       spacing=12),
            ]),
        )
        controls = [
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.END,
                   controls=[ft.Column([caps("EXPLORE · NTU"),
                                        serif("探索", 38, weight=ft.FontWeight.W_600, height=1.2),
                                        ft.Container(width=64, height=1.5, bgcolor=OLIVE)], spacing=6),
                             ft.Container(padding=pad(0, 0, 0, 22), content=caps(f"現在營業 {len(open_now)} 家", 12))]),
            ft.Column(spacing=12, controls=[
                section_label("FROM", "你在哪"),
                ft.Row(scroll=ft.ScrollMode.AUTO, spacing=10,
                       controls=[chip(x.name, x.id == state["origin"], set_origin(x.id),
                                      icon=ft.Icons.MENU_BOOK_OUTLINED if x.id == "lib" else ft.Icons.PLACE_OUTLINED)
                                 for x in buildings]),
            ]),
            hero,
            ft.Column(leaderboard_section(), spacing=12),
            ft.Column(spacing=12, controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    section_label("OPEN NOW", "附近現在有開"), caps(f"{len(pool)} 家")]),
                ft.Row(scroll=ft.ScrollMode.AUTO, spacing=10,
                       controls=[chip(a, a == state["area"], set_area(a)) for a in areas]),
            ]),
            *([explore_row(r, now) for r in shown] or [
                sans("這一區現在都休息了。換個區域，或晚點再來看看。", 14, MUTED, height=1.7)]),
        ]
        if len(pool) > len(shown):
            controls.append(ft.Row([pill(f"再看 {min(20, len(pool) - len(shown))} 家", more, filled=False, expand=True)]))
        controls.append(sans("餐廳資料 © OpenStreetMap contributors · 營業時間僅供參考", 11, MUTED, center=True))
        return [ft.Container(padding=pad(PAD, 28, PAD, 0), content=ft.Column(controls, spacing=22))]

    # ---------- 店家頁（從探索、想去點進來） ----------
    def place_screen(cw: int):
        r: Restaurant = state["overlay"]["restaurant"]
        now = taipei_now()
        walk = walking_minutes(origin_building(), r)
        status, _ = restaurant_status(r, now)
        mine = [e for e in journal.sort_newest_first(store.entries) if e.restaurant_id == r.id]
        facts = [("走路", f"{walk} 分"), ("人均", price_text(r, "")),
                 ("人潮", crowd_hint(r, now).replace("尖峰時段，", "").replace("目前", ""))]

        def eat_here(e):
            open_overlay("record", restaurant=r, walk=walk)

        blocks = [
            ft.Row([ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW, icon_color=INK, icon_size=20, tooltip="返回",
                                  on_click=lambda e: close_overlay())]),
            ft.Container(padding=pad(PAD - 8, 0, PAD - 8, 0), content=ft.Column(spacing=22, controls=[
                ft.Column(spacing=10, controls=[
                    caps(f"{r.area} · {status}"),
                    serif(r.name, 32, weight=ft.FontWeight.W_600, height=1.3),
                    sans(hours_today(r, now), 13, MUTED),
                ]),
                ft.Container(border=ft.Border(top=ft.BorderSide(1, LINE), bottom=ft.BorderSide(1, LINE)),
                             content=ft.Row(spacing=0, controls=[
                                 ft.Container(expand=True, padding=pad(0 if i == 0 else 12, 14, 0, 14),
                                              border=None if i == 0 else ft.Border(left=ft.BorderSide(1, LINE)),
                                              content=ft.Column([caps(k, 10), sans(v, 14, max_lines=1)], spacing=4))
                                 for i, (k, v) in enumerate(facts)])),
                ft.Row([pill("就吃這家，記下來", eat_here, expand=True),
                        pill("揪人一起吃", lambda e: open_overlay("newmeet", radar=False, restaurant=r),
                             filled=False, accent=True, icon=ft.Icons.GROUPS_OUTLINED)], spacing=10),
                place_card(r, f"從{origin_building().name}走過去約 {walk} 分鐘"),
                ft.Column(spacing=10, controls=[
                    section_label("YOUR NOTES", "你在這裡的紀錄"),
                    *([ft.Container(border=bottom_line(), padding=pad(0, 8, 0, 8),
                                    on_click=lambda ev, e=e: open_overlay("post", post=post_from_entry(e)),
                                    content=ft.Row([serif(full_date(e.when), 15, height=1.3), ft.Container(expand=True),
                                                    sans(e.note[:14] + ("…" if len(e.note) > 14 else ""), 12, MUTED)]))
                       for e in mine[:5]] or [sans("還沒來過。吃完記一筆，下次就找得到。", 13, MUTED)]),
                ]),
                sans(data_note(r), 11, MUTED, height=1.6),
            ])),
        ]
        return blocks

    def place_bar(r: Restaurant):
        return ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Container(padding=pad(6, 0, 0, 0), content=link_button(
                "導航", walk_url(r), filled=False, icon=ft.Icons.DIRECTIONS_WALK, height=44)),
            ft.Container(expand=True),
            boost_button(r.id, r.name, r.area),
            wish_button(wish_item_from_restaurant(r)),
        ])

    # ---------- 30 秒決定（問答） ----------
    def default_query() -> Query:
        return Query(building_id=state["origin"], minutes_available=60, budget=9999, party_size=1,
                     recent_ids=journal.recent_restaurant_ids(store.entries, taipei_now(), days=3))

    def build_query() -> Query:
        return Query(
            building_id=state["origin"], minutes_available=state["minutes"] or 60,
            budget=state["budget"] or 9999, party_size=state["party"] or 1,
            required_tags=set(state["tags"]), avoid_allergens=set(state["allergens"]),
            recent_ids=journal.recent_restaurant_ids(store.entries, taipei_now(), days=3),  # 最近 3 天吃過的排後面
        )

    def quiz_go(step: int):
        if step < 1:
            close_overlay()
            return
        state["step"] = step
        render()

    def option_row(label: str, hint: str, selected: bool, on_click):
        return ft.Container(
            border=bottom_line(), padding=pad(0, 18, 0, 18), on_click=on_click,
            content=ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                serif(label, 20, ACCENT if selected else INK, height=1.2),
                ft.Container(expand=True),
                sans(hint, 12, MUTED),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=20, color=ACCENT if selected else "#B5B0A7"),
            ]),
        )

    def quiz_screen(cw: int):
        step = state["step"]
        if step > QUESTIONS:
            return results_screen(cw)
        head = ft.Column(spacing=14, controls=[
            ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW, icon_color=INK, icon_size=20, tooltip="上一題",
                              on_click=lambda e: quiz_go(step - 1)),
                ft.Container(expand=True),
                caps(f"QUESTION 0{step} / 0{QUESTIONS}"),
                ft.IconButton(icon=ft.Icons.CLOSE, icon_color=INK, icon_size=20, tooltip="離開",
                              on_click=lambda e: close_overlay()),
            ]),
            ft.Container(padding=pad(PAD - 8, 0, PAD - 8, 0),
                         content=ft.ProgressBar(value=step / QUESTIONS, color=INK, bgcolor=LINE, bar_height=2)),
        ])

        def pick(key, value):
            def handler(e):
                state[key] = value
                quiz_go(step + 1)
            return handler

        if step == 1:
            title, sub = "你現在在哪？", "從離你最近的地方出發"
            rows = [option_row(b.name, "", state["origin"] == b.id, pick("origin", b.id)) for b in buildings]
        elif step == 2:
            title, sub = "有多少時間吃飯？", "包含走路和吃飯"
            rows = [option_row(l, h, state["minutes"] == v, pick("minutes", v)) for v, l, h in TIME_OPTIONS]
        elif step == 3:
            title, sub = "預算大概多少？", "一個人"
            rows = [option_row(l, h, state["budget"] == v, pick("budget", v)) for v, l, h in BUDGET_OPTIONS]
        elif step == 4:
            title, sub = "幾個人一起吃？", ""
            rows = [option_row(l, h, state["party"] == v, pick("party", v)) for v, l, h in PARTY_OPTIONS]
        else:
            title, sub = "有什麼飲食需求？", "可以複選，沒有就直接找"

            def toggle(key, value):
                def handler(e):
                    state[key] ^= {value}
                    render(keep_scroll=True)
                return handler

            rows = [
                ft.Row(wrap=True, spacing=8, run_spacing=8,
                       controls=[chip(l, v in state["tags"], toggle("tags", v)) for v, l in DIET_OPTIONS]),
                ft.Container(height=8),
                section_label("ALLERGY", "會過敏的食物"),
                ft.Row(wrap=True, spacing=8, run_spacing=8,
                       controls=[chip(l, v in state["allergens"], toggle("allergens", v)) for v, l in ALLERGY_OPTIONS]),
                ft.Container(height=16),
                ft.Row([pill("幫我找", lambda e: quiz_go(QUESTIONS + 1), expand=True)]),
            ]
        body = ft.Container(padding=pad(PAD, 18, PAD, 0), content=ft.Column(spacing=0, controls=[
            serif(title, 28, weight=ft.FontWeight.W_600, height=1.35),
            sans(sub, 13, MUTED) if sub else ft.Container(),
            ft.Container(height=18),
            *rows,
        ]))
        return [ft.Container(padding=pad(8, 8, 8, 0), content=head), body]

    def pick_card(rec: Recommendation, no: int, from_surprise: bool = False):
        r = rec.restaurant
        busy = rec.crowd_hint.startswith("尖峰時段，可能")
        crowd = "可能要排隊" if busy else ("人有點多" if "稍多" in rec.crowd_hint else "應該不用排")
        closing = f"{rec.minutes_until_close} 分後打烊" if rec.minutes_until_close < 90 else "營業中"

        def eat_here(e):
            if from_surprise:
                page.pop_dialog()
            open_overlay("record", restaurant=r, walk=rec.walk_minutes, surprise=from_surprise)

        return ft.Container(
            **GLASS_KW, border_radius=22, padding=20,
            content=ft.Column(spacing=10, controls=[
                ft.Row([caps("SURPRISE" if from_surprise else f"0{no}"), ft.Container(expand=True),
                        caps(price_text(r))]),
                serif(r.name, 23, height=1.3),
                sans(f"{r.area} · 走 {rec.walk_minutes} 分 · {closing} · {crowd}", 12,
                     ACCENT if busy or rec.minutes_until_close < 45 else MUTED, spacing=0.3),
                sans("・".join(rec.reasons), 13, BODY, height=1.7),
                ft.Container(height=2),
                ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    pill("就吃這家", eat_here, expand=True),
                    link_button("導航", walk_url(r), filled=False, icon=ft.Icons.DIRECTIONS_WALK),
                    wish_button(wish_item_from_restaurant(r)),
                ]),
                sans(data_note(r), 11, MUTED),
            ]),
        )

    def open_surprise(q: Query):
        rec = surprise(restaurants, buildings, q, taipei_now())
        if rec is None:
            toast("現在沒有符合條件的店可以抽")
            return

        def again(e):
            page.pop_dialog()
            open_surprise(q)

        page.show_dialog(ft.AlertDialog(
            bgcolor=BG, content_padding=12,
            title=serif("就決定是這家。", 20, center=True),
            content=ft.Container(width=360, content=pick_card(rec, 0, from_surprise=True)),
            actions=[ft.TextButton(content="再抽一次", on_click=again),
                     ft.TextButton(content="關閉", on_click=lambda e: page.pop_dialog())],
        ))

    def results_screen(cw: int):
        q, now = build_query(), taipei_now()
        picks = recommend(restaurants, buildings, q, now)
        bname = origin_building().name
        budget = "不設限" if q.budget >= 9999 else f"{q.budget} 元內"
        head = ft.Row([
            ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW, icon_color=INK, icon_size=20, tooltip="改條件",
                          on_click=lambda e: quiz_go(QUESTIONS)),
            ft.Container(expand=True),
            ft.IconButton(icon=ft.Icons.CLOSE, icon_color=INK, icon_size=20, tooltip="離開", on_click=lambda e: close_overlay()),
        ])
        controls = [
            caps(f"{now:%H:%M} · {bname} · {q.minutes_available} 分 · {budget} · {q.party_size} 人"),
            serif("就從這幾家選吧。" if picks else "現在找不到合適的店。", 28, weight=ft.FontWeight.W_600, height=1.35),
        ]
        if not picks:
            controls += [sans(explain_empty(restaurants, buildings, q, now), 14, BODY, height=1.8),
                         ft.Row([pill("回去改條件", lambda e: quiz_go(2), expand=True)])]
        else:
            controls += [pick_card(p, i + 1) for i, p in enumerate(picks)]
            controls.append(ft.Container(
                border_radius=22, padding=20, bgcolor=INK, on_click=lambda e: open_surprise(q), ink=True,
                content=ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Column(spacing=4, expand=True, controls=[
                        serif("還是選不出來？", 19, BG), sans("驚喜一下，從符合條件的店抽一家。", 13, "#D8D3CA")]),
                    ft.Icon(ft.Icons.CASINO_OUTLINED, size=26, color=BG)]),
            ))
        return [ft.Container(padding=pad(8, 8, 8, 0), content=head),
                ft.Container(padding=pad(PAD, 4, PAD, 0), content=ft.Column(controls, spacing=18))]

    # ==================== 想去 ====================
    def wish_screen(cw: int, header: bool = True):
        now = taipei_now()
        b = origin_building()

        def wish_card(w: dict):
            r = by_id.get(w["key"])
            if r:
                status, is_open = restaurant_status(r, now)
                info = f"{r.area} · 走 {walking_minutes(b, r)} 分 · {status}"
            else:
                info, is_open = (w.get("area") or "自己加的店") + " · 沒有營業資料", False

            async def remove(e):
                await store.toggle_wish(w)
                render(keep_scroll=True)

            def record(e):
                if r:
                    open_overlay("record", restaurant=r, walk=walking_minutes(b, r))
                else:
                    open_overlay("record", name=w["name"])

            return ft.Container(
                **GLASS_KW, border_radius=20, padding=pad(18, 16, 8, 12),
                on_click=(lambda e: open_overlay("place", restaurant=r)) if r else None,
                content=ft.Column(spacing=6, controls=[
                    ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                        ft.Column(spacing=4, expand=True, controls=[
                            serif(w["name"], 20, height=1.3, max_lines=1),
                            sans(info, 12, MUTED if is_open else "#9C978E", spacing=0.3)]),
                        ft.IconButton(icon=ft.Icons.BOOKMARK, icon_color=ACCENT, tooltip="從想去移除", on_click=remove),
                    ]),
                    ft.Row(spacing=4, controls=[
                        ft.TextButton(content=sans("記錄這一餐", 13, INK), on_click=record),
                        *([link_button("導航", walk_url(r), filled=False,
                                       icon=ft.Icons.DIRECTIONS_WALK, height=36)] if r else []),
                    ]),
                ]),
            )

        def draw(e):
            known = [by_id[w["key"]] for w in store.wish if w["key"] in by_id]
            open_ones = [r for r in known if minutes_until_close(r, now) is not None]
            pool = open_ones or known
            if not pool:
                toast("清單裡還沒有可以抽的店")
                return
            r = random.choice(pool)
            walk = walking_minutes(b, r)
            left = minutes_until_close(r, now)
            rec = Recommendation(r, walk, left if left is not None else 0, crowd_hint(r, now), 0,
                                 ["從你的想去清單抽出來的"] + ([] if left is not None else ["不過現在沒開"]))
            page.show_dialog(ft.AlertDialog(
                bgcolor=BG, content_padding=12, title=serif("今天就去這家。", 20, center=True),
                content=ft.Container(width=360, content=pick_card(rec, 0, from_surprise=True)),
                actions=[ft.TextButton(content="再抽一次", on_click=lambda ev: (page.pop_dialog(), draw(ev))),
                         ft.TextButton(content="關閉", on_click=lambda ev: page.pop_dialog())],
            ))

        controls = [
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.END,
                   controls=[ft.Column([caps("WISHLIST · 想去"), serif("想去清單", 30, weight=ft.FontWeight.W_600, height=1.2)],
                                       spacing=4),
                             caps(f"{len(store.wish)} 家")]),
        ] if header else []
        if store.wish:
            controls.append(ft.Row([pill("從清單抽一家", draw, filled=False, accent=True, expand=True,
                                         icon=ft.Icons.CASINO_OUTLINED)]))
            controls += [wish_card(w) for w in store.wish]
        else:
            controls.append(ft.Container(
                **GLASS_KW, border_radius=22, padding=24,
                content=ft.Column(spacing=8, controls=[
                    serif("還沒有想去的店", 20),
                    sans("在動態或探索按書籤，店就會收在這裡。選不出來的時候，可以從清單抽一家。", 14, BODY, height=1.7),
                    ft.Container(height=4),
                    ft.Row([pill("去探索", tab_handler("explore"), filled=False)]),
                ]),
            ))
        if not header:
            return controls
        return [ft.Container(padding=pad(PAD, 20, PAD, 0), content=ft.Column(controls, spacing=18))]

    # ==================== 個人食譜誌 ====================
    recap_cache: dict[tuple, bytes] = {}
    font_loading = {"on": False}         # 網頁版：宋體下載中就不要重複下載

    def recap_png() -> bytes:
        y, m, kind = state["recap_year"], state["recap_month"], state["recap_kind"]
        month_entries = journal.in_month(store.entries, y, m)
        key = (y, m, kind, tuple(sorted(e.id for e in month_entries)),
               sum(1 for e in month_entries if e.id in store.photos))
        if key not in recap_cache:
            if kind == "stats":
                recap_cache[key] = render_stats_card(journal.monthly_stats(store.entries, y, m))
            else:
                recap_cache[key] = render_photo_dump(month_entries, store.photos, y, m)
        return recap_cache[key]

    def shift_month(delta: int):
        y, m = state["recap_year"], state["recap_month"] + delta
        if m == 0:
            y, m = y - 1, 12
        if m == 13:
            y, m = y + 1, 1
        now = taipei_now()
        if (y, m) > (now.year, now.month):
            return
        state["recap_year"], state["recap_month"] = y, m
        render(keep_scroll=True)

    def journal_screen(cw: int):
        now = taipei_now()
        s = journal.monthly_stats(store.entries, now.year, now.month)
        entries = journal.sort_newest_first(store.entries)

        def stat(value, label, first=False):
            return ft.Container(
                expand=True, padding=pad(0 if first else 14, 14, 0, 14),
                border=None if first else ft.Border(left=ft.BorderSide(1, LINE)),
                content=ft.Column([serif(value, 26, height=1.1), caps(label, 10)], spacing=6),
            )

        def set_view(v):
            def handler(e):
                state["journal_view"] = v
                render(keep_scroll=True)
            return handler

        head = [
            ft.Column([caps("ME · 我的食譜誌"), serif("我的", 30, weight=ft.FontWeight.W_600, height=1.2)], spacing=4),
            profile_card(),
            caps(f"{len(entries)} 餐 · {len(store.photos)} 張照片 · {len(store.wish)} 家想去"),
            ft.Container(border=ft.Border(top=ft.BorderSide(1, LINE), bottom=ft.BorderSide(1, LINE)),
                         content=ft.Row(spacing=0, controls=[
                             stat(str(s["meals"]), f"{MONTHS_EN[now.month - 1]} · 餐", True),
                             stat(str(s["places"]), "家店"),
                             stat(f"{s['km']}", "KM 走路")])),
            ft.Row(spacing=24, controls=[
                text_tab("紀錄", state["journal_view"] == "grid", set_view("grid")),
                text_tab("每月 Dump", state["journal_view"] == "dump", set_view("dump")),
                text_tab("想去", state["journal_view"] == "wish", set_view("wish")),
            ]),
        ]
        view = state["journal_view"]
        body = (journal_grid(cw, entries) if view == "grid" else dump_view(cw) if view == "dump"
                else wish_screen(cw, header=False))
        return [ft.Container(padding=pad(PAD, 24, PAD, 0), content=ft.Column(head + body, spacing=18))]

    def journal_grid(cw: int, entries):
        if not entries:
            return [ft.Container(
                **GLASS_KW, border_radius=22, padding=24,
                content=ft.Column(spacing=8, controls=[
                    serif("食譜誌還是空白的", 20),
                    sans("按下方的＋記錄這一餐，或在探索選一家「就吃這家」。", 14, BODY, height=1.7),
                ]),
            )]
        tw = (cw - PAD * 2 - 8) / 3
        out = []
        months = journal.months_with_entries(entries)
        for y, m in months:
            month_entries = [e for e in entries if e.when.year == y and e.when.month == m]
            out.append(caps(f"{MONTHS_EN[m - 1]} {y} · {m} 月 · {len(month_entries)} 餐"))
            tiles = []
            for e in month_entries:
                tiles.append(ft.Container(
                    on_click=lambda ev, e=e: open_overlay("post", post=post_from_entry(e)),
                    content=ft.Column(spacing=4, controls=[
                        photo_box(store.photos.get(e.id), tw, 1.25, 8, e.name, small=True),
                        sans(e.name, 11, INK, max_lines=1),
                    ]),
                ))
            out.append(ft.Row(tiles, wrap=True, spacing=4, run_spacing=12))
        return out

    def dump_view(cw: int):
        y, m, kind = state["recap_year"], state["recap_month"], state["recap_kind"]

        def set_kind(k):
            def handler(e):
                state["recap_kind"] = k
                render(keep_scroll=True)
            return handler

        out = [
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                   controls=[
                       ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, icon_color=INK, tooltip="上個月",
                                     on_click=lambda e: shift_month(-1)),
                       serif(f"{y} 年 {m} 月", 18, height=1.2),
                       ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, icon_color=INK, tooltip="下個月",
                                     on_click=lambda e: shift_month(1)),
                   ]),
            ft.Row([chip("飯 Dump", kind == "dump", set_kind("dump")),
                    chip("數據卡", kind == "stats", set_kind("stats"))], spacing=8,
                   alignment=ft.MainAxisAlignment.CENTER),
        ]
        if not HAS_PILLOW:
            out.append(sans("產生 Dump 需要 Pillow 套件。請在終端機執行：pip3 install pillow", 14, MUTED, height=1.7))
            return out
        if not serif_ready():
            async def load_font():
                try:
                    await ensure_serif_font()
                finally:
                    font_loading["on"] = False
                recap_cache.clear()
                render(keep_scroll=True)
            if not font_loading["on"]:
                font_loading["on"] = True
                page.run_task(load_font)
            out.append(sans("正在下載字體，第一次會花幾秒鐘…", 14, MUTED, center=True))
            return out
        png = recap_png()

        async def download(e):
            await save_png(png, f"席間_{y}{m:02d}_{'飯Dump' if kind == 'dump' else '數據卡'}.png")

        w = cw - PAD * 2 - 40
        out += [
            ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[ft.Container(
                width=w, height=w * 16 / 9, border_radius=16, border=hairline(),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=ft.Image(src=png, width=w, height=w * 16 / 9, fit=ft.BoxFit.COVER))]),
            ft.Row([pill("存成圖片，分享到 IG 限動", download, expand=True)]),
            ft.Row([link_button("發到 Threads", threads_url(f"我的 {m} 月餐桌，在 Table 席間記錄的。"),
                                filled=False, expand=True)]),
            sans("飯 Dump 會優先放有照片的紀錄，最多 9 張。" if kind == "dump" else
                 "數據卡會統計這個月吃了幾餐、最常去哪、走了多遠。", 12, MUTED, center=True),
        ]
        return out

    # ==================== 社群（Supabase）：共用小工具 ====================
    def logged() -> bool:
        return cloud.enabled and cloud.logged_in

    def ready() -> bool:
        return logged() and bool(state["profile"])

    async def save_session():
        try:
            await store.prefs.set(KEY_SESSION, cloud.dump_session())
        except Exception:
            pass

    async def cloud_call(coro, quiet: bool = False):
        """回傳 (成功與否, 結果)。失敗時跳出中文提示；登入失效就登出。"""
        try:
            result = await coro
        except CloudError as exc:
            msg = str(exc)
            if "登入" in msg and "台大" not in msg:
                cloud.sign_out()
                state["profile"] = None
                await save_session()
            if not quiet:
                toast(msg)
            return False, None
        await save_session()
        return True, result

    async def load_feed():
        if ready():
            ok, rows = await cloud_call(cloud.feed(60), quiet=True)
            state["feed"] = rows if ok else (state["feed"] or [])

    async def load_meetups():
        if ready():
            ok, rows = await cloud_call(cloud.open_meetups(), quiet=True)
            state["meetups"] = rows if ok else (state["meetups"] or [])

    async def load_board():
        if ready():
            ok, rows = await cloud_call(cloud.leaderboard(state["board_days"], 10), quiet=True)
            state["board"] = rows if ok else (state["board"] or [])
            ok, boosted = await cloud_call(cloud.my_boosts_today(), quiet=True)
            if ok:
                state["boosted"] = set(boosted)

    async def refresh_tab(tab: str):
        if tab == "feed":
            await load_feed()
        elif tab == "explore":
            await load_board()
        elif tab == "meet":
            await load_meetups()

    async def go_tab(tab: str):
        switch_tab(tab)
        if ready():
            await refresh_tab(tab)
            if state["tab"] == tab and not state["overlay"]:
                render(keep_scroll=True)

    def threads_url(text: str) -> str:
        return ("https://www.threads.com/intent/post?text=" + urllib.parse.quote(text)
                + ("&url=" + urllib.parse.quote(SITE_URL) if SITE_URL else ""))

    def login_card(title: str, body: str):
        if not cloud.enabled:
            return ft.Container(
                **GLASS_KW, border_radius=22, padding=22,
                content=ft.Column(spacing=8, controls=[
                    caps("COMING SOON · 社群功能"), serif("社群功能還沒開通", 20),
                    sans("負責的組員照 README「社群功能設定」那一節接上 Supabase 後，這裡就能登入。"
                         "現在先看範例。", 14, BODY, height=1.7)]),
            )
        return ft.Container(
            **GLASS_KW, border_radius=22, padding=22,
            content=ft.Column(spacing=8, controls=[
                caps("JOIN · 加入餐桌"), serif(title, 20), sans(body, 14, BODY, height=1.7),
                ft.Container(height=4),
                ft.Row([pill("取個暱稱加入", lambda e: open_overlay("login"))]),
            ]),
        )

    def boost_button(rid: str, name: str, area: str, big: bool = False):
        icon = ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT_OUTLINED, size=19)
        label = sans("", 13, spacing=0.5)
        box = ft.Container(height=48 if big else 40, border_radius=24,
                           padding=pad(16, 0, 16, 0) if big else pad(8, 0, 8, 0),
                           content=ft.Row([icon, label], spacing=5, tight=True,
                                          alignment=ft.MainAxisAlignment.CENTER))

        def paint():
            on = rid in state["boosted"]
            set_icon(icon, ft.Icons.LOCAL_FIRE_DEPARTMENT if on else ft.Icons.LOCAL_FIRE_DEPARTMENT_OUTLINED)
            icon.color = label.color = ACCENT if on else INK
            label.value = "已助力" if on else "助力"
            if big:
                box.border = hairline(ACCENT if on else LINE)

        async def toggle(e):
            if not ready():
                open_overlay("login")
                return
            if rid in state["boosted"]:
                toast("今天已經幫這家助力過了，明天可以再來")
                return
            ok, _ = await cloud_call(cloud.boost(rid, name, area))
            if not ok:
                return
            state["boosted"].add(rid)
            state["board"] = None
            paint()
            box.update()
            toast(f"幫「{name}」助力 +1")

        paint()
        box.on_click = toggle
        return box

    def report_dialog(target_type: str, target_id, user_id: str = "", name: str = ""):
        def send(reason):
            async def handler(e):
                page.pop_dialog()
                ok, _ = await cloud_call(cloud.report(target_type, str(target_id), reason))
                if ok:
                    toast("收到了，我們會盡快處理。謝謝你告訴我們")
            return handler

        async def block(e):
            page.pop_dialog()
            ok, _ = await cloud_call(cloud.block_user(user_id))
            if ok:
                toast(f"已封鎖 {name}，你們不會再看到彼此的動態與飯局")
                state["feed"] = None
                state["meetups"] = None
                if state["overlay"] and state["overlay"]["kind"] == "meetup":
                    state["overlay"] = None
                await refresh_tab(state["tab"])
                render()

        actions = [ft.TextButton(content="不當內容", on_click=send("不當內容")),
                   ft.TextButton(content="騷擾或讓人不舒服", on_click=send("騷擾或不舒服")),
                   ft.TextButton(content="其他", on_click=send("其他"))]
        if user_id and user_id != cloud.user_id:
            actions.append(ft.TextButton(content=f"封鎖 {name}", on_click=block))
        actions.append(ft.TextButton(content="取消", on_click=lambda e: page.pop_dialog()))
        page.show_dialog(ft.AlertDialog(
            bgcolor=BG, title=serif("檢舉或封鎖", 20),
            content=sans("檢舉內容只有管理的組員看得到，對方不會知道是誰檢舉的。", 13, MUTED, height=1.7),
            actions=actions,
        ))

    # ==================== 社群：動態流 ====================
    def cloud_post(a: dict) -> Post:
        photo = cloud.public_url(a.get("photo_path") or "") or None
        return Post(
            id=f"c{a['ref_id']}", author=a["actor_name"], initial=(a["actor_name"] or "?")[:1],
            at=to_taipei(a["created_at"]) or taipei_now(), place=a["restaurant_name"], area=a.get("area", ""),
            tags=list(a.get("tags") or []), note=a.get("note", ""), photo=photo,
            restaurant_id=a.get("restaurant_id", ""), cheered_by=list(a.get("cheer_names") or []),
            cloud_id=a["ref_id"], cheered=bool(a.get("cheered")), own=bool(a.get("mine")),
            dept=a.get("actor_dept", ""), actor_id=a.get("actor_id", ""),
        )

    def activity_row(icon, line: str, sub: str, trailing=None, on_click=None):
        return ft.Container(
            border=bottom_line(), padding=pad(2, 12, 0, 12), on_click=on_click,
            content=ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Container(width=32, height=32, border_radius=16, bgcolor=EMPTY, alignment=ft.Alignment.CENTER,
                             content=ft.Icon(icon, size=17, color=ACCENT)),
                ft.Column(spacing=2, expand=True, controls=[sans(line, 14, INK, max_lines=2, height=1.5),
                                                            sans(sub, 11, MUTED, spacing=0.3)]),
                trailing or ft.Container(),
            ]),
        )

    def cloud_feed_item(a: dict, cw: int):
        verb = a["verb"]
        when = relative_time(to_taipei(a["created_at"]) or taipei_now(), taipei_now())
        r = by_id.get(a.get("restaurant_id", ""))
        open_place = (lambda e, r=r: open_overlay("place", restaurant=r)) if r else None
        if verb == "post":
            return feed_card(cloud_post(a), cw)
        if verb == "boost":
            return activity_row(ft.Icons.LOCAL_FIRE_DEPARTMENT_OUTLINED,
                                f"{a['actor_name']} 幫「{a['restaurant_name']}」助力",
                                " · ".join(x for x in [a.get("area", ""), when] if x),
                                boost_button(a["restaurant_id"], a["restaurant_name"], a.get("area", "")) if r else None,
                                open_place)
        if verb == "title":
            return activity_row(ft.Icons.AUTO_AWESOME_OUTLINED, f"{a['actor_name']} 測出「{a.get('extra', '')}」", when,
                                ft.TextButton(content=sans("我也測", 13, INK), on_click=lambda e: open_overlay("fun")))
        m = a.get("meetup") or {}
        radar = verb == "radar"
        theme = a.get("extra") or ""
        line = (f"{a['actor_name']} 現在想去「{a['restaurant_name']}」，找人一起" if radar
                else f"{a['actor_name']} 開了飯局：{a['restaurant_name']}")
        sub = f"{m.get('count', 1)}/{m.get('capacity', '?')} 人" + (f" · {theme}" if theme else "") + f" · {when}"
        joined = m.get("joined")
        trailing = (sans("已加入", 12, ACCENT) if joined else
                    ft.TextButton(content=sans("加入", 13, ACCENT, ft.FontWeight.W_500),
                                  on_click=join_handler(m.get("id"))))
        return activity_row(ft.Icons.RADAR if radar else ft.Icons.GROUPS_OUTLINED, line, sub, trailing,
                            meetup_opener(m.get("id")))

    # ==================== 社群：飯局 ====================
    def meetup_when(m: dict) -> str:
        starts, expires = to_taipei(m["starts_at"]), to_taipei(m["expires_at"])
        if m["kind"] == "radar":
            left = max(0, int((expires - taipei_now()).total_seconds() // 60)) if expires else 0
            return f"RADAR · 現在就走 · 還剩 {left} 分鐘"
        return f"{starts.month}/{starts.day}（{WEEKDAYS[starts.weekday()]}）{starts:%H:%M}"

    def common_line(m: dict) -> str:
        parts = []
        if m.get("shared_places"):
            parts.append("你們都助力過 " + "、".join(m["shared_places"][:2]))
        if m.get("same_dept"):
            parts.append(f"{m['same_dept']} 位同系")
        return " · ".join(parts)

    def join_handler(mid):
        async def handler(e):
            if mid is None:
                return
            if not ready():
                open_overlay("login")
                return
            if not store.pact:
                pact_dialog(mid)
                return
            await do_join(mid)
        return handler

    async def do_join(mid):
        ok, res = await cloud_call(cloud.join_meetup(mid))
        if not ok:
            return
        joined, reason = res
        toast("加入了！記得準時出現，臨時不能去要先退出" if joined else reason)
        state["feed"] = None
        await load_meetups()
        if state["overlay"] and state["overlay"]["kind"] == "meetup":
            await open_meetup(mid)
        else:
            await refresh_tab(state["tab"])
            render(keep_scroll=True)

    PACT = ("只約在餐廳，不約到宿舍或私人地方。不推銷、不傳教、不拉保險。"
            "不強迫交換聯絡方式。不舒服可以隨時離開，也可以檢舉。")

    def pact_dialog(mid=None, then=None):
        async def agree(e):
            page.pop_dialog()
            await store.set_pact()
            if mid is not None:
                await do_join(mid)
            elif then is not None:
                await then()

        page.show_dialog(ft.AlertDialog(
            bgcolor=BG, title=serif("飯局公約", 20), content=sans(PACT, 14, BODY, height=1.8),
            actions=[ft.TextButton(content="我同意", on_click=agree),
                     ft.TextButton(content="再想想", on_click=lambda e: page.pop_dialog())],
        ))

    def meetup_card(m: dict):
        members = m.get("member_names") or []
        full = len(members) >= m["capacity"]
        if m.get("joined"):
            action = pill("查看", meetup_opener(m["id"]), filled=False)
        elif full:
            action = sans("人數已滿", 12, MUTED)
        else:
            action = pill("加入", join_handler(m["id"]), accent=True)
        when = meetup_when(m) + (" · 好友限定" if m.get("friends_only") else "")
        lines = [caps(when, 11, ACCENT if m["kind"] == "radar" else MUTED),
                 serif(m["restaurant_name"], 20, max_lines=1, height=1.3)]
        if m.get("theme"):
            lines.append(sans(m["theme"], 13, BODY, max_lines=2, height=1.6))
        lines.append(sans(f"{'、'.join(members[:4])}{' 等' if len(members) > 4 else ''} · {len(members)}/{m['capacity']} 人"
                          f" · 主揪 {m['host_name']}", 12, MUTED, max_lines=1))
        if common_line(m):
            lines.append(sans(common_line(m), 12, ACCENT, max_lines=1))
        return ft.Container(
            bgcolor=CARD, border=hairline(ACCENT if m["kind"] == "radar" else LINE), border_radius=20,
            padding=pad(18, 16, 14, 14), on_click=meetup_opener(m["id"]),
            content=ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Column(lines, spacing=5, expand=True), action]),
        )

    def meetup_opener(mid):
        async def handler(e):
            await open_meetup(mid)
        return handler

    async def open_meetup(mid):
        if mid is None:
            return
        if not any(m["id"] == mid for m in state["meetups"] or []):
            await load_meetups()
        state["overlay"] = {"kind": "meetup", "meetup_id": mid, "card": 0, "members": None}
        render()
        m = next((x for x in state["meetups"] or [] if x["id"] == mid), None)
        if m and m.get("joined"):
            if state["friends"] is None:
                await load_friends()
            ok, members = await cloud_call(cloud.meetup_members(mid), quiet=True)
            ov = state["overlay"]
            if ov and ov.get("meetup_id") == mid:
                ov["members"] = members if ok else []
                render(keep_scroll=True)

    def meet_screen(cw: int):
        async def refresh(e):
            state["meetups"] = None
            render(keep_scroll=True)
            await load_meetups()
            render(keep_scroll=True)

        head = ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.END,
                      controls=[ft.Column([caps("MEET · 一起吃"), serif("飯局", 30, weight=ft.FontWeight.W_600, height=1.2)],
                                          spacing=4),
                                ft.IconButton(icon=ft.Icons.REFRESH, icon_color=INK, tooltip="重新整理", on_click=refresh)])
        controls = [head]
        if not ready():
            controls.append(login_card("找人一起吃飯", "取個暱稱加入後，可以開飯局、加入別人的飯局，"
                                                      "或丟一個 1 小時內有效的「現在就走」吃飯雷達。"))
            return [ft.Container(padding=pad(PAD, 20, PAD, 0), content=ft.Column(controls, spacing=18))]
        controls.append(ft.Row([
            pill("現在就走", lambda e: open_overlay("newmeet", radar=True), filled=False, accent=True,
                 expand=True, icon=ft.Icons.RADAR),
            pill("開一個飯局", lambda e: open_overlay("newmeet", radar=False), expand=True, icon=ft.Icons.ADD),
        ], spacing=10))
        rows = state["meetups"]
        if rows is None:
            controls.append(sans("載入中…", 13, MUTED))
        else:
            radars = [m for m in rows if m["kind"] == "radar"]
            meals = [m for m in rows if m["kind"] != "radar"]
            controls.append(section_label("RADAR", "現在就走，1 小時內有效"))
            controls += [meetup_card(m) for m in radars] or [
                sans("現在沒有人在找飯友。丟一個雷達試試？", 13, MUTED)]
            controls.append(section_label("UPCOMING", "接下來的飯局"))
            controls += [meetup_card(m) for m in meals] or [
                sans("還沒有飯局。挑一家想吃的店，開第一團吧。", 13, MUTED)]
        controls.append(sans("飯局只約在餐廳，不會顯示任何人的即時位置。遇到不舒服的事，"
                             "在飯局頁按「檢舉」。", 11, MUTED, height=1.7))
        return [ft.Container(padding=pad(PAD, 20, PAD, 0), content=ft.Column(controls, spacing=16))]

    def add_friend_button(p: dict):
        async def handler(e):
            ok, res = await cloud_call(cloud.request_friend(p["user_id"]))
            if ok:
                done, reason = res
                toast(reason or ("已送出邀請" if done else "無法加好友"))
                if reason == "已成為好友":
                    await load_friends()
                    render(keep_scroll=True)
        return ft.TextButton(content=sans("加好友", 12, ACCENT), on_click=handler)

    def meetup_screen(cw: int):
        ov = state["overlay"]
        mid = ov["meetup_id"]
        m = next((x for x in state["meetups"] or [] if x["id"] == mid), None)
        back = ft.Row([ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW, icon_color=INK, icon_size=20, tooltip="返回",
                                     on_click=lambda e: close_overlay())])
        if not m:
            return [ft.Container(padding=pad(8, 8, 8, 0), content=back),
                    ft.Container(padding=pad(PAD, 8, PAD, 0), content=ft.Column(spacing=10, controls=[
                        serif("這個飯局已經結束或被取消了", 22), sans("回到飯局頁看看其他團吧。", 14, MUTED)]))]
        r = by_id.get(m["restaurant_id"])
        members = ov.get("members") or []
        blocks = [caps(meetup_when(m), 11, ACCENT if m["kind"] == "radar" else MUTED),
                  serif(m["restaurant_name"], 30, weight=ft.FontWeight.W_600, height=1.3)]
        if m.get("theme"):
            blocks.append(sans(m["theme"], 15, BODY, height=1.8))
        if r:
            blocks.append(sans(f"{r.area} · {hours_today(r, taipei_now())} · {price_text(r)}", 12, MUTED))
        people = []
        if members:
            for p in members:
                sub = " · ".join(x for x in [p.get("dept", ""), p.get("title", "")] if x)
                people.append(ft.Row(spacing=10, controls=[
                    avatar((p["display_name"] or "?")[:1], 30),
                    ft.Column(spacing=1, expand=True, controls=[sans(p["display_name"], 14, weight=ft.FontWeight.W_500),
                                                                sans(sub, 11, MUTED)]),
                    caps("主揪") if p["user_id"] == m["host_id"] else ft.Container(),
                    add_friend_button(p) if p["user_id"] != cloud.user_id and p["user_id"] not in friend_ids()
                    else ft.Container()]))
        else:
            people.append(sans("、".join(m.get("member_names") or []), 14, BODY))
        blocks.append(ft.Column([section_label("WHO", f"{len(m.get('member_names') or [])}/{m['capacity']} 人"), *people],
                                spacing=10))
        if common_line(m):
            blocks.append(sans(common_line(m), 13, ACCENT))

        if m.get("joined"):
            cards, games = icebreaker_cards(mid, m["restaurant_name"], m.get("area", ""), m.get("shared_places") or [],
                                            [p.get("title", "") for p in members])
            idx = ov.get("card", 0) % len(cards)

            def flip(delta):
                def handler(e):
                    ov["card"] = (idx + delta) % len(cards)
                    render(keep_scroll=True)
                return handler

            blocks.append(ft.Column(spacing=10, controls=[
                section_label("ICEBREAKER", "破冰字卡，大家輪流抽"),
                ft.Container(bgcolor=INK, border_radius=22, padding=24, height=200, on_click=flip(1),
                             content=ft.Column(spacing=12, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                 caps(f"CARD {idx + 1:02d} / {len(cards):02d}", 11, "#B5B0A7"),
                                 serif(cards[idx], 20, BG, height=1.6),
                                 sans("點一下換下一張", 11, "#B5B0A7")])),
                ft.Row([pill("上一張", flip(-1), filled=False, expand=True), pill("下一張", flip(1), expand=True)],
                       spacing=10),
                section_label("GAMES", "餐桌小遊戲"),
                *[ft.Container(border=bottom_line(), padding=pad(0, 8, 0, 10), content=ft.Column(spacing=4, controls=[
                    serif(name, 16, height=1.3), sans(how, 13, BODY, height=1.7)])) for name, how in games],
            ]))

        async def leave(e):
            ok, _ = await cloud_call(cloud.leave_meetup(mid))
            if ok:
                toast("已取消這個飯局" if m.get("mine") else "已退出飯局")
                state["overlay"] = None
                state["feed"] = None
                await load_meetups()
                render()

        actions = []
        if r:
            actions.append(link_button("導航", walk_url(r), filled=False, icon=ft.Icons.DIRECTIONS_WALK))
        if m.get("joined"):
            actions.append(pill("取消飯局" if m.get("mine") else "退出飯局", leave, filled=False, expand=True))
        else:
            actions.append(pill("加入", join_handler(mid), accent=True, expand=True))
        blocks.append(ft.Row(actions, spacing=10))
        if not m.get("mine"):
            blocks.append(ft.Row([ft.TextButton(content=sans("檢舉或封鎖", 12, MUTED),
                                                on_click=lambda e: report_dialog("meetup", mid, m["host_id"], m["host_name"]))]))
        return [ft.Container(padding=pad(8, 8, 8, 0), content=back),
                ft.Container(padding=pad(PAD, 4, PAD, 0), content=ft.Column(blocks, spacing=20))]

    def newmeet_screen(cw: int):
        ov = state["overlay"]
        radar = bool(ov.get("radar"))
        d = ov.setdefault("draft", {"name": "", "restaurant": ov.get("restaurant"), "day": 0, "time": "",
                                    "capacity": 2 if radar else 4, "theme": "", "pact": store.pact,
                                    "friends_only": bool(ov.get("friends_only"))})
        if d["restaurant"] and not d["name"]:
            d["name"] = d["restaurant"].name
        now = taipei_now()
        suggest_row = ft.Row(wrap=True, spacing=8, run_spacing=8)

        def pick(r):
            def handler(e):
                d["name"], d["restaurant"] = r.name, r
                name_field.value = r.name
                suggest_row.controls = []
                name_field.update()
                suggest_row.update()
            return handler

        def on_name(e):
            d["name"] = name_field.value or ""
            d["restaurant"] = next((x for x in restaurants if x.name == d["name"].strip()), None)
            q = d["name"].strip()
            suggest_row.controls = [chip(r.name, False, pick(r)) for r in restaurants
                                    if q and q in r.name and r.name != q][:6]
            suggest_row.update()

        name_field = ft.TextField(
            value=d["name"], hint_text="店名，從清單裡選一家", border=ft.InputBorder.UNDERLINE,
            border_color=LINE, focused_border_color=INK, cursor_color=ACCENT, on_change=on_name,
            text_style=ft.TextStyle(size=20, font_family=serif_family, color=INK),
        )

        def setter(key, value):
            def handler(e):
                d[key] = value
                render(keep_scroll=True)
            return handler

        times = ["11:30", "12:00", "12:30", "17:30", "18:00", "18:30", "19:00", "20:00", "21:00"]
        day_names = ["今天", "明天", "後天"]
        valid_times = [t for t in times if d["day"] > 0 or t > f"{now:%H:%M}"]
        if d["time"] not in valid_times:
            d["time"] = valid_times[0] if valid_times else ""

        def on_theme(e):
            d["theme"] = (theme_field.value or "")[:40]

        theme_field = ft.TextField(value=d["theme"], hint_text="例如：一個人不敢吃的店、系上新生交流", max_length=40,
                                   border_color=LINE, focused_border_color=INK, cursor_color=ACCENT, bgcolor=CARD,
                                   border_radius=14, on_change=on_theme, text_style=ft.TextStyle(size=15, color=INK))

        async def submit(e):
            r = d["restaurant"]
            if not r:
                toast("請從清單選一家餐廳（飯局只能約在餐廳）")
                return
            if not d["pact"]:
                toast("請先勾選同意飯局公約")
                return
            starts = None
            if not radar:
                if not d["time"]:
                    toast("今天已經沒有可以選的時間，選明天吧")
                    return
                hh, mm = map(int, d["time"].split(":"))
                starts = (now + timedelta(days=d["day"])).replace(hour=hh, minute=mm, second=0, microsecond=0)
            ok, mid = await cloud_call(cloud.create_meetup(r.id, r.name, r.area, starts, d["capacity"],
                                                           d["theme"].strip(), radar, d["friends_only"]))
            if not ok:
                return
            await store.set_pact()
            toast(("只有好友看得到。" if d["friends_only"] else "")
                  + ("雷達丟出去了，1 小時內有效" if radar else "飯局開好了，等大家加入"))
            state["overlay"] = None
            state["tab"] = "meet"
            state["feed"] = None
            await load_meetups()
            render()

        head = ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.IconButton(icon=ft.Icons.CLOSE, icon_color=INK, tooltip="取消", on_click=lambda e: close_overlay()),
            ft.Container(expand=True, alignment=ft.Alignment.CENTER,
                         content=serif("現在就走" if radar else "開一個飯局", 18, height=1.2)),
            ft.Container(width=48),
        ])
        form = [caps("RADAR · 1 小時內有效，時間到自動消失" if radar else "MEETUP · 2～6 人"),
                ft.Column([section_label("WHERE", "去哪一家"), name_field, suggest_row], spacing=8)]
        if not radar:
            form.append(ft.Column([section_label("WHEN", "什麼時候"),
                                   ft.Row([chip(n, d["day"] == i, setter("day", i)) for i, n in enumerate(day_names)],
                                          spacing=8),
                                   ft.Row([chip(t, d["time"] == t, setter("time", t)) for t in valid_times],
                                          wrap=True, spacing=8, run_spacing=8)
                                   if valid_times else sans("今天已經沒有時段了，選明天吧。", 13, MUTED)], spacing=10))
        form.append(ft.Column([section_label("HOW MANY", "人數上限（含你）"),
                               ft.Row([chip(f"{n} 人", d["capacity"] == n, setter("capacity", n)) for n in range(2, 7)],
                                      wrap=True, spacing=8)], spacing=10))
        form.append(ft.Column([section_label("THEME", "一句話說明（可略過）"), theme_field], spacing=10))
        who = [section_label("WHO CAN SEE", "誰看得到"),
               ft.Row([chip("全校同學", not d["friends_only"], setter("friends_only", False)),
                       chip("只給好友", d["friends_only"], setter("friends_only", True))], spacing=8),
               sans("只給好友：不會出現在校園動態，只有你的好友看得到、加得進來。" if d["friends_only"] else
                    "全校同學都看得到，適合認識新朋友。", 12, MUTED, height=1.6)]
        if d["friends_only"] and state["friends"] is not None and not state["friends"]["list"]:
            who.append(ft.TextButton(content=sans("你還沒有好友，先去分享好友連結 →", 12, ACCENT), on_click=open_friends))
        form.append(ft.Column(who, spacing=10))
        form.append(ft.Container(
            bgcolor=CARD, border=hairline(ACCENT if d["pact"] else LINE), border_radius=16, padding=16,
            on_click=setter("pact", not d["pact"]),
            content=ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                ft.Icon(ft.Icons.CHECK_BOX if d["pact"] else ft.Icons.CHECK_BOX_OUTLINE_BLANK, size=20,
                        color=ACCENT if d["pact"] else MUTED),
                ft.Column(spacing=4, expand=True, controls=[sans("我同意飯局公約", 14, weight=ft.FontWeight.W_500),
                                                            sans(PACT, 12, MUTED, height=1.7)])])))
        form.append(ft.Row([pill("丟出雷達" if radar else "開團", submit, expand=True)]))
        return [ft.Container(padding=pad(8, 8, 8, 0), content=head),
                ft.Container(padding=pad(PAD, 8, PAD, 0), content=ft.Column(form, spacing=22))]

    # ==================== 社群：登入 ====================
    def login_screen(cw: int):
        """加入＝取暱稱。不需要信箱：第一次加入時在背景匿名登入，帳號跟著這支手機／這個瀏覽器。"""
        ov = state["overlay"]
        editing = ready()
        if editing and "name" not in ov:
            ov["name"], ov["dept"] = state["profile"]["display_name"], state["profile"].get("dept", "")

        def field(key, hint, max_length):
            def on_change(e):
                ov[key] = e.control.value or ""
            return ft.TextField(value=ov.get(key, ""), hint_text=hint, on_change=on_change, max_length=max_length,
                                border=ft.InputBorder.UNDERLINE, border_color=LINE, focused_border_color=INK,
                                cursor_color=ACCENT, text_style=ft.TextStyle(size=20, color=INK))

        async def join(e):
            name = (ov.get("name") or "").strip()
            if not name:
                toast("取一個暱稱吧")
                return
            if not cloud.logged_in:
                ok, _ = await cloud_call(cloud.sign_in_anonymously())
                if not ok:
                    return
            ok, prof = await cloud_call(cloud.setup_profile(name[:20], (ov.get("dept") or "").strip()[:20]))
            if ok and prof:
                state["profile"] = prof
                toast("暱稱改好了" if editing else f"歡迎加入，{prof['display_name']}！")
                await finish_login()

        head = ft.Row([ft.IconButton(icon=ft.Icons.CLOSE, icon_color=INK, tooltip="關閉", on_click=lambda e: close_overlay())])
        body = [caps("EDIT · 改暱稱" if editing else "JOIN · 加入餐桌"),
                serif("大家要怎麼稱呼你？", 28, weight=ft.FontWeight.W_600),
                sans("不用信箱、不用密碼，取個暱稱就能幫愛店助力、分享食記、找人一起吃飯。"
                     "暱稱和系所會顯示給其他使用者看，不想用本名也沒關係。", 14, BODY, height=1.8),
                field("name", "暱稱（20 字內）", 20), field("dept", "系所，例如：資工系（可略過）", 20),
                ft.Row([pill("儲存" if editing else "加入", join, expand=True)])]
        if not editing:
            body.append(sans("帳號會記在這支手機或這個瀏覽器裡；清除瀏覽器資料或換手機，就會變成新的帳號。"
                             "加入代表你同意：只在餐廳見面、尊重每一位飯友。", 11, MUTED, height=1.7))
        return [ft.Container(padding=pad(8, 8, 8, 0), content=head),
                ft.Container(padding=pad(PAD, 8, PAD, 0), content=ft.Column(body, spacing=20))]

    async def finish_login():
        state["overlay"] = None
        state["feed"] = state["meetups"] = state["board"] = state["friends"] = None
        render()
        await refresh_tab(state["tab"])
        render(keep_scroll=True)
        await accept_pending_friend()

    async def sign_out(e=None):
        cloud.sign_out()
        state["profile"] = None
        state["feed"] = state["meetups"] = state["board"] = None
        state["boosted"] = set()
        await save_session()
        toast("已登出")  # 匿名帳號登出後就回不來，所以介面上只在「刪除社群資料」時使用
        render()

    def confirm_delete_data(e=None):
        async def do_delete(ev):
            page.pop_dialog()
            ok, _ = await cloud_call(cloud.delete_my_data())
            if ok:
                await sign_out()
                toast("你的社群資料都刪除了")

        page.show_dialog(ft.AlertDialog(
            bgcolor=BG, title=serif("刪除我的社群資料？", 20),
            content=sans("會刪除你的個人資料、助力、分享的食記、飯局與同感。手機裡的飯紀錄不受影響。刪除後無法復原。",
                         14, BODY, height=1.8),
            actions=[ft.TextButton(content="刪除", on_click=do_delete),
                     ft.TextButton(content="取消", on_click=lambda ev: page.pop_dialog())],
        ))

    # ==================== 社群：趣味測驗 ====================
    def fun_screen(cw: int):
        ov = state["overlay"]
        answers = ov.setdefault("answers", [])
        if len(answers) < len(QUIZ):
            i = len(answers)
            question, options = QUIZ[i]

            def back(e):
                if answers:
                    answers.pop()
                    render()
                else:
                    close_overlay()

            def pick(j):
                def handler(e):
                    answers.append(j)
                    render()
                return handler

            head = ft.Column(spacing=14, controls=[
                ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW, icon_color=INK, icon_size=20, tooltip="上一題", on_click=back),
                    ft.Container(expand=True), caps(f"QUESTION {i + 1:02d} / {len(QUIZ):02d}"),
                    ft.IconButton(icon=ft.Icons.CLOSE, icon_color=INK, icon_size=20, tooltip="離開",
                                  on_click=lambda e: close_overlay())]),
                ft.Container(padding=pad(PAD - 8, 0, PAD - 8, 0),
                             content=ft.ProgressBar(value=(i + 1) / len(QUIZ), color=INK, bgcolor=LINE, bar_height=2)),
            ])
            body = ft.Container(padding=pad(PAD, 18, PAD, 0), content=ft.Column(spacing=0, controls=[
                caps("吃貨派別測驗 · 沒有標準答案"), ft.Container(height=8),
                serif(question, 26, weight=ft.FontWeight.W_600, height=1.4), ft.Container(height=18),
                *[option_row(label, "", False, pick(j)) for j, (label, _) in enumerate(options)],
            ]))
            return [ft.Container(padding=pad(8, 8, 8, 0), content=head), body]

        tribe, title, quip = score_quiz(answers)

        async def use_title(e):
            if not ready():
                open_overlay("login")
                return
            ok, prof = await cloud_call(cloud.set_title(title, tribe))
            if ok and prof:
                state["profile"] = prof
                state["feed"] = None
                toast("稱號設定好了，飯局裡大家會看到")

        async def save_card(e):
            if not HAS_PILLOW:
                toast("需要 Pillow 套件才能存成圖片")
                return
            await ensure_serif_font()
            await save_png(render_title_card(title, quip), f"席間_{title}.png")

        body = [caps("YOUR TABLE TYPE · 你的吃貨派別"), serif(title, 34, ACCENT, ft.FontWeight.W_600, height=1.3),
                sans(quip, 16, BODY, height=1.9),
                ft.Row([pill("設為我的稱號", use_title, expand=True)]),
                ft.Row([pill("存成圖片", save_card, filled=False, expand=True),
                        link_button("發到 Threads", threads_url(f"我在 Table 席間測出來是「{title}」。{quip}"),
                                    filled=False, expand=True)], spacing=10),
                ft.Row([ft.TextButton(content=sans("再測一次", 13, MUTED), on_click=lambda e: (answers.clear(), render()))]),
                sans("這是好玩的測驗，不代表任何評價。稱號只會顯示你的派別，不會顯示你選了什麼。", 11, MUTED, height=1.7)]
        return [ft.Container(padding=pad(8, 8, 8, 0), content=ft.Row([
                    ft.IconButton(icon=ft.Icons.CLOSE, icon_color=INK, tooltip="關閉", on_click=lambda e: close_overlay())])),
                ft.Container(padding=pad(PAD, 8, PAD, 0), content=ft.Column(body, spacing=20))]

    # ==================== 社群：好友 ====================
    def friend_link(code: str) -> str:
        """好友連結：朋友打開就會成為好友。網址的 # 後面是 App 裡的頁面（GitHub Pages 用 hash 路由）。"""
        return f"{(SITE_URL or '').rstrip('/')}/#/friend/{code}"

    def friend_code_in(route: str | None) -> str | None:
        m = re.search(r"friend/([A-Za-z0-9]{4,12})", route or "")
        return m.group(1).upper() if m else None

    async def load_friends():
        if not ready():
            return
        f = {"code": "", "list": [], "requests": []}
        ok, code = await cloud_call(cloud.my_friend_code(), quiet=True)
        f["code"] = code if ok else ""
        ok, rows = await cloud_call(cloud.my_friends(), quiet=True)
        f["list"] = rows if ok else []
        ok, rows = await cloud_call(cloud.friend_requests(), quiet=True)
        f["requests"] = rows if ok else []
        state["friends"] = f

    def friend_ids() -> set:
        return {x["user_id"] for x in (state["friends"] or {}).get("list", [])}

    async def accept_pending_friend():
        """有人用好友連結打開 App：加入後自動成為好友。"""
        code = state["pending_friend"]
        if not code or not cloud.enabled:
            return
        if not ready():
            if not (state["overlay"] and state["overlay"]["kind"] == "login"):
                open_overlay("login")
            toast("先取個暱稱加入，就會自動和朋友成為好友")
            return
        state["pending_friend"] = None
        ok, res = await cloud_call(cloud.add_friend_by_code(code))
        if ok:
            added, info = res
            toast(f"你和 {info} 成為好友了！之後可以開只給好友看的飯局" if added else info)
            state["friends"] = state["meetups"] = None
            await refresh_tab(state["tab"])
            render(keep_scroll=True)

    async def open_friends(e=None):
        open_overlay("friends")
        await load_friends()
        if state["overlay"] and state["overlay"]["kind"] == "friends":
            render(keep_scroll=True)

    async def copy_text(text: str):
        try:
            await ft.Clipboard().set(text)
        except Exception:
            try:
                page.set_clipboard(text)
            except Exception:
                toast("長按上面的連結就能複製")
                return
        toast("連結已複製，貼給朋友就好")

    def friends_screen(cw: int):
        f = state["friends"]
        back = ft.Row([ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW, icon_color=INK, icon_size=20, tooltip="返回",
                                     on_click=lambda e: close_overlay())])
        body = [caps("FRIENDS · 只跟熟人吃"), serif("好友", 30, weight=ft.FontWeight.W_600, height=1.2),
                sans("開飯局時可以選「只給好友看」，只有好友看得到、加得進來。"
                     "把你的好友連結傳給朋友，對方打開就會成為好友；見面時也可以讓對方用手機相機掃 QR code。",
                     14, BODY, height=1.8)]
        if f is None:
            body.append(sans("載入中…", 13, MUTED))
        else:
            if f["code"]:
                link = friend_link(f["code"])

                async def copy(e):
                    await copy_text(link)

                share_text = f"加我好友，一起用 Table 席間約吃飯：{link}"
                body.append(ft.Container(
                    **GLASS_KW, border_radius=22, padding=20,
                    content=ft.Column(spacing=14, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                        caps("MY FRIEND LINK · 我的好友連結"),
                        ft.Image(src=qr_png(link, scale=6), width=200, height=200),
                        ft.Text(link, size=12, color=MUTED, selectable=True, text_align=ft.TextAlign.CENTER),
                        ft.Row([pill("複製連結", copy, filled=False, expand=True),
                                link_button("用 LINE 傳", "https://line.me/R/share?text=" + urllib.parse.quote(share_text),
                                            expand=True)], spacing=10),
                    ])))
            if f["requests"]:
                rows = []
                for q in f["requests"]:
                    def answer(uid, accept):
                        async def handler(e):
                            ok, _ = await cloud_call(cloud.respond_friend(uid, accept))
                            if ok:
                                toast("成為好友了！" if accept else "已略過")
                                await load_friends()
                                render(keep_scroll=True)
                        return handler
                    rows.append(ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                        avatar((q["display_name"] or "?")[:1], 32),
                        ft.Column(spacing=1, expand=True, controls=[sans(q["display_name"], 14, weight=ft.FontWeight.W_500),
                                                                    sans(q.get("dept") or "一起吃過飯局", 11, MUTED)]),
                        pill("接受", answer(q["user_id"], True), accent=True),
                        ft.TextButton(content=sans("略過", 12, MUTED), on_click=answer(q["user_id"], False))]))
                body.append(ft.Column([section_label("REQUESTS", f"{len(f['requests'])} 個好友邀請"), *rows], spacing=10))
            rows = []
            for x in f["list"]:
                def remove(uid, name):
                    async def handler(e):
                        ok, _ = await cloud_call(cloud.remove_friend(uid))
                        if ok:
                            toast(f"已和 {name} 解除好友")
                            await load_friends()
                            render(keep_scroll=True)
                    return handler
                sub = " · ".join(v for v in [x.get("dept", ""), x.get("title", "")] if v)
                rows.append(ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    avatar((x["display_name"] or "?")[:1], 32),
                    ft.Column(spacing=1, expand=True, controls=[sans(x["display_name"], 14, weight=ft.FontWeight.W_500),
                                                                sans(sub, 11, MUTED)]),
                    ft.TextButton(content=sans("解除", 12, MUTED), on_click=remove(x["user_id"], x["display_name"]))]))
            body.append(ft.Column([section_label("FRIENDS", f"{len(f['list'])} 位好友"),
                                   *(rows or [sans("還沒有好友。把上面的連結傳給一起吃飯的朋友吧。", 13, MUTED)])],
                                  spacing=10))
            body.append(sans("好友跟著這支手機的帳號；清除瀏覽紀錄或換手機會看不到原本的好友。"
                             "一起吃過公開飯局的人，也可以在飯局頁按「加好友」，對方同意才會成立。", 11, MUTED, height=1.7))
        return [ft.Container(padding=pad(8, 8, 8, 0), content=back),
                ft.Container(padding=pad(PAD, 4, PAD, 0), content=ft.Column(body, spacing=20))]

    def profile_card():
        if not ready():
            return login_card("加入台大的餐桌", "加入後可以幫愛店助力、看大家今天吃什麼、找人一起吃飯。")
        p = state["profile"]
        info = [serif(p["display_name"], 24, weight=ft.FontWeight.W_600, height=1.2)]
        if p.get("dept"):
            info.append(caps(p["dept"]))
        if p.get("title"):
            info.append(sans(f"「{p['title']}」", 13, ACCENT))
        return ft.Column(spacing=10, controls=[
            ft.Row(spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                avatar(p["display_name"][:1], 56, "#E8E1D6"), ft.Column(info, spacing=4, expand=True)]),
            ft.Row(spacing=0, wrap=True, controls=[
                ft.TextButton(content=sans("好友", 13, INK), on_click=open_friends),
                ft.TextButton(content=sans("吃貨派別測驗", 13, INK), on_click=lambda e: open_overlay("fun")),
                ft.TextButton(content=sans("改暱稱", 13, MUTED), on_click=lambda e: open_overlay("login")),
                ft.TextButton(content=sans("刪除我的社群資料", 13, MUTED), on_click=confirm_delete_data)]),
        ])

    # ==================== 社群：排行榜（探索頁） ====================
    def leaderboard_section():
        def set_days(days):
            async def handler(e):
                state["board_days"], state["board"] = days, None
                render(keep_scroll=True)
                await load_board()
                render(keep_scroll=True)
            return handler

        head = ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12,
                      controls=[section_label("RANKING", "愛店排行榜"),
                                ft.Container(expand=True, height=1, bgcolor=LINE),
                                ft.Row([chip("本週", state["board_days"] == 7, set_days(7)),
                                        chip("總榜", state["board_days"] == 0, set_days(0))], spacing=6)])
        out = [head]
        if not ready():
            out.append(login_card("幫愛店衝上排行榜", "每天可以幫每家店助力一次，看看台大人這週最愛哪家。"))
            return out
        rows = state["board"]
        if rows is None:
            out.append(sans("載入中…", 13, MUTED))
        elif not rows:
            out.append(sans("這段時間還沒有人助力。從下面挑一家你喜歡的店，當第一個吧。", 13, MUTED, height=1.7))
        for i, row in enumerate(rows or []):
            r = by_id.get(row["restaurant_id"])
            out.append(ft.Container(
                **GLASS_KW, border_radius=34, padding=pad(18, 12, 10, 12),
                on_click=(lambda e, r=r: open_overlay("place", restaurant=r)) if r else None,
                content=ft.Row(spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Container(width=40, content=ft.Text(f"{i + 1:02d}", size=30, color=MUTED, italic=True,
                                                           font_family=serif_family)),
                    ft.Container(width=1, height=44, bgcolor=LINE),
                    thumb(row["restaurant_id"], row["restaurant_name"], 64),
                    ft.Column(spacing=4, expand=True, controls=[
                        serif(row["restaurant_name"], 18, max_lines=1, height=1.3),
                        sans(f"{row.get('area', '')} · {row['boosters']} 人助力", 11, MUTED, spacing=0.3)]),
                    boost_button(row["restaurant_id"], row["restaurant_name"], row.get("area", "")),
                ])))
        return out

    # ==================== 導覽列與畫面切換 ====================
    def switch_tab(tab: str):
        state["tab"], state["overlay"] = tab, None
        render()

    def tab_handler(tab: str):
        async def handler(e):
            await go_tab(tab)
        return handler

    def open_overlay(kind: str, **kw):
        state["overlay"] = {"kind": kind, **kw}
        if kind == "record" and kw.get("name"):
            state["overlay"]["draft"] = {"name": kw["name"], "restaurant": None, "photo": None, "tags": set(),
                                         "note": "", "price": "", "party": 1, "walk": 0, "surprise": False}
        if kind == "quiz" and "step" not in kw:
            state["step"] = state.get("step") or 1
        render()

    def close_overlay():
        state["overlay"] = None
        render()

    NAV = [("feed", "動態", ft.Icons.VIEW_AGENDA_OUTLINED, ft.Icons.VIEW_AGENDA),
           ("explore", "探索", ft.Icons.EXPLORE_OUTLINED, ft.Icons.EXPLORE),
           None,
           ("meet", "飯局", ft.Icons.GROUPS_OUTLINED, ft.Icons.GROUPS),
           ("journal", "我的", ft.Icons.PERSON_OUTLINE, ft.Icons.PERSON)]

    def nav_item(item):
        if item is None:
            return ft.Container(expand=True)
        key, label, icon, icon_on = item
        on = state["tab"] == key
        return ft.Container(
            expand=True, height=64, on_click=tab_handler(key), alignment=ft.Alignment.CENTER,
            content=ft.Column(spacing=3, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(icon_on if on else icon, size=21, color=INK if on else MUTED),
                sans(label, 10, INK if on else MUTED, ft.FontWeight.W_500 if on else None, spacing=0.6)]),
        )

    def glass(content, height=64, padding=None):
        return ft.Container(
            height=height, border_radius=height / 2, bgcolor=ft.Colors.with_opacity(0.62, "#FFFFFF"),
            blur=ft.Blur(22, 22), border=border_all(1, ft.Colors.with_opacity(0.95, "#FFFFFF")), padding=padding,
            shadow=ft.BoxShadow(blur_radius=30, color=ft.Colors.with_opacity(0.08, INK), offset=ft.Offset(0, 10)),
            content=content,
        )

    body_list = ft.ListView(spacing=0, padding=pad(0, 0, 0, 130))
    current_key = {"value": None}
    frame = ft.Container(width=content_width())

    def screen_key() -> tuple:
        ov = state["overlay"]
        if ov:
            return ("overlay", ov["kind"], id(ov.get("post")), id(ov.get("restaurant")), state["step"],
                    ov.get("meetup_id"), ov.get("step"), len(ov.get("answers", [])))
        return ("tab", state["tab"])

    def backdrop(cw: int):
        """奶茶色漸層＋兩道淡淡的弧線，讓毛玻璃有東西可以透。"""
        return [
            ft.Container(left=0, top=0, right=0, bottom=0, gradient=ft.LinearGradient(
                begin=ft.Alignment(-1, -1), end=ft.Alignment(1, 1), colors=[BG_TOP, BG, BG_BOTTOM])),
            ft.Container(left=-cw * 0.45, top=-cw * 0.55, width=cw * 1.1, height=cw * 1.1, border_radius=cw * 0.55,
                         bgcolor=ft.Colors.with_opacity(0.35, "#FFFFFF"),
                         border=border_all(1, ft.Colors.with_opacity(0.6, "#FFFFFF"))),
            ft.Container(right=-cw * 0.6, bottom=cw * 0.15, width=cw * 1.2, height=cw * 1.2, border_radius=cw * 0.6,
                         border=border_all(1, ft.Colors.with_opacity(0.55, "#FFFFFF"))),
        ]

    def render(keep_scroll: bool = False):
        nonlocal body_list
        cw = content_width()
        frame.width = cw
        ov = state["overlay"]
        if ov:
            kind = ov["kind"]
            screens = {"post": detail_screen, "record": record_screen, "place": place_screen, "quiz": quiz_screen,
                       "login": login_screen, "fun": fun_screen, "meetup": meetup_screen, "newmeet": newmeet_screen,
                       "friends": friends_screen}
            controls = screens[kind](cw)
        else:
            tab = state["tab"]
            controls = (feed_screen(cw) if tab == "feed" else explore_screen(cw) if tab == "explore"
                        else meet_screen(cw) if tab == "meet" else journal_screen(cw))

        key = screen_key()
        if not (keep_scroll and key == current_key["value"]):
            body_list = ft.ListView(spacing=0, padding=pad(0, 0, 0, 130))      # 換頁：從最上面開始
        current_key["value"] = key
        body_list.controls = controls

        layers = [*backdrop(cw), ft.Container(left=0, top=0, right=0, bottom=0, content=body_list)]
        if ov and ov["kind"] == "post":
            layers.append(ft.Container(left=PAD, right=PAD, bottom=22,
                                       content=glass(detail_bar(ov["post"]), padding=pad(0, 0, 8, 0))))
        elif ov and ov["kind"] == "place":
            layers.append(ft.Container(left=PAD, right=PAD, bottom=22,
                                       content=glass(ft.Container(padding=pad(0, 0, 8, 0), content=place_bar(ov["restaurant"])))))
        elif not ov:
            layers.append(ft.Container(left=PAD, right=PAD, bottom=22,
                                       content=glass(ft.Row([nav_item(i) for i in NAV], spacing=0))))
            layers.append(ft.Container(
                left=(cw - 64) / 2, bottom=22 + 22, width=64, height=64, border_radius=32,
                gradient=ft.LinearGradient(begin=ft.Alignment(-1, -1), end=ft.Alignment(1, 1), colors=[OLIVE, OLIVE_DARK]),
                border=border_all(4, ft.Colors.with_opacity(0.85, "#FFFFFF")),
                shadow=ft.BoxShadow(blur_radius=22, color=ft.Colors.with_opacity(0.30, OLIVE_DARK), offset=ft.Offset(0, 8)),
                alignment=ft.Alignment.CENTER, tooltip="記錄這一餐", ink=True,
                on_click=lambda e: open_overlay("record"),
                content=ft.Icon(ft.Icons.ADD, size=28, color=ON_OLIVE),
            ))
        frame.content = ft.Stack(layers)
        page.update()

    def on_resize(e):
        render(keep_scroll=True)

    try:
        page.on_resize = on_resize
    except Exception:
        pass

    page.add(ft.SafeArea(
        expand=True,
        content=ft.Row(expand=True, spacing=0, alignment=ft.MainAxisAlignment.CENTER,
                       vertical_alignment=ft.CrossAxisAlignment.STRETCH, controls=[frame]),
    ))
    async def on_route_change(e=None):
        code = friend_code_in(getattr(page, "route", ""))
        if code:
            state["pending_friend"] = code
            await accept_pending_friend()

    try:
        page.on_route_change = on_route_change
    except Exception:
        pass
    state["pending_friend"] = friend_code_in(getattr(page, "route", ""))     # 用好友連結打開的

    render()
    if cloud.enabled and cloud.logged_in:                  # 上次登入過：自動接上
        ok, prof = await cloud_call(cloud.me(), quiet=True)
        state["profile"] = prof if ok else None
        if state["profile"]:
            await refresh_tab(state["tab"])
        render(keep_scroll=True)
    await accept_pending_friend()


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
