"""把 OpenStreetMap 的 opening_hours 轉成本專案的格式。

OSM 例子：  "Mo-Fr 11:00-14:00,17:00-20:00; Sa 11:00-14:00; Su off"
本專案格式：{"mon": "11:00-14:00|17:00-20:00", ..., "sun": ""}

支援：星期範圍（含跨週如 Fr-Mo）、多段時間、逗號或分號分隔的多條規則、
off/closed、24/7、超過 24 點的寫法（如 17:00-26:00 = 凌晨 2 點）、
國定假日 PH/SH（略過，不影響一般日子）。
看不懂的（月份、日期等特殊規則）回傳 None，交給人工確認。
"""
from __future__ import annotations

import re

OSM_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
OUR_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY = re.compile(r"^(Mo|Tu|We|Th|Fr|Sa|Su|PH|SH)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?$")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")


def _day_range(a: str, b: str | None) -> list[int]:
    if a in ("PH", "SH"):
        return []                                   # 假日規則：略過
    i = OSM_DAYS.index(a)
    if b is None:
        return [i]
    j = OSM_DAYS.index(b)
    return list(range(i, j + 1)) if i <= j else list(range(i, 7)) + list(range(0, j + 1))


def _norm_time(tok: str) -> str | None:
    m = _TIME.match(tok)
    if not m:
        return None
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if h1 > 24 or h2 > 48 or m1 > 59 or m2 > 59:
        return None
    if h2 > 24:                                     # 26:00 → 02:00（跨夜）
        h2 -= 24
    return f"{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}"


def _tokens(text: str) -> list[str]:
    text = text.replace("、", ",").replace("，", ",").replace("；", ";").replace("：", ":")
    text = re.sub(r"\s*([,;])\s*", r" \1 ", text)
    return text.split()


def parse_osm_hours(text: str) -> dict[str, str] | None:
    text = (text or "").strip()
    if not text:
        return None
    if text == "24/7":
        return {d: "00:00-24:00" for d in OUR_DAYS}

    result = {d: "" for d in OUR_DAYS}             # OSM：沒寫到的日子視為公休
    days: list[int] | None = None                    # None = 還沒指定星期
    saw_day_token = False
    times: list[str] | None = None
    any_rule = False

    def flush():
        nonlocal days, times, saw_day_token, any_rule
        if times is not None:
            targets = days if saw_day_token else list(range(7))
            value = "" if times == ["off"] else "|".join(times)
            for d in targets or []:
                result[OUR_DAYS[d]] = value
            any_rule = True
        elif saw_day_token and days:
            raise ValueError("只有星期沒有時間")
        days, times, saw_day_token = None, None, False

    try:
        for tok in _tokens(text):
            if tok == ";":
                flush()
            elif tok == ",":
                continue
            elif (m := _DAY.match(tok)):
                if times is not None:              # 時間後面又出現星期 = 新的一條規則
                    flush()
                days = (days or []) + _day_range(m.group(1), m.group(2))
                saw_day_token = True
            elif tok.lower() in ("off", "closed"):
                times = ["off"]
            elif tok == "24/7":
                times = ["00:00-24:00"]
            elif (t := _norm_time(tok)):
                times = (times if times and times != ["off"] else []) + [t]
            else:
                return None                        # 看不懂的寫法
        flush()
    except ValueError:
        return None
    return result if any_rule else None
