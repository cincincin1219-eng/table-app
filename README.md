# Table / 席間 ── 台大附近的餐桌

「決定三餐」App 的第二版，介面改成雜誌感的「席間」風格（亞麻白底、襯線店名、唯一的顏色是陶土紅）。
下方是毛玻璃膠囊導覽列：

- **動態**：「校園」看大家分享的食記、誰幫哪家店助力、誰在揪飯、誰測出什麼稱號；「我的」看自己的紀錄。
  只有「同感」和「想去」，沒有讚數。
- **探索**：「30 秒決定一餐」＋ **愛店排行榜**（每人每店每天助力一次，本週／總榜）＋ 台大附近現在有開的店。
  店家頁可以導航、助力、揪人一起吃。
- **＋ 記錄這一餐**：店名、照片、標籤、短評、人均、人數；勾選後會分享到校園動態。
- **飯局**：「現在就走」吃飯雷達（1 小時內有效）、2～6 人飯局、顯示和你的共同點（都助力過的店、同系）、
  成團後的破冰字卡與餐桌小遊戲、檢舉與封鎖。
- **我的**：取暱稱加入（不用信箱）、改暱稱、吃貨派別測驗（稱號可分享）、紀錄牆、每月 Dump、想去清單。

社群功能用 Supabase（免費方案即可），設定方法見第 9 節；**沒設定時 App 照常運作**，社群頁面會顯示「尚未開通」。
自己的飯紀錄、照片、想去清單存在使用者自己的手機或瀏覽器（照片會先縮小成約 50 KB）；
只有勾選「分享到校園動態」的食記和照片才會上傳。
同一份 Python 程式可以跑成**網頁**和 **Android App**（使用 [Flet](https://flet.dev)，免費開源）。

> 團隊怎麼用 GitHub 分工、開分支、發 Pull Request，請看 [CONTRIBUTING.md](CONTRIBUTING.md)。
> 每次 push 和 Pull Request 都會由 GitHub Actions 自動跑測試。

## 1. 安裝（每位組員做一次）

```bash
# 需要 Python 3.10 以上
python -m venv .venv
# Windows：.venv\Scripts\activate    macOS / Linux：source .venv/bin/activate
pip install flet pillow pytest
```

## 2. 執行

在專案根目錄：

```bash
python3 tools/get_font.py       # 第一次：下載宋體和 Table 斜體字（約 9 MB，只要做一次）
python src/demo_cli.py          # 不用介面，直接在終端機看推薦結果（測邏輯最快）
flet run src/main.py            # 桌面視窗
flet run --web src/main.py      # 用瀏覽器開網頁版
pytest                          # 跑測試
```

用手機即時測試：手機安裝 Flet App（App Store / Google Play 搜尋 "Flet"），
再照 Flet 官方文件的 "Testing on mobile" 步驟連線，改程式時手機畫面會即時更新。

## 3. 打包

```bash
flet build web      # 產生 build/web，可放到 GitHub Pages 等免費靜態網站
flet build apk      # 產生 Android 安裝檔，傳給同學直接安裝（不用上架、免費）
```

打包 APK 需要 Android SDK / Flutter 等工具，第一次執行 `flet build` 時請依畫面提示或
[官方發佈說明](https://flet.dev/docs/publish) 安裝。iOS 版需要 Mac 和
Apple 開發者帳號（每年 99 美元），本學期建議 iPhone 使用者先用網頁版。

## 4. 專案結構

```
ntu-meal-picker/
├── src/
│   ├── main.py            # Flet 介面（網頁與 App 共用）：動態、探索、記錄、飯局、我的
│   ├── config.py          # Supabase 網址與公開金鑰（社群功能）
│   ├── assets/            # 字體（get_font.py 下載）、範例照片 demo/
│   ├── demo_cli.py        # 終端機示範
│   ├── core/              # 推薦邏輯，與介面無關
│   │   ├── models.py      # 資料結構、標籤與過敏原清單
│   │   ├── data.py        # 讀 CSV、解析營業時間
│   │   ├── filters.py     # C2 營業中、C3 飲食過濾、步行時間、人潮提示
│   │   ├── recommend.py   # C1 評分推薦、C6 驚喜一下、無結果時的建議
│   │   ├── journal.py     # 每一餐的紀錄（店名、照片、標籤、短評、人均、人數）與每月統計
│   │   ├── recap.py       # 每月 Dump 圖（飯 Dump、數據卡）、稱號卡、照片縮圖
│   │   ├── cloud.py       # 連 Supabase：匿名加入、助力、動態、飯局、照片上傳
│   │   ├── cloud_fake.py  # 測試用的假雲端
│   │   └── social.py      # 吃貨派別測驗、破冰字卡題庫
│   └── data/
│       ├── restaurants.csv
│       └── buildings.csv
├── supabase/            # schema.sql（資料表＋規則）、storage.sql（照片空間）
├── tools/               # 資料工具：fetch_osm.py（自動抓）、build_restaurants.py（匯入）
├── data_work/           # 放抓下來、確認中的 CSV
├── tests/
└── pyproject.toml
```

**原則**：所有判斷邏輯都放在 `core/`，介面只負責收集條件、顯示結果。
這樣 `core/` 可以單獨測試，之後要加 LINE Bot 也能直接重用。

## 5. 資料流程：自動抓 → 人工確認 → 匯入 App

**目前 App 裡的 8 家餐廳是「範例」，都是假的；建物座標也只是近似值。**
用下面三步換成真實資料。

### 步驟 1：自動抓＋篩選（負責程式的人做）

```bash
python3 tools/fetch_osm.py        # 預設 5 位組員；4 人就打 python3 tools/fetch_osm.py 4
```

會從 OpenStreetMap 抓台大周邊的餐廳，並自動產生兩個檔案：

- `data_work/osm_candidates_日期.csv`：原始清單（全部，約 900 多家）
- `data_work/verify_list_日期.csv`：**確認清單**，已經分好優先順序和負責人

| 優先 | 意思 | 約幾家 |
| --- | --- | --- |
| A 先確認 | 正餐，離最近的台大建物或公館站走路 4 分鐘內 | 約 150 |
| B 有空再確認 | 正餐 5～8 分鐘；或早餐、咖啡輕食 4 分鐘內 | 約 270 |
| C 先不用管 | 手搖飲甜點、酒館、太遠、疑似歇業或不是餐廳、重複 | 其餘 |

已經有原始清單、只想重新篩選的話：`python3 tools/prioritize.py data_work/osm_candidates_日期.csv --members 5`

**OpenStreetMap 幾乎沒收錄台大校內學餐**（小福、活大、鹿鳴堂等），請負責「校內」的組員自己新增。

### （可選）先預覽效果

還沒確認前，想先看看 App 用真實店家推薦的樣子：

```bash
python3 tools/make_preview.py data_work/verify_list_日期.csv
python3 src/demo_cli.py            # 或 flet run --web src/main.py
```

會把 A、B 級正餐（約 400 家）放進 App。沒有營業時間的店先套用 11:00-14:00、17:00-20:30，
價格顯示「價格未填」、不做預算篩選；卡片會標示「預覽資料，未確認」。
預覽時勾飲食條件多半找不到店，因為 OpenStreetMap 幾乎沒有這些標籤，這正是要人工確認的原因。

### （現在用的）先讓 App 有真的餐廳：make_starter.py

```bash
python3 tools/make_starter.py data_work/verify_list_20261119.csv
```

從確認清單挑出「台大附近、正餐、OSM 上有營業時間」的店（目前 74 家）直接寫進 App，馬上能試用。
價格是依店名或料理類型**估計**的，App 會標「（估）」；營業時間來自 OSM，可能過時；過敏原空白代表「不知道」。
組員在 Google 地圖看到價格範圍後，可以直接改 `tools/make_starter.py` 最上面的 `PRICE_BY_NAME`，再執行一次。
全部人工確認完，改用下面步驟 3 的 build_restaurants.py 匯入正式資料。

### 步驟 2：人工確認（全組分工）

1. 打開 Google 試算表 →「檔案 → 匯入 → 上傳」，選 `verify_list_日期.csv`。
2. 分享給組員。每人用「篩選」功能，選出 **負責人** 是自己、**優先** 是 A 的列。
3. 每一家確認後填好下列欄位，最後在 **verified** 欄填「是」（`提醒` 欄會告訴你這家要特別注意什麼）：

| 欄位 | 怎麼填 | 例子 |
| --- | --- | --- |
| verified | 確認完填「是」；店倒了或不是吃飯的店就留空 | 是 |
| name / area | 有錯就改；漏掉的店（例如學餐）自己新增一列 | 公館 |
| lat, lng | 新增的店才要填，Google 地圖對店家按右鍵可複製 | 25.0165, 121.5395 |
| price | 一般一餐大約幾元（整數） | 120 |
| seats | 大約座位數 | 30 |
| tags | 可寫中文，用「;」或「、」分隔：素食、全素、不辣、高蛋白 | 素食、不辣 |
| allergens | 餐點**含有**的過敏原：花生、甲殼類、乳製品、蛋、麩質 | 蛋、麩質 |
| mon ~ sun | 營業時間，兩段用 `\|` 分隔，公休留空，跨夜寫 18:00-02:00 | 11:00-14:00\|17:00-20:30 |
| popular | 尖峰時段常大排長龍就填「是」 | 是 |
| notes | 程式提醒你要補什麼，也可寫備註 | |

`osm_` 開頭的欄位是原始資料，給你參考用，不用改。
**過敏資訊不確定就不要亂填**，寧可漏推也不要誤推。

4. 全部確認完：「檔案 → 下載 → 逗號分隔值（.csv）」，把檔案放進專案的 `data_work` 資料夾。

### 步驟 3：匯入 App（負責程式的人做）

```bash
python3 tools/build_restaurants.py data_work/下載的檔名.csv
```

- 只會收錄 verified 填「是」的店。
- 有格式錯誤會告訴你「第幾列、哪個欄位錯」，修好再跑一次就好；有錯時不會動到 App 的資料。
- 成功後執行 `flet run --web src/main.py` 就能看到真實餐廳。

資料來源標示：© OpenStreetMap contributors（ODbL 授權），期末報告與 App 中請註明。

### App 實際使用的 `src/data/restaurants.csv` 欄位（由步驟 3 自動產生，不用手動改）

| 欄位 | 說明 | 範例 |
| --- | --- | --- |
| id | 唯一代號 | r01 |
| name / area | 店名 / 區域 | 校內、公館、溫州街、科技大樓 |
| lat, lng | 緯度、經度（Google 地圖右鍵可複製） | 25.0165, 121.5395 |
| price | 一般一餐價格（元） | 100 |
| seats | 大約座位數 | 30 |
| tags | 有的特性，`;` 分隔：vegetarian、vegan、not_spicy、high_protein | vegetarian;not_spicy |
| allergens | 餐點含有的過敏原：peanut、shellfish、dairy、egg、gluten | egg;gluten |
| mon ~ sun | 營業時間，多段用 `\|` 分隔，公休留空，跨夜如 18:00-02:00 | 11:00-14:00\|17:00-20:30 |
| popular | 尖峰時段常排隊：true / false | true |
| last_checked | 最後實地確認日期 | 2026-11-19 |


## 6. 推薦規則（可依訪談結果調整 `core/recommend.py`）

1. 硬性過濾：飲食標籤與過敏原 → 營業中 → 抵達時距打烊至少 15 分鐘 →
   來回步行＋用餐（1 人 25 分、多人 40 分）不超過可用時間 → 預算 → 座位數
2. 評分：越近越高（40 分）、越便宜越高（20 分）、熱門店在尖峰時段 −15、
   非尖峰 +5、營業還很久 +5、最近吃過 −25
3. 取前 3 名；沒有結果時說明哪個條件刷掉最多店（不會建議放寬飲食限制）

## 7. 下一步（對應報告的功能編號）

- [ ] 實地補齊 80 家餐廳與 20 棟建物資料
- [x] V1 社群：取暱稱加入（匿名登入）、助力排行榜、校園動態、飯局與吃飯雷達、破冰字卡、吃貨派別測驗（第 9 節設定）
- [ ] 破冰字卡改由 AI 產生（目前用題庫，介面不用改，換掉 core/social.py 的 icebreaker_cards）
- [ ] V2：15 格 Dump 與短片、共創 Dump、集章、轉盤分帳（見「社群升級規劃」文件）
- [ ] 探索頁的真地圖（Flet 的 flet-map 擴充套件 ＋ OpenStreetMap 圖磚）
- [ ] C4 多人聚餐房間投票（需要共用資料庫，例如 Supabase / Firebase 免費方案，或自架 FastAPI + SQLite）
- [ ] C5 使用者回報排隊狀況
- [ ] C6 記住個人偏好（目前只在單次使用中記得「最近選過」）
- [ ] 部署網頁版、打包 APK、找 10 位同學試用

## 8. 發佈成公開網站（讓大家用網址打開）

`flet run --web` 給的 `http://127.0.0.1:xxxx` 只有自己電腦打得開。要給大家用，要發佈成靜態網站：

```bash
# 1. 打包成網站（會產生在 src/dist 資料夾）
flet publish src/main.py -a assets --distpath dist

# 2. 先在自己電腦測試，打開 http://localhost:8000
python3 -m http.server 8000 --directory src/dist
```

3. 把 `src/dist` 資料夾上傳到免費主機，例如 Cloudflare Pages 的「直接上傳」(Direct Upload)，
   或 Netlify Drop（app.netlify.com/drop，把資料夾拖進網頁即可），就會拿到一個 https 公開網址。
4. 每次更新餐廳資料（build_restaurants.py）後，要重新做 1～3 步，網站上的資料才會更新。

注意：網站第一次打開要下載 Python 執行環境，會等 10～20 秒，之後就快了。

## 9. 社群功能設定（Supabase，全部免費方案）

社群功能需要一個大家共用的資料庫。以下步驟由一位組員做一次就好，大約 10 分鐘。
**不需要信箱登入**：使用者第一次取個暱稱就加入，帳號跟著那支手機或那個瀏覽器（Supabase 的匿名登入）。

1. **建立專案**：到 supabase.com 登入 → New project，區域選 Northeast Asia (Tokyo)（或 auto）。
2. **建立資料表與規則**：SQL Editor → New query → 貼上 `supabase/schema.sql` → Run；
   再開一個 query 貼上 `supabase/storage.sql` → Run。兩份都可以重複執行；**更新版本時要再執行一次 schema.sql**。
3. **開啟匿名登入**：Authentication → Sign In / Providers（或 Providers）→ 找到 **Allow anonymous sign-ins**
   （或 Anonymous）→ 打開 → Save。
4. **填金鑰**：Project Settings → API Keys / Data API，把 Project URL 和 anon（或 publishable）key 貼到 `src/config.py`。
   **不要**貼 service_role / secret key。
5. **看檢舉**：Table Editor → reports；封鎖紀錄在 blocks。被檢舉的內容可以在 Table Editor 直接刪除。
6. **重新發佈**：`flet publish src/main.py -a assets --distpath dist`，把新的 `src/dist` 拖到 Netlify
   原本那個專案的 **Deploys** 頁面，網址不會變。

注意：匿名帳號清除瀏覽器資料或換手機就會變成新帳號。之後如果要改回台大信箱登入，
`core/cloud.py` 裡的信箱驗證碼功能還留著，需要另外接寄信服務（SMTP）。

資料庫規則有自動測試：裝了 Postgres 的電腦可以執行 `TABLE_SQL_TESTS=1 pytest tests/test_sql.py`。
