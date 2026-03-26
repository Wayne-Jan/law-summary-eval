# Agentic Extraction Pipeline v3.10 Specification

> **Version**: 3.10
> **Date**: 2026-03-26
> **Status**: Draft
> **Lineage**: v3.9 → **v3.10（timeline evidence-span upgrade）**
> **附錄**:
> - `specs/extraction_v3.10_contracts.md` - Agent I/O Contract 與 Gate 條件

---

## 版本目標

v3.10 的重點不是重做整個 pipeline，而是把 timeline 的來源表示改成「可追溯的 evidence spans」：

- 保留 v3.9 的整體 pipeline 結構與模型分工
- 讓一筆 timeline event 可以對應多個原文片段
- 把「事件摘要」和「原文定位」拆開
- 以 deterministic alignment 為主，LLM 只負責語義抽取，不再強迫它猜字元座標

---

## 設計原則

1. **Backwards-compatible first**
   - 舊版消費端仍可讀取 `timeline[]`、`extraction_text`、`char_start`、`char_end`
   - 新增欄位不破壞既有欄位

2. **Evidence-driven timeline**
   - 一筆 event 可以有多個 `source_spans[]`
   - 每個 span 都必須是原文中的逐字片段
   - 複合事件不再硬塞成單一連續字串

3. **Deterministic alignment**
   - LLM 不再輸出 `char_start/char_end`
   - 座標由後處理 deterministic alignment 補上
   - `extraction_text` 只保留作為 primary anchor quote

4. **Split when possible**
   - 若一個複合事件可拆成多個原子事件，優先拆開
   - 只有在語義上必須保留為單一事件時，才使用多個 `source_spans[]`

---

## Pipeline 總覽

```text
Phase 1: SCAN
  Scanner (Deepseek)

Phase 2: EXTRACT
  Entity Mapper (Deepseek)
    → Argument Extractor (Deepseek)
      → Timeline Builder v3.10 (Deepseek)

Phase 3: CROSS-VALIDATE
  Cross-Validator (Kimi)

Phase 4: ALIGN
  4a. Deterministic source-span alignment
  4b. Alignment Verifier (Kimi) for fuzzy/unresolved anchors

Phase 5: AUDIT
  Auditor (Kimi)

Phase 6: REFLEXION
  Orchestrator (Kimi), only when gates trigger
```

---

## Timeline v3.10 行為規範

### 事件切分原則

- 一筆事件應以單一時間點、單一語義動作為主
- 若原文有多個時間點、連續檢驗、連續用藥或連續觀察，優先拆成多筆
- 若事件本身是複合敘事，允許保留單筆，但必須附多個 `source_spans[]`

### source_spans 規則

- `source_spans[]` 至少 1 筆
- 每筆 span 都必須是原文中的 verbatim quote
- 不可用 `...` 拼接兩段原文
- primary span 放第一個
- 其餘 span 只放真的有證據意義的補充片段

### extraction_text 規則

- `extraction_text` 仍保留
- 它代表 **primary anchor quote**
- 必須可以直接在原文中定位
- 不得改寫，不得混合多段

### char_start / char_end 規則

- LLM 不輸出座標
- 後處理會以 `source_spans[0]` 補上 event-level `char_start/char_end`
- 若 primary span 無法對齊，事件進入 `UNRESOLVED`

---

## 介面變更

### 新增

- `source_spans[]`
- `alignment_status`
- `alignment_method`
- `alignment_confidence`

### 保留

- `timeline[]`
- `extraction_text`
- `char_start`
- `char_end`
- `timeline_summary`

### 移除自 LLM 輸出

- `char_start`
- `char_end`

---

## 版本策略

- v3.9 繼續維持現有 behavior，不回頭改
- v3.10 由新 runner 產生
- 之後 frontend 若要支援多段高亮，只需讀 `source_spans[]`

