"""讀取 CSV 資料。欄位說明見 README。"""
from __future__ import annotations

import csv
from pathlib import Path

from .models import DAYS, Building, Restaurant

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def parse_hours(text: str) -> list[tuple[int, int]]:
    """'11:00-14:00|17:00-20:30' -> [(660, 840), (1020, 1230)]。

    空字串代表當天公休。打烊時間早於開門時間代表跨夜（例如 18:00-02:00）。
    """
    text = (text or "").strip()
    if not text:
        return []
    spans = []
    for part in text.split("|"):
        start, end = part.split("-")
        s, e = _to_minutes(start), _to_minutes(end)
        if e <= s:
            e += 24 * 60
        spans.append((s, e))
    return spans


def _split(text: str) -> set[str]:
    return {t.strip() for t in (text or "").split(";") if t.strip()}


def load_restaurants(path: Path | str = DATA_DIR / "restaurants.csv") -> list[Restaurant]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    result = []
    for row in rows:
        result.append(
            Restaurant(
                id=row["id"],
                name=row["name"],
                area=row["area"],
                lat=float(row["lat"]),
                lng=float(row["lng"]),
                price=int(row["price"]),
                seats=int(row["seats"]),
                tags=_split(row["tags"]),
                allergens=_split(row["allergens"]),
                hours={d: parse_hours(row[d]) for d in DAYS},
                popular=row["popular"].strip().lower() in {"1", "true", "yes", "y"},
                last_checked=row.get("last_checked", ""),
            )
        )
    return result


def load_buildings(path: Path | str = DATA_DIR / "buildings.csv") -> list[Building]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [
            Building(id=r["id"], name=r["name"], lat=float(r["lat"]), lng=float(r["lng"]))
            for r in csv.DictReader(f)
        ]
