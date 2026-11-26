"""產生 QR code（純 Python，不需要額外安裝套件，網頁版也能用）。

只做 App 需要的部分：位元組模式、錯誤修正等級 M、版本 1～10（最多約 210 個字元，
好友連結大約 60 個字元，綽綽有餘）。演算法照 ISO/IEC 18004 標準。

    from core.qr import qr_matrix, qr_png
    png = qr_png("https://example.com/#/friend/AB12CD34")   # 給 ft.Image(src=png)
"""
from __future__ import annotations

import io

# 版本 1～10、等級 M：每個區塊的錯誤修正碼數、區塊數
_ECC_PER_BLOCK = [None, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
_NUM_BLOCKS = [None, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
_FORMAT_M = 0          # 等級 M 的格式代碼


def _raw_modules(ver: int) -> int:
    """這個版本可以放資料（含錯誤修正）的格子數。"""
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        align = ver // 7 + 2
        n -= (25 * align - 10) * align - 55
        if ver >= 7:
            n -= 36
    return n


def _data_codewords(ver: int) -> int:
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK[ver] * _NUM_BLOCKS[ver]


# ---------- Reed-Solomon（GF(256)，多項式 0x11D） ----------
def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


# ---------- 編碼資料 ----------
def _encode_data(text: str) -> tuple[int, list[int]]:
    data = text.encode("utf-8")
    for ver in range(1, 11):
        count_bits = 8 if ver <= 9 else 16
        capacity_bits = _data_codewords(ver) * 8
        if 4 + count_bits + 8 * len(data) <= capacity_bits:
            break
    else:
        raise ValueError("文字太長，放不進 QR code（最多約 210 個字元）")

    bits: list[int] = []

    def put(value: int, length: int):
        bits.extend((value >> i) & 1 for i in reversed(range(length)))

    put(0b0100, 4)                       # 位元組模式
    put(len(data), count_bits)
    for b in data:
        put(b, 8)
    put(0, min(4, capacity_bits - len(bits)))       # 結束符號
    put(0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) < capacity_bits:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    return ver, codewords


def _add_ecc_and_interleave(ver: int, data: list[int]) -> list[int]:
    num_blocks, ecc_len = _NUM_BLOCKS[ver], _ECC_PER_BLOCK[ver]
    raw = _raw_modules(ver) // 8
    num_short = num_blocks - raw % num_blocks
    short_len = raw // num_blocks
    divisor = _rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(num_blocks):
        length = short_len - ecc_len + (0 if i < num_short else 1)
        dat = data[k:k + length]
        k += length
        ecc = _rs_remainder(dat, divisor)
        if i < num_short:
            dat = dat + [0]
        blocks.append(dat + ecc)
    out = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != short_len - ecc_len or j >= num_short:
                out.append(blk[i])
    return out


# ---------- 畫格子 ----------
def _alignment_positions(ver: int, size: int) -> list[int]:
    if ver == 1:
        return []
    n = ver // 7 + 2
    step = (ver * 4 + n * 2 + 1) // (n * 2 - 2) * 2
    return [6] + sorted(size - 7 - i * step for i in range(n - 1))


def _format_bits(mask: int) -> int:
    data = _FORMAT_M << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return (data << 10 | rem) ^ 0x5412


def _mask_hit(mask: int, x: int, y: int) -> bool:
    return [
        (x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0,
        (x // 3 + y // 2) % 2 == 0, x * y % 2 + x * y % 3 == 0,
        (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0,
    ][mask]


def _build(ver: int, codewords: list[int], mask: int) -> list[list[bool]]:
    size = ver * 4 + 17
    dark = [[False] * size for _ in range(size)]
    func = [[False] * size for _ in range(size)]

    def setf(x, y, v):
        dark[y][x] = v
        func[y][x] = True

    for i in range(size):                               # 計時線
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):      # 三個定位方塊
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    setf(x, y, max(abs(dx), abs(dy)) not in (2, 4))
    pos = _alignment_positions(ver, size)
    n = len(pos)
    for i in range(n):                                   # 對齊方塊
        for j in range(n):
            if (i == 0 and j == 0) or (i == 0 and j == n - 1) or (i == n - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    setf(pos[i] + dx, pos[j] + dy, max(abs(dx), abs(dy)) != 1)

    fmt = _format_bits(mask)                             # 格式資訊（兩份）
    bit = lambda v, i: (v >> i) & 1 == 1                 # noqa: E731
    for i in range(6):
        setf(8, i, bit(fmt, i))
    setf(8, 7, bit(fmt, 6))
    setf(8, 8, bit(fmt, 7))
    setf(7, 8, bit(fmt, 8))
    for i in range(9, 15):
        setf(14 - i, 8, bit(fmt, i))
    for i in range(8):
        setf(size - 1 - i, 8, bit(fmt, i))
    for i in range(8, 15):
        setf(8, size - 15 + i, bit(fmt, i))
    setf(8, size - 8, True)

    if ver >= 7:                                         # 版本資訊
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        vbits = ver << 12 | rem
        for i in range(18):
            a, b = size - 11 + i % 3, i // 3
            setf(a, b, bit(vbits, i))
            setf(b, a, bit(vbits, i))

    i = 0                                                # 資料：從右下角之字形往上填
    total = len(codewords) * 8
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not func[y][x]:
                    if i < total:
                        dark[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
                    if _mask_hit(mask, x, y):
                        dark[y][x] = not dark[y][x]
        right -= 2
    return dark


def _penalty(m: list[list[bool]]) -> int:
    """簡化版的遮罩評分：連續同色、2×2 色塊、黑白比例。分數越低越好掃。"""
    size, score = len(m), 0
    for lines in (m, list(zip(*m))):
        for row in lines:
            run, prev = 0, None
            for v in row:
                run = run + 1 if v == prev else 1
                prev = v
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
    for y in range(size - 1):
        for x in range(size - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                score += 3
    darks = sum(map(sum, m))
    score += abs(darks * 20 - size * size * 10) // (size * size) * 10
    return score


def qr_matrix(text: str) -> list[list[bool]]:
    """回傳 QR code 的格子（True = 黑）。"""
    ver, data = _encode_data(text)
    codewords = _add_ecc_and_interleave(ver, data)
    return min((_build(ver, codewords, mask) for mask in range(8)), key=_penalty)


def qr_png(text: str, scale: int = 8, border: int = 4, dark: str = "#1C1B18", light: str = "#FFFFFF") -> bytes:
    """畫成 PNG（四周留白 4 格，掃描比較穩）。"""
    from PIL import Image, ImageDraw

    m = qr_matrix(text)
    size = (len(m) + border * 2) * scale
    img = Image.new("RGB", (size, size), light)
    draw = ImageDraw.Draw(img)
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                x0, y0 = (x + border) * scale, (y + border) * scale
                draw.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=dark)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
