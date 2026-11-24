"""每月回顧圖：產生 IG 限動尺寸（1080×1920）的「數據卡」與「飯 Dump」。

風格跟 App 一樣是「席間」的雜誌感：亞麻白底、深炭灰字、細線分隔、
店名用襯線字，唯一的顏色是陶土紅。純 Python ＋ Pillow，手機、網頁、電腦都能跑。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 1080, 1920

LINEN = (248, 246, 241)     # 背景
PAPER = (255, 255, 255)
LINE = (234, 230, 223)      # 細線
INK = (28, 27, 24)
BODY = (58, 56, 51)
MUTED = (110, 107, 100)
ACCENT = (184, 93, 67)      # 陶土紅
EMPTY = (239, 233, 223)     # 沒照片時的底色

HERE = Path(__file__).resolve().parent.parent
FONTS_DIR = HERE / "assets" / "fonts"
# 網頁版的 Python 在瀏覽器裡跑，讀不到 assets/。
# 宋體約 8 MB，不打包進 Python 程式包（會拖慢第一次開網頁）：
# 要產生回顧圖時才用 ensure_serif_font() 從網站的 fonts/ 下載到瀏覽器裡的暫存區。
# Logo 字體很小，仍然複製一份到 core/fonts/（get_font.py 會做）。
PACKAGE_FONTS = Path(__file__).resolve().parent / "fonts"
SERIF_NAME = "NotoSerifTC-Medium.otf"
WEB_SERIF_URL = "fonts/" + SERIF_NAME          # 相對網址：跟著網站所在位置走（例如 /table-app/）
WEB_SERIF_CACHE = Path("/tmp/table-fonts") / SERIF_NAME
SERIF_CANDIDATES = [
    (FONTS_DIR / SERIF_NAME, 0),                # 電腦版：讀本機檔案
    (WEB_SERIF_CACHE, 0),                       # 網頁版：ensure_serif_font() 下載後放這裡
    (Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Medium.ttc"), 3),    # Linux（TC）
    (Path("/System/Library/Fonts/Supplemental/Songti.ttc"), 0),              # macOS 宋體
    (Path("C:/Windows/Fonts/mingliu.ttc"), 0),                               # Windows 細明體
]
SANS_CANDIDATES = [
    (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 3),
    (Path("/System/Library/Fonts/PingFang.ttc"), 0),
    (Path("/System/Library/Fonts/STHeiti Medium.ttc"), 0),
    (Path("C:/Windows/Fonts/msjh.ttc"), 0),
]
LOGO_CANDIDATES = [
    (PACKAGE_FONTS / "Logo-Italic.ttf", 0),
    (FONTS_DIR / "Logo-Italic.ttf", 0),
    (Path("/usr/share/fonts/truetype/google-fonts/Lora-Italic-Variable.ttf"), 0),
    (Path("/System/Library/Fonts/Supplemental/Georgia Italic.ttf"), 0),
    (Path("C:/Windows/Fonts/georgiai.ttf"), 0),
]


def _is_web() -> bool:
    return sys.platform == "emscripten"


_web_serif_failed = False


def serif_ready() -> bool:
    """回顧圖用的宋體是否已經就緒（或不需要再等）。電腦版永遠是 True。"""
    return not _is_web() or _web_serif_failed or WEB_SERIF_CACHE.exists()


async def ensure_serif_font() -> bool:
    """網頁版：第一次產生回顧圖前，從網站下載宋體。失敗就用預設字體，不再重試。"""
    global _web_serif_failed
    if not _is_web() or WEB_SERIF_CACHE.exists():
        return True
    if _web_serif_failed:
        return False
    try:
        from pyodide.http import pyfetch
        resp = await pyfetch(WEB_SERIF_URL)
        if not resp.ok:
            raise OSError(f"HTTP {resp.status}")
        data = await resp.bytes()
        WEB_SERIF_CACHE.parent.mkdir(parents=True, exist_ok=True)
        WEB_SERIF_CACHE.write_bytes(data)
        return True
    except Exception:
        _web_serif_failed = True
        return False


class Fonts:
    """一組字體：serif（店名、大標）、sans（內文、小標）、logo（Table 斜體）。

    為了相容舊的呼叫方式，直接呼叫 fonts(size) 會回傳 sans。
    """

    def __init__(self, path: str | Path | None = None, index: int = 0):
        self._paths = {
            "serif": self._first(SERIF_CANDIDATES),
            "sans": (Path(path), index) if path else self._first(SANS_CANDIDATES),
            "logo": self._first(LOGO_CANDIDATES),
        }
        if self._paths["serif"] is None:
            self._paths["serif"] = self._paths["sans"]
        if self._paths["sans"] is None:              # 網頁版沒有系統中文字體：內文也用宋體
            self._paths["sans"] = self._paths["serif"]
        if self._paths["logo"] is None:
            self._paths["logo"] = self._paths["serif"]
        self._cache: dict[tuple, ImageFont.FreeTypeFont] = {}

    @staticmethod
    def _first(candidates):
        for p, i in candidates:
            if p.exists():
                return p, i
        return None

    def get(self, kind: str, size: int):
        key = (kind, size)
        if key not in self._cache:
            found = self._paths.get(kind)
            if found:
                self._cache[key] = ImageFont.truetype(str(found[0]), size, index=found[1])
            else:
                self._cache[key] = ImageFont.load_default(size=size)
        return self._cache[key]

    def __call__(self, size: int):
        return self.get("sans", size)

    def serif(self, size: int):
        return self.get("serif", size)

    def logo(self, size: int):
        return self.get("logo", size)


# ---------- 小工具 ----------
def _spaced(draw, xy, text, font, fill=MUTED, spacing=6, anchor="ls"):
    """英文小標：拉開字距。anchor 只支援 ls（左基線）或 rs（右基線）。"""
    x, y = xy
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    if anchor == "rs":
        x -= total
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill, anchor="ls")
        x += w + spacing
    return total


def _fit(draw, text: str, font_fn, max_w: int, size: int, min_size: int = 24):
    """太長就縮小字；縮到最小還放不下就截斷加「…」。"""
    while size > min_size and draw.textlength(text, font=font_fn(size)) > max_w:
        size -= 2
    font = font_fn(size)
    if draw.textlength(text, font=font) <= max_w:
        return text, font
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…", font


def _dotted(draw, x1, x2, y, color=(207, 201, 191), step=12):
    x = x1
    while x < x2:
        draw.ellipse((x, y - 1.5, x + 3, y + 1.5), fill=color)
        x += step


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=radius, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


MONTH_EN = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
PAD = 80


def _masthead(d, fonts: Fonts, year: int, month: int, kicker: str):
    """頁首：Table 席間 ＋ 月份，下面一條細線。"""
    d.text((PAD, 170), "Table", font=fonts.logo(78), fill=INK, anchor="ls")
    lw = d.textlength("Table", font=fonts.logo(78))
    _spaced(d, (PAD + lw + 22, 166), "席間", fonts.serif(32), MUTED, spacing=12)
    _spaced(d, (W - PAD, 166), f"{MONTH_EN[month - 1]} {year}", fonts(28), MUTED, spacing=5, anchor="rs")
    d.line((PAD, 214, W - PAD, 214), fill=LINE, width=2)
    _spaced(d, (PAD, 286), kicker, fonts(26), MUTED, spacing=6)


def _footer(d, fonts: Fonts):
    d.line((PAD, H - 110, W - PAD, H - 110), fill=LINE, width=2)
    _spaced(d, (PAD, H - 56), "TABLE · 席間", fonts(24), MUTED, spacing=5)
    _spaced(d, (W - PAD, H - 56), "NTU · 台大附近", fonts(24), MUTED, spacing=4, anchor="rs")


# ---------- 數據卡 ----------
def render_stats_card(stats: dict, fonts: Fonts | None = None) -> bytes:
    fonts = fonts or Fonts()
    y_, m_ = stats["year"], stats["month"]
    img = Image.new("RGBA", (W, H), LINEN + (255,))
    d = ImageDraw.Draw(img)
    _masthead(d, fonts, y_, m_, "MONTHLY TABLE · 每月餐桌")
    d.text((PAD, 380), f"{m_} 月，你的餐桌", font=fonts.serif(76), fill=INK, anchor="ls")

    if stats["meals"] == 0:
        d.text((W / 2, H / 2), "這個月還沒有紀錄", font=fonts.serif(52), fill=MUTED, anchor="mm")
        d.text((W / 2, H / 2 + 80), "記下一餐，月底就會長出這張卡", font=fonts(36), fill=MUTED, anchor="mm")
        _footer(d, fonts)
        return _to_png(img)

    # 主數字：吃了幾餐
    num = str(stats["meals"])
    num_font = fonts.serif(280)
    d.text((PAD - 8, 690), num, font=num_font, fill=ACCENT, anchor="ls")
    nx = PAD + d.textlength(num, font=num_font) + 16
    d.text((nx, 690), "餐", font=fonts.serif(84), fill=INK, anchor="ls")
    d.text((PAD, 770), f"去了 {stats['places']} 家不同的店，記錄了 {stats['days_logged']} 天。",
           font=fonts(38), fill=BODY, anchor="ls")

    # 2×2 數據格，只用細線分隔
    top, cell_h = 840, 236
    half = (W - PAD * 2) // 2
    d.line((PAD, top, W - PAD, top), fill=LINE, width=2)
    d.line((PAD, top + cell_h, W - PAD, top + cell_h), fill=LINE, width=2)
    d.line((PAD, top + cell_h * 2, W - PAD, top + cell_h * 2), fill=LINE, width=2)
    d.line((PAD + half, top, PAD + half, top + cell_h * 2), fill=LINE, width=2)

    def cell(col, row, label, big, small):
        x = PAD + col * half + (0 if col == 0 else 40)
        y = top + row * cell_h
        _spaced(d, (x, y + 70), label, fonts(24), MUTED, spacing=5)
        text, font = _fit(d, big, fonts.serif, half - 60, 62, 34)
        d.text((x, y + 160), text, font=font, fill=INK, anchor="ls")
        if small:
            d.text((x, y + 212), small, font=fonts(30), fill=MUTED, anchor="ls")

    area = stats["top_area"] or "—"
    cell(0, 0, "FAVORITE · 最常去", stats["favorite_name"] or "—", f"去了 {stats['favorite_count']} 次")
    cell(1, 0, "AREA · 你是", f"{area}派" if stats["top_area"] else "—",
         f"{stats['top_area_share']}% 的飯在這裡" if stats["top_area"] else "")
    cell(0, 1, "WALKED · 為了吃走了", f"{stats['km']} km", "來回步行距離")
    late = stats["late_night"]
    cell(1, 1, "AFTER 9PM · 深夜", f"{late} 餐", f"驚喜一下 {stats['surprises']} 次")

    # 本月菜單：前三名
    y = top + cell_h * 2 + 100
    _spaced(d, (PAD, y), "THIS MONTH'S MENU · 本月前三", fonts(26), MUTED, spacing=6)
    y += 90
    for i, (name, count) in enumerate(stats["top3"]):
        d.text((PAD, y), f"0{i + 1}", font=fonts(30), fill=MUTED, anchor="ls")
        name_text, name_font = _fit(d, name, fonts.serif, W - PAD * 2 - 280, 46, 30)
        d.text((PAD + 70, y), name_text, font=name_font, fill=INK, anchor="ls")
        end = PAD + 70 + d.textlength(name_text, font=name_font) + 24
        count_text = f"{count} 次"
        cw = d.textlength(count_text, font=fonts(32))
        _dotted(d, end, W - PAD - cw - 24, y - 10)
        d.text((W - PAD, y), count_text, font=fonts(32), fill=MUTED, anchor="rs")
        y += 90

    if stats["busiest_weekday"]:
        d.text((PAD, H - 160), f"最常在{stats['busiest_weekday']}好好吃一頓。", font=fonts.serif(34), fill=BODY, anchor="ls")
    _footer(d, fonts)
    return _to_png(img)


# ---------- 飯 Dump ----------
def _photo(data: bytes, size: tuple[int, int]) -> Image.Image:
    photo = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    return ImageOps.fit(photo, size, Image.Resampling.LANCZOS)


def _placeholder(fonts: Fonts, name: str, size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, EMPTY)
    ImageDraw.Draw(img).text((size[0] / 2, size[1] / 2), name[:1] or "?", font=fonts.serif(120),
                             fill=MUTED, anchor="mm")
    return img


def render_photo_dump(entries, photos: dict[str, bytes], year: int, month: int,
                      fonts: Fonts | None = None) -> bytes:
    """entries：這個月的 MealEntry；photos：{entry.id: 照片 bytes}。有照片的優先，最多 9 張。"""
    fonts = fonts or Fonts()
    img = Image.new("RGBA", (W, H), LINEN + (255,))
    d = ImageDraw.Draw(img)
    _masthead(d, fonts, year, month, "PHOTO DUMP · 飯 DUMP")
    with_photo = [e for e in entries if e.id in photos]
    d.text((PAD, 380), f"{month} 月的餐桌", font=fonts.serif(76), fill=INK, anchor="ls")
    if entries:
        counts: dict[str, int] = {}
        for e in entries:
            counts[e.name] = counts.get(e.name, 0) + 1
        fav, cnt = max(counts.items(), key=lambda kv: kv[1])
        left = f"{len(entries)} 餐 · {len(with_photo)} 張照片 · 最常出現 "
        d.text((PAD, 446), left, font=fonts(30), fill=MUTED, anchor="ls")
        lx = PAD + d.textlength(left, font=fonts(30))
        fav_text, fav_font = _fit(d, fav, fonts.serif, W - PAD - lx - 90, 32, 24)
        d.text((lx, 446), fav_text, font=fav_font, fill=INK, anchor="ls")
        fx = lx + d.textlength(fav_text, font=fav_font) + 10
        d.text((fx, 446), f"× {cnt}", font=fonts(30), fill=ACCENT, anchor="ls")

    if not entries:
        d.text((W / 2, H / 2), "這個月還沒有紀錄", font=fonts.serif(52), fill=MUTED, anchor="mm")
        _footer(d, fonts)
        return _to_png(img)

    picks = (with_photo + [e for e in entries if e.id not in photos])[:9]
    picks.sort(key=lambda e: e.at)
    gap = 20
    cw = (W - PAD * 2 - gap * 2) // 3          # 4:5 直式照片
    ch = cw * 5 // 4
    row_h = ch + 58
    top = 486
    for i, e in enumerate(picks):
        r, c = divmod(i, 3)
        x, y = PAD + c * (cw + gap), top + r * row_h
        pic = _photo(photos[e.id], (cw, ch)) if e.id in photos else _placeholder(fonts, e.name, (cw, ch))
        img.alpha_composite(_rounded(pic, 18), (x, y))
        name_text, name_font = _fit(d, e.name, fonts.serif, cw - 70, 26, 20)
        d.text((x + 2, y + ch + 38), name_text, font=name_font, fill=INK, anchor="ls")
        d.text((x + cw, y + ch + 38), f"{e.when.month}/{e.when.day}", font=fonts(22), fill=MUTED, anchor="rs")

    _footer(d, fonts)
    return _to_png(img)


# ---------- 吃貨派別稱號卡 ----------
def render_title_card(title: str, quip: str, fonts: Fonts | None = None) -> bytes:
    """趣味測驗結果，IG 限動尺寸。"""
    fonts = fonts or Fonts()
    img = Image.new("RGBA", (W, H), LINEN + (255,))
    d = ImageDraw.Draw(img)
    d.text((PAD, 170), "Table", font=fonts.logo(78), fill=INK, anchor="ls")
    lw = d.textlength("Table", font=fonts.logo(78))
    _spaced(d, (PAD + lw + 22, 166), "席間", fonts.serif(32), MUTED, spacing=12)
    d.line((PAD, 214, W - PAD, 214), fill=LINE, width=2)
    _spaced(d, (PAD, 640), "YOUR TABLE TYPE · 我的吃貨派別", fonts(28), MUTED, spacing=6)
    y = 780
    text, font = _fit(d, title, fonts.serif, W - PAD * 2, 104, 56)
    d.text((PAD, y), text, font=font, fill=ACCENT, anchor="ls")
    y += 110
    line, lines = "", []
    for ch in quip:                                    # 中文逐字換行
        if d.textlength(line + ch, font=fonts(44)) > W - PAD * 2:
            lines.append(line)
            line = ""
        line += ch
    lines.append(line)
    for ln in lines[:4]:
        d.text((PAD, y), ln, font=fonts(44), fill=BODY, anchor="ls")
        y += 74
    d.text((PAD, H - 200), "這是好玩的測驗，不代表任何評價。", font=fonts(30), fill=MUTED, anchor="ls")
    _footer(d, fonts)
    return _to_png(img)


def make_thumbnail(data: bytes, max_side: int = 640, quality: int = 78) -> bytes:
    """把使用者的照片縮小成 JPEG，存在手機或瀏覽器裡不占空間（約 40～80 KB）。"""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()
