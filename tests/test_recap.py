import io
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.journal import monthly_stats, new_entry  # noqa: E402
from core.recap import H, W, make_thumbnail, render_photo_dump, render_stats_card  # noqa: E402


def _entries(n=12):
    t = datetime(2026, 11, 1, 12, 0)
    names = ["公館麵店", "一間名字非常非常長的超級好吃日式炸豬排咖哩飯專賣店", "Pasta 2 Go"]
    return [new_entry(t + timedelta(days=i), names[i % 3], area="公館", walk_minutes=3) for i in range(n)]


def _jpeg(w=1200, h=800, color=(200, 120, 80)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def test_stats_card_is_story_size():
    png = render_stats_card(monthly_stats(_entries(), 2026, 11))
    assert Image.open(io.BytesIO(png)).size == (W, H) == (1080, 1920)


def test_empty_month_still_renders():
    assert Image.open(io.BytesIO(render_stats_card(monthly_stats([], 2027, 1)))).size == (W, H)
    assert Image.open(io.BytesIO(render_photo_dump([], {}, 2027, 1))).size == (W, H)


def test_photo_dump_mixes_photos_and_placeholders():
    entries = _entries(12)
    photos = {entries[0].id: make_thumbnail(_jpeg()), entries[5].id: make_thumbnail(_jpeg(600, 900))}
    png = render_photo_dump(entries, photos, 2026, 11)
    assert Image.open(io.BytesIO(png)).size == (W, H)


def test_thumbnail_is_small_jpeg():
    thumb = make_thumbnail(_jpeg(4000, 3000))
    img = Image.open(io.BytesIO(thumb))
    assert img.format == "JPEG" and max(img.size) == 640
    assert len(thumb) < 150_000
