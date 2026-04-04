# Arena POC — SPEC

## 目標

建立一個 Blind Pairwise Comparison 頁面，讓評審者對同一案件的兩份匿名摘要進行 A/B 比較投票。POC 階段不串 Firestore，投票結果存 localStorage 並可匯出 JSON。

---

## 參與比較的 Conditions（8 個）

### 商用組（Haiku backbone）
| ID | 顯示名（排行榜用） | Arena 匿名 |
|----|---------------------|------------|
| `claude_afg_v5.1` | LENS-Haiku-Full | 隱藏 |
| `ablation_no_afg` | LENS-Haiku-NoAFG | 隱藏 |
| `ablation_no_react` | LENS-Haiku-NoReact | 隱藏 |
| `baseline_claude-haiku` | Haiku Baseline | 隱藏 |

### 開源組（DeepSeek v3.1 backbone）
| ID | 顯示名（排行榜用） | Arena 匿名 |
|----|---------------------|------------|
| `LENS-Full-DeepSeek_v31` | LENS-DeepSeek-Full | 隱藏 |
| `LENS-NoReact-DeepSeek_v31` | LENS-DeepSeek-NoReact | 隱藏 |
| `baseline_ollama_deepseek-v3.1-671b-cloud` | DeepSeek Baseline | 隱藏 |

> 注意：`LENS-NoAFG-DeepSeek_v31` 因資料不齊（僅 24 案）排除，共 7 個 conditions。

---

## 評比案件（15 案）

從 `human_eval_30_candidates.json` 中選出：

### 上冊（3 案）
| case_id | 案名 | 字數 | 判決 |
|---------|------|------|------|
| 待對應 | 車禍腹痛延誤治療案 | 13,520 | 有罪 |
| 待對應 | 總膽管取石術腹痛未照會案 | 12,962 | 有罪 |
| 待對應 | 心肌梗塞急救時機案 | 35,440 | 無罪 |

### 中冊（6 案）
| case_id | 案名 | 字數 |
|---------|------|------|
| 待對應 | 肝臟切除術後出血案 | 40,135 |
| 待對應 | 抽脂術後併發症休克案 | 21,595 |
| 待對應 | 子宮外孕未為必要處置案 | 17,832 |
| 待對應 | 連續插管失敗遲未照會案 | 15,744 |
| 待對應 | 福尼爾氏壞死症未擴創手術案 | 13,057 |
| 待對應 | 主動脈剝離鑑別診斷案 | 8,908 |

### 下冊（6 案）
| case_id | 案名 | 字數 |
|---------|------|------|
| 待對應 | 試管嬰兒子宮外孕案 | 33,533 |
| 待對應 | Tegretol藥物治療案 | 25,110 |
| 待對應 | 活體腎臟移植手術案 | 21,239 |
| 待對應 | 車禍手術麻醉案 | 18,384 |
| 待對應 | 筋膜切開術後截肢案 | 16,255 |
| 待對應 | 健檢中心Inderal藥物案 | 10,790 |

---

## 頁面規格：`arena.html`

### 1. 佈局

沿用 view.html 的設計語言（toolbar、panel border-radius:12px、#4f46e5 主色、section-content 排版）。

```
┌──────────────────────────────────────────────────────────────┐
│ Toolbar: [LENS Arena]  案件 3/15  已投票 12  [排行榜] [摘要檢視] │
├──────────────────────────────────────────────────────────────┤
│ Section tabs:  [事實] [爭點] [判決理由] [鑑定意見] [量刑/結論]    │
├─────────────────────────┬────────────────────────────────────┤
│                         │                                    │
│      摘要 A              │      摘要 B                        │
│                         │                                    │
│  （白底 panel，           │  （白底 panel，                     │
│   border-radius:12px，   │   border-radius:12px，             │
│   與 view.html 的         │   相同 section-content 排版）       │
│   content-panel 同風格）  │                                    │
│                         │                                    │
├─────────────────────────┴────────────────────────────────────┤
│                                                              │
│   [  A 較好  ]     [  難分高下  ]     [  B 較好  ]              │
│                                                              │
│   理由（選填）：[____________________________________]         │
│                                                              │
│                               [ 送出並看下一組 → ]             │
└──────────────────────────────────────────────────────────────┘
```

### 2. Toolbar

