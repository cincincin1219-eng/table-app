# 團隊協作方式（GitHub）

## 一次性設定（組長做）

1. 在 GitHub 建立新的 repository，名稱 `ntu-meal-picker`，可選 Private。
2. Settings → Collaborators → 邀請所有組員。
3. 在自己電腦把這個資料夾推上去：

   ```bash
   cd ntu-meal-picker
   git init
   git add .
   git commit -m "初始專案：推薦核心、Flet 介面、範例資料"
   git branch -M main
   git remote add origin https://github.com/<組長帳號>/ntu-meal-picker.git
   git push -u origin main
   ```

4. Settings → Branches → 為 `main` 加上保護規則：
   需要 Pull Request 才能合併、需要 1 人 review、需要 `tests` 通過。

## 每位組員的日常流程

```bash
git clone https://github.com/<組長帳號>/ntu-meal-picker.git   # 第一次
git checkout main && git pull                                   # 每次開工前
git checkout -b feature/c4-vote-room                            # 一個功能開一個分支
# ...寫程式...
pytest                                                          # 確認測試通過
git add . && git commit -m "C4：新增投票房間資料表"
git push -u origin feature/c4-vote-room
```

接著到 GitHub 開 Pull Request，填好範本，指定一位組員 review，通過且測試綠燈後再 Merge。

## 分支命名

| 類型 | 格式 | 例子 |
| --- | --- | --- |
| 新功能 | `feature/<功能>` | `feature/c5-crowd-report` |
| 修 bug | `fix/<問題>` | `fix/overnight-hours` |
| 介面 | `ui/<畫面>` | `ui/result-card` |
| 資料 | `data/<區域>` | `data/gongguan` |

## 用 GitHub 管理進度

- **Issues**：每個功能、bug、待補的資料區域各開一張，指派負責人。
  建議標籤：`C1`～`C6`、`ui/ux`、`data`、`bug`。
- **Projects（看板）**：欄位用 Todo / In progress / Review / Done，
  每兩週的 Sprint 會議直接看板子對進度，也能當期末報告的分工證據。
- **Milestones**：`MVP（W12）`、`完整版（W14）`、`期末（W16）`。

## 小規則

- 不要直接 push 到 `main`。
- 一個 PR 只做一件事，越小越好 review。
- 介面改動請附手機寬度截圖，讓大家一起看 UI/UX。
- 改 `core/` 的邏輯要補測試（`tests/test_core.py`）。
- 不要把 API 金鑰等祕密放進程式碼。
