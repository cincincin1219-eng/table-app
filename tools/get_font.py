"""下載「席間」介面用的兩套免費字體，執行一次就好（在專案資料夾）：

    python3 tools/get_font.py

  NotoSerifTC-Medium.otf  思源宋體（店名、標題）  SIL Open Font License 1.1
  Logo-Italic.ttf         Cormorant Garamond 斜體（Table 字樣）  SIL Open Font License 1.1

沒下載也能用：Mac 桌面版會用內建宋體，網頁版用預設字體，只是沒那麼好看。
"""
import shutil
import sys
import urllib.request
from pathlib import Path

FONTS = Path(__file__).resolve().parent.parent / "src" / "assets" / "fonts"      # 介面用
PACKAGE_FONTS = Path(__file__).resolve().parent.parent / "src" / "core" / "fonts"  # Logo 字體（網頁版回顧圖用）
TARGETS = [
    ("NotoSerifTC-Medium.otf", "思源宋體 Noto Serif TC（約 8 MB）", [
        "https://github.com/notofonts/noto-cjk/raw/main/Serif/SubsetOTF/TC/NotoSerifTC-Medium.otf",
        "https://github.com/googlefonts/noto-cjk/raw/main/Serif/SubsetOTF/TC/NotoSerifTC-Medium.otf",
    ]),
    ("Logo-Italic.ttf", "Cormorant Garamond 斜體（約 0.5 MB）", [
        "https://github.com/google/fonts/raw/main/ofl/cormorantgaramond/CormorantGaramond-SemiBoldItalic.ttf",
        "https://github.com/google/fonts/raw/main/ofl/cormorantgaramond/CormorantGaramond-Italic%5Bwght%5D.ttf",
        "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Italic%5Bwght%5D.ttf",
    ]),
]


def download(name: str, label: str, urls: list[str]) -> bool:
    dest = FONTS / name
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f"✓ {label} 已經下載過了")
        return True
    print(f"正在下載 {label} …")
    for url in urls:
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as exc:
            print(f"  這個網址不行（{exc.__class__.__name__}），換下一個")
            continue
        if dest.stat().st_size > 100_000:
            print(f"✓ 完成：{dest}")
            return True
        dest.unlink()
    print(f"✗ {label} 下載失敗。稍後再試，或手動下載後改名為 {name} 放到 {FONTS}")
    return False


def main():
    FONTS.mkdir(parents=True, exist_ok=True)
    ok = all([download(*t) for t in TARGETS])
    PACKAGE_FONTS.mkdir(parents=True, exist_ok=True)
    for name, _, _ in TARGETS:
        if name == "NotoSerifTC-Medium.otf":     # 太大，不打包進網頁版；網頁版會從網站的 fonts/ 下載
            continue
        if (FONTS / name).exists():
            shutil.copy2(FONTS / name, PACKAGE_FONTS / name)
    print("\n重新執行 flet run --web src/main.py 就會套用。" if ok else "\n有字體沒下載成功，App 仍然可以用。")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