- 左側：「LENS Arena」標題
- 中間：進度指示 `案件 3/15 · 已投票 12`
- 右側：導航連結（排行榜、摘要檢視、首頁）

### 3. Section Tabs

- 水平 tab bar，固定在兩個 panel 上方
- 點選 tab 時，**兩邊同時切換到同一 section**
- Tab 列表從資料的 `sections` 陣列動態生成
- Active tab 使用 indigo 底色

### 4. 雙欄摘要面板

- 左右各一個 panel，樣式沿用 view.html 的 `.content-panel`
- Panel 標題只顯示 **「摘要 A」/「摘要 B」**，不透露 condition
- 摘要內容排版沿用 `.section-content`（font-size:14px, line-height:1.85, white-space:pre-wrap）
- Citation tags `[CH_XX]` 沿用紫色標籤樣式（但 POC 不需點擊互動）
- 兩個 panel **各自獨立捲動**
- A/B 的左右位置每次隨機分配

### 5. 投票區

- 三個按鈕：「A 較好」「難分高下」「B 較好」
- 按鈕風格：大圓角、hover 有 shadow，選中後高亮
- 「A 較好」/ 「B 較好」選中時為 indigo；「難分高下」為灰色
- 下方一個 textarea：「理由（選填）」，placeholder: "簡述你的判斷依據..."
- 「送出並看下一組 →」按鈕，未選投票時 disabled

### 6. 首次進入

- 彈出 modal 詢問暱稱
- 輸入後存入 `localStorage('arena_evaluator')`
- 之後進入自動跳過

---

## 配對抽樣邏輯

### 配對池

C(7,2) = 21 種 condition pairs × 15 cases = 315 種組合。

### 加權分層

| 優先級 | 配對類型 | 權重 |
|--------|----------|------|
| 高 | 同 backbone Full vs Baseline | 3 |
| 高 | 同 backbone Full vs NoAFG | 3 |
| 高 | 同 backbone Full vs NoReact | 3 |
| 中 | 同 backbone NoAFG vs NoReact | 2 |
| 中 | 同 backbone NoAFG/NoReact vs Baseline | 2 |
| 中 | 跨 backbone Full vs Full | 2 |
| 低 | 跨 backbone Baseline vs Baseline | 1 |
| 低 | 其他跨 backbone 配對 | 1 |

### 抽樣流程

1. 從配對池中按權重隨機選一組 (case, condA, condB)
2. 跳過該評審已投票過的組合
3. A/B 左右位置隨機
4. 若所有高權重配對都做完，降級到中權重，再到低權重

---

## 資料來源

直接從現有的 `./data/{condition}/{case_id}.json` 載入，欄位：
- `sections[].id` — section 識別
- `sections[].title` — section 標題（用於 tab）
- `sections[].content` — section 內文

不需要額外建資料。

---

## 投票儲存（POC：localStorage）

```json
{
  "evaluator": "wayne",
  "votes": [
    {
      "case_id": "case_012",
      "condition_a": "claude_afg_v5.1",
      "condition_b": "baseline_claude-haiku",
      "display_order": "a_left",
      "winner": "a",
      "reason": "A 的爭點整理比較完整",
      "timestamp": "2026-04-04T10:23:00Z",
      "duration_sec": 85
    }
  ]
}
```

- Key: `arena_votes`
- 提供「匯出 JSON」按鈕，下載完整投票紀錄
- 提供「清除紀錄」按鈕（確認後清除）

---

## 排行榜（內嵌於同頁，或獨立 tab）

POC 階段用當前評審者自己的投票計算：

- 各 condition 勝率表
- 簡易 Elo 排名（初始 1000 分，K=32）
- 投票總數 / 完成進度

---

## 手機適配

沿用 view.html 的 responsive 策略：
- ≤768px：雙欄改為上下堆疊（A 在上、B 在下）
- Section tabs 改為水平可捲動
- 投票按鈕改為全寬堆疊

---

## 檔案清單

| 檔案 | 用途 |
|------|------|
| `arena.html` | 主頁面（HTML + CSS + JS 全包，與 view.html 同模式） |
| `data/arena_config.json` | 15 案 case_id 清單 + 7 conditions + 配對權重定義 |

---

## 不做的事（POC 排除）

- Firestore 讀寫
- 多評審者排行榜彙總
- 原文 chunk 引用面板（view.html 的 source-panel）
- Citation 點擊互動
- 同步捲動
