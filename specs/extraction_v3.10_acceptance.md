# Extraction v3.10 — Acceptance Notes

> **主文件**：`specs/extraction_v3.10.md`

## 目標

- `span_mismatch` 顯著下降
- `not_found` 事件明顯減少
- 複合事件保留可追溯來源

## 建議驗收指標

| 指標 | 目標 |
|------|------|
| timeline exact quote match rate | >= v3.9 |
| unresolved event rate | <= v3.9 |
| multi-span event coverage | 有明顯提升 |
| `...` in `source_spans[].quote` | 0 |

