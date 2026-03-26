# Extraction v3.10 — Agent I/O Contracts

> **主文件**：`specs/extraction_v3.10.md`

---

## 1. Timeline Builder v3.10

### Input Contract

| 欄位 | 來源 | Required | Gate |
|------|------|----------|------|
| `judgment_text` | Runner | YES | 缺失 → `abort` |
| `scanner_result` | Scanner | YES | 缺失 → `abort` |
| `entity_map_result` | Entity Mapper | YES | 缺失 → `abort` |
| `argument_result` | Argument Extractor | YES | 缺失 → `abort` |
| `semantic_result` | Semantic Scanner | NO | 可省略 |

### Output Contract

| 欄位 | Required | Nullable | 驗證規則 |
|------|----------|----------|---------|
| `timeline[]` | YES | NO | 長度 ≥ 2 |
| `timeline[].event_id` | YES | NO | 唯一正整數 |
| `timeline[].timestamp` | YES | NO | 非空字串 |
| `timeline[].timestamp_normalized` | YES | NO | ISO 8601 |
| `timeline[].event_type` | YES | NO | enum 值之一 |
| `timeline[].description` | YES | NO | 非空字串 |
| `timeline[].actors[]` | YES | NO | 長度 ≥ 1；必須為人名 |
| `timeline[].location` | NO | YES | 字串或空字串 |
| `timeline[].critical_decision` | YES | NO | bool |
| `timeline[].decision_content` | NO | YES | 只有 critical_decision=true 才可填 |
| `timeline[].extraction_text` | YES | NO | **primary anchor quote**，逐字片段 |
| `timeline[].source_spans[]` | YES | NO | 長度 ≥ 1；每筆為 verbatim quote |
| `timeline[].source_spans[].quote` | YES | NO | 逐字片段，不可含 `...` |
| `timeline[].source_spans[].role` | NO | YES | `primary` / `supporting` |
| `timeline_summary` | YES | NO | 必須存在 |
| `causation_chain` | NO | YES | 保留相容欄位 |

### Postprocess Contract

| 欄位 | 來源 | 說明 |
|------|------|------|
| `char_start` | Deterministic align | 取 `source_spans[0]` 對齊結果 |
| `char_end` | Deterministic align | 取 `source_spans[0]` 對齊結果 |
| `alignment_status` | Deterministic align / verifier | `MATCH_EXACT` / `MATCH_FUZZY` / `UNRESOLVED` |
| `alignment_method` | Deterministic align / verifier | `exact` / `normalized` / `context` / `fuzzy` / `llm_verifier` |
| `alignment_confidence` | Deterministic align / verifier | 0-1 |
| `source_spans[].char_start/end` | Deterministic align | 每筆 span 各自補座標 |

---

## 2. Schema Gate

### Required keys

| stage | required keys |
|------|---------------|
| `timeline` | `timeline` |
| `master` | `case_name`, `coordinates`, `entities`, `arguments`, `timeline`, `metadata` |

### Timeline validation

- `timeline` 必須是 list
- 每個 event 必須是 dict
- `source_spans` 必須是 list，且至少 1 筆
- `source_spans[].quote` 不可空
- `extraction_text` 不可空
- `event_type` 必須在允許集合內
- final artifact 允許 `char_start/char_end` 由 postprocess 補上

