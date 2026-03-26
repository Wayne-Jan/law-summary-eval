"""Timeline Builder Prompt - v3.10 evidence-span aware version."""

from __future__ import annotations

from typing import Optional


TIMELINE_BUILDER_SYSTEM_PROMPT = """你是醫療糾紛時序分析專家，專門分析台灣醫療過失刑事判決書。
你的任務是建構完整、準確、可追溯的醫療事件時間軸。
"""


def build_timeline_builder_prompt(
    judgment_text: str,
    scanner_result: dict,
    entity_map_result: dict,
    argument_result: dict,
    semantic_result: Optional[dict] = None,
    max_text_length: int = 100000,
) -> str:
    """Build the v3.10 prompt.

    v3.10 changes:
    - keep `extraction_text` as the primary exact quote
    - add `source_spans[]` so one event can be grounded by multiple quotes
    - do not ask the model to guess char offsets; alignment happens later
    """

    if len(judgment_text) > max_text_length:
        judgment_text = judgment_text[:max_text_length] + "\n...[文本已截斷]..."

    defendants = entity_map_result.get("defendants", [])
    victims = entity_map_result.get("victims", [])
    all_actor_names = entity_map_result.get("all_actor_names", [])

    expert_opinions = argument_result.get("expert_opinions", [])
    critical_timepoints = []
    for op in expert_opinions:
        for tp in op.get("critical_timepoints", []):
            critical_timepoints.append(
                {
                    "timestamp": tp.get("timestamp", ""),
                    "description": tp.get("description", ""),
                    "source": op.get("institution", ""),
                }
            )

    verdict_info = ""
    sentence_info = ""
    validated_persons_info = ""

    if semantic_result:
        verdict_type = semantic_result.get("verdict_type", "unknown")
        verdict_reasoning = semantic_result.get("verdict_reasoning", "")
        is_plea_bargain = semantic_result.get("is_plea_bargain", False)
        is_simplified_trial = semantic_result.get("is_simplified_trial", False)

        verdict_info = f"""
## 判決類型分析
- 判決類型：{verdict_type}
- 協商判決：{"是" if is_plea_bargain else "否"}
- 簡式審判：{"是" if is_simplified_trial else "否"}
- 判斷依據：{verdict_reasoning}
"""

        sentences = semantic_result.get("sentences", [])
        if sentences:
            sentence_lines = []
            for s in sentences:
                line = (
                    f"  - {s.get('defendant_name', '')}: "
                    f"{s.get('sentence_type', '')} {s.get('duration_text', '')} "
                    f"({s.get('duration_months', 0)}月)"
                )
                if s.get("probation_years"):
                    line += f"，緩刑 {s['probation_years']} 年"
                sentence_lines.append(line)
            sentence_info = f"""
## 刑期資訊（供時間軸終點參考）
{chr(10).join(sentence_lines)}
"""

        validated_defendants = semantic_result.get("validated_defendants", [])
        validated_victims = semantic_result.get("validated_victims", [])
        if validated_defendants or validated_victims:
            def_names = [
                f"{d.get('standard_name', '')} (別名: {', '.join(d.get('potential_aliases', []))})"
                for d in validated_defendants
            ]
            vic_names = [
                f"{v.get('standard_name', '')} (別名: {', '.join(v.get('potential_aliases', []))})"
                for v in validated_victims
            ]
            validated_persons_info = f"""
## 驗證後人名（請使用標準名稱）
- 被告：{def_names if def_names else "無"}
- 被害人：{vic_names if vic_names else "無"}
"""

    prompt = f"""# 任務：醫療事件時間軸建構（v3.10）

## 案件基本資訊
- 案號：{scanner_result.get("case_number", "")}
- 法院：{scanner_result.get("court", "")}
- 判決日期：{scanner_result.get("verdict_date", "")}
{verdict_info}
## 已識別的被告
{[d.get("name", "") for d in defendants]}

## 已識別的被害人
{[v.get("name", "") for v in victims]}
{validated_persons_info}
## 所有相關人員
{all_actor_names}
{sentence_info}
## 鑑定意見中的關鍵時間點（必須納入時間軸）
{critical_timepoints if critical_timepoints else "無"}

## 時間軸建構要求

請從判決書中萃取所有醫療相關事件，建構完整、可追溯的時間軸。

### 必須涵蓋的事件類型
1. **initial_contact**
2. **diagnosis**
3. **treatment**
4. **vital_signs**
5. **consultation**
6. **deterioration**
7. **critical_decision**
8. **transfer**
9. **final_outcome**

### 切分原則
- 一筆事件應盡量對應一個原子事件
- 若原文將多個觀察 / 檢驗 / 處置寫成一段連續病程，但語義上不可再拆，允許保留單筆事件
- 但若有多個可獨立定位的原文片段，請拆成多個 `source_spans[]`
- 不要把兩段原文用 `...` 拼成一個 quote

### source_spans 規則
- `source_spans[]` 至少 1 筆
- 每筆 `quote` 必須是原文中的逐字片段
- `quote` 不可改寫，不可加省略號
- `source_spans[0]` 為 primary span
- 若事件需要多個證據片段，`source_spans` 可放 2~3 筆

### extraction_text 規則
- `extraction_text` 請填 **primary anchor quote**
- 它必須是可直接在原文定位的逐字片段
- 它不負責描述全部事件，只負責提供最穩定的主錨點

### 事件描述規則
- `description` 可用摘要式語句，但要忠實於原文
- `actors` 必須是人名，不可填 entity ID
- `critical_decision` 請照原文重要性標註
- `vital_signs` 若原文出現體溫、血壓、心跳、呼吸、血氧或意識，請主動填入

## 輸出格式

請輸出 JSON：

```json
{{
  "timeline": [
    {{
      "event_id": 1,
      "timestamp": "94年3月27日",
      "timestamp_normalized": "2005-03-27",
      "event_type": "initial_contact",
      "description": "蔡木成因車禍送醫",
      "actors": ["蔡木成"],
      "location": "急診室",
      "critical_decision": false,
      "extraction_text": "原文逐字片段",
      "source_spans": [
        {{"role": "primary", "quote": "原文逐字片段"}},
        {{"role": "supporting", "quote": "另一個逐字片段"}}
      ]
    }}
  ],
  "timeline_summary": {{
    "total_events": 15,
    "time_span": {{
      "start": "2005-03-27",
      "end": "2005-03-28",
      "duration_hours": 40.5
    }},
    "critical_decisions_count": 3,
    "has_initial_contact": true,
    "has_deterioration": true,
    "has_final_outcome": true,
    "time_gaps": [
      {{
        "from_event_id": 5,
        "to_event_id": 6,
        "gap_hours": 8,
        "explanation": "夜間觀察期間"
      }}
    ]
  }}
}}
```

## 特別注意

1. `source_spans[].quote` 不可含 `...`
2. 若一筆事件難以被一個 quote 完整代表，請保留 `description`，但仍要放至少 1 個可定位的 primary quote
3. 事件數量可多於 v3.9，因為複合事件應優先拆分
4. 請直接輸出 JSON，不要加任何說明文字

## 判決書原文

{judgment_text}
"""

    return prompt

