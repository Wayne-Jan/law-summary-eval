#!/usr/bin/env python3
"""Build static JSON data for GitHub Pages site.

Outputs JSON in the EXACT same format as /api/view/{case} returns,
so the frontend HTML can be copied from viz/static/view.html with
minimal changes (only swap fetch URLs to static paths).

All output filenames use ASCII slugs (case_001, case_002, ...) to avoid
GitHub Pages issues with non-ASCII filenames.

Usage:
    python site/build.py
"""

import json
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from modules.extraction_v3_8.alignment_engine import smart_align
PREDICTIONS = os.path.join(PROJECT_ROOT, "data", "predictions")
CHUNKS_DIR = os.path.join(PROJECT_ROOT, "data", "chunks_20260105")
EXTRACTIONS_DIR_V39 = os.path.join(PROJECT_ROOT, "data", "extractions_v3.9")
SOURCE_TEXT_DIR = os.path.join(PROJECT_ROOT, "原始判決書")
GT_SUMMARY_DIR = os.path.join(PROJECT_ROOT, "摘要 (ground_truth)")
SITE_DATA = os.path.join(PROJECT_ROOT, "site", "data")

# Must match server.py VIEWER_CONDITION_LABELS / VIEWER_CONDITION_GROUPS
CONDITION_LABELS = {
    "claude_afg_v5.1": "Claude-A",
    "ablation_no_afg": "Claude-B",
    "ablation_no_react": "Claude-C",
    "opensource_afg_v11": "OpenSource-A",
    "opensource_afg_v11_no_afg": "OpenSource-B",
    "opensource_afg_v11_no_react": "OpenSource-C",
    "baseline_claude-haiku": "Baseline-Haiku",
    "baseline_claude-sonnet": "Baseline-Sonnet",
    "baseline_gemini-3.0-flash": "Baseline-Gemini 3.0 Flash",
    "baseline_gemini-3.1-pro": "Baseline-Gemini 3.1 Pro",
    "baseline_gpt-5.3": "Baseline-GPT 5.3",
    "baseline_gpt-5.4-thinking": "Baseline-GPT 5.4 Thinking",
    "baseline_ollama_cogito-2.1-671b-cloud": "Baseline-Cogito 2.1",
    "baseline_ollama_deepseek-v3.1-671b-cloud": "Baseline-DeepSeek v3.1",
    "baseline_ollama_glm-5-cloud": "Baseline-GLM 5",
    "baseline_ollama_gpt-oss-120b-cloud": "Baseline-GPT-OSS",
    "baseline_ollama_kimi-k2.5-cloud": "Baseline-Kimi K2.5",
    "baseline_ollama_mistral-large-3-675b-cloud": "Baseline-Mistral Large 3",
    "baseline_ollama_qwen3-next-80b-cloud": "Baseline-Qwen3 Next",
    "baseline_ollama_qwen3.5-397b-cloud": "Baseline-Qwen3.5",
}

# Display order: Claude → OpenSource → Baselines
CONDITION_ORDER = [
    "claude_afg_v5.1",
    "ablation_no_afg",
    "ablation_no_react",
    "opensource_afg_v11",
    "opensource_afg_v11_no_afg",
    "opensource_afg_v11_no_react",
    "baseline_claude-haiku",
    "baseline_claude-sonnet",
    "baseline_gemini-3.0-flash",
    "baseline_gemini-3.1-pro",
    "baseline_gpt-5.3",
    "baseline_gpt-5.4-thinking",
    "baseline_ollama_cogito-2.1-671b-cloud",
    "baseline_ollama_deepseek-v3.1-671b-cloud",
    "baseline_ollama_glm-5-cloud",
    "baseline_ollama_gpt-oss-120b-cloud",
    "baseline_ollama_kimi-k2.5-cloud",
    "baseline_ollama_mistral-large-3-675b-cloud",
    "baseline_ollama_qwen3-next-80b-cloud",
    "baseline_ollama_qwen3.5-397b-cloud",
]

CONDITION_GROUPS = {
    "claude_afg_v5.1": "商用模型",
    "ablation_no_afg": "商用模型",
    "ablation_no_react": "商用模型",
    "baseline_claude-haiku": "商用模型",
    "baseline_claude-sonnet": "商用模型",
    "baseline_gemini-3.0-flash": "商用模型",
    "baseline_gemini-3.1-pro": "商用模型",
    "baseline_gpt-5.3": "商用模型",
    "baseline_gpt-5.4-thinking": "商用模型",
    "baseline_ollama_cogito-2.1-671b-cloud": "開源模型",
    "baseline_ollama_deepseek-v3.1-671b-cloud": "開源模型",
    "baseline_ollama_glm-5-cloud": "開源模型",
    "baseline_ollama_gpt-oss-120b-cloud": "開源模型",
    "baseline_ollama_kimi-k2.5-cloud": "開源模型",
    "baseline_ollama_mistral-large-3-675b-cloud": "開源模型",
    "baseline_ollama_qwen3-next-80b-cloud": "開源模型",
    "baseline_ollama_qwen3.5-397b-cloud": "開源模型",
    "opensource_afg_v11": "開源模型",
    "opensource_afg_v11_no_afg": "開源模型",
    "opensource_afg_v11_no_react": "開源模型",
}

SECTION_FILES = [
    ("facts", "section_01_facts.txt", "（一）公訴事實與起訴意旨"),
    ("defense", "section_02_defense.txt", "（二）被告回應"),
    ("opinions", "section_03_opinions.txt", "（三）鑑定意見"),
    ("verdict", "section_04_verdict.txt", "（四）判決結果"),
    ("reasoning", "section_05_reasoning.txt", "（五）判決理由"),
]


def read_text(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_sections(case_dir):
    """Load sections in the same format as /api/view/{case} returns."""
    sections = []
    # Try workspace/sections first, then root
    section_dir = os.path.join(case_dir, "workspace", "sections")
    if not os.path.isdir(section_dir):
        section_dir = case_dir

    for section_id, filename, default_title in SECTION_FILES:
        file_path = os.path.join(section_dir, filename)
        if os.path.exists(file_path):
            raw = read_text(file_path).strip()
            body = raw
            # Strip section title from first line if present (same as server.py)
            first_line, _, remainder = raw.partition("\n")
            if first_line.strip().startswith("（") and "）" in first_line:
                body = remainder.strip()
            sections.append({"id": section_id, "title": default_title, "content": body})
        else:
            sections.append({"id": section_id, "title": default_title, "content": ""})

    return sections


def load_chunks_for_case(case_name, case_dir):
    """Build CH_XX -> content mapping, same logic as server.py."""
    chunks = {}

    # 1. Try citations.txt (pre-built)
    citations_txt_path = os.path.join(case_dir, "citations.txt")
    if os.path.exists(citations_txt_path):
        current_alias = None
        current_content = []
        for line in read_text(citations_txt_path).split("\n"):
            if line.startswith("=== CH_") and line.endswith(" ==="):
                if current_alias and current_content:
                    chunks[current_alias] = "\n".join(current_content).strip()
                current_alias = line.replace("=== ", "").replace(" ===", "")
                current_content = []
            elif current_alias:
                current_content.append(line)
        if current_alias and current_content:
            chunks[current_alias] = "\n".join(current_content).strip()

    # 2. Build citations_map from meta/citations.json or chunk_alias_mapping
    citations_map = {}
    cit_json = read_json(os.path.join(case_dir, "meta", "citations.json"))
    if cit_json:
        citations_map = cit_json.get("alias_to_chunk_id", {})

    if not citations_map:
        # Try chunk_alias_mapping.json
        mapping = read_json(
            os.path.join(case_dir, "workspace", "chunk_alias_mapping.json")
        )
        if mapping:
            for alias, val in mapping.items():
                if isinstance(val, dict):
                    citations_map[alias] = val.get("original_id", "")
                else:
                    citations_map[alias] = val

    # 3. Fallback: positional mapping from chunks JSON
    chunks_json_path = os.path.join(CHUNKS_DIR, f"{case_name}.json")
    if not citations_map and os.path.exists(chunks_json_path):
        raw = read_json(chunks_json_path)
        chunk_list = raw if isinstance(raw, list) else raw.get("chunks", [])
        for idx, chunk in enumerate(chunk_list, start=1):
            alias = f"CH_{idx:02d}"
            chunk_id = chunk.get("chunk_id", "")
            if chunk_id:
                citations_map[alias] = chunk_id

    # 4. Fill missing chunks from raw chunks JSON
    if citations_map and os.path.exists(chunks_json_path):
        missing = set(citations_map.keys()) - set(chunks.keys())
        if missing:
            raw = read_json(chunks_json_path)
            chunk_list = raw if isinstance(raw, list) else raw.get("chunks", [])
            id_to_content = {
                c.get("chunk_id", ""): c.get("content", "") for c in chunk_list
            }
            for alias in missing:
                chunk_id = citations_map.get(alias, "")
                if chunk_id in id_to_content:
                    chunks[alias] = id_to_content[chunk_id]

    # 5. Last resort: if still no chunks, use positional content
    if not chunks and os.path.exists(chunks_json_path):
        raw = read_json(chunks_json_path)
        chunk_list = raw if isinstance(raw, list) else raw.get("chunks", [])
        for idx, chunk in enumerate(chunk_list, start=1):
            chunks[f"CH_{idx:02d}"] = chunk.get("content", "")

    return chunks, citations_map


def load_metadata(case_dir):
    md = read_json(os.path.join(case_dir, "meta", "metadata.json"))
    return md or {}


def extract_eval_summary(eval_dir):
    report = read_json(os.path.join(eval_dir, "report.json"))
    if report and "scores" in report:
        return report["scores"]
    result = {}
    rule = read_json(os.path.join(eval_dir, "rule_metrics.json"))
    if rule and "_summary" in rule:
        result["rule_based_avg"] = rule["_summary"].get("rule_based_avg")
    fact = read_json(os.path.join(eval_dir, "fact_recall.json"))
    if fact:
        result["fact_recall_avg"] = fact.get("overall_fact_recall")
    quality = read_json(os.path.join(eval_dir, "quality.json"))
    if quality and "overall" in quality:
        result["quality_avg"] = quality["overall"].get("overall_quality")
    faith = read_json(os.path.join(eval_dir, "faithfulness.json"))
    if faith:
        result["faithfulness"] = faith.get("faithfulness_score")
    return result if result else None


def parse_gt_sections(raw_text):
    """Parse GT summary into sections — copied from server.py _parse_gt_sections."""
    section_map = {
        "一": "facts",
        "二": "defense",
        "三": "opinions",
        "四": "verdict",
        "五": "reasoning",
    }
    strip_labels = {
        "facts": ["公訴事實與起訴意旨", "自訴事實與意旨", "自訴事實與自訴意旨"],
        "defense": ["被告回應"],
        "opinions": ["鑑定意見"],
        "verdict": ["判決結果"],
        "reasoning": ["判決理由"],
    }
    default_result = {
        "facts": raw_text.strip(),
        "defense": "",
        "opinions": "",
        "verdict": "",
        "reasoning": "",
    }

    marker_pattern = re.compile(
        r"^\s*[（(]\s*([一二三四五])\s*[）)]\s*(.*)$", re.MULTILINE
    )
    marker_matches = list(marker_pattern.finditer(raw_text))

    ordered_sections = []
    seen = set()
    for match in marker_matches:
        section_id = section_map.get(match.group(1))
        if not section_id or section_id in seen:
            continue
        ordered_sections.append((section_id, match))
        seen.add(section_id)
        if len(ordered_sections) == 5:
            break

    if len(ordered_sections) < 5:
        return default_result

    def _strip_leading_label(sid, text):
        cleaned = text.lstrip()
        for label in strip_labels.get(sid, []):
            cleaned = re.sub(
                rf"^\s*{re.escape(label)}\s*([：:、，。]?\s*)?",
                "",
                cleaned,
                count=1,
            )
        return cleaned.strip()

    ordered_sections.sort(key=lambda x: x[1].start())
    result = {
        "facts": "",
        "defense": "",
        "opinions": "",
        "verdict": "",
        "reasoning": "",
    }

    for idx, (section_id, match) in enumerate(ordered_sections):
        start = match.start(2)
        end = (
            ordered_sections[idx + 1][1].start()
            if idx + 1 < len(ordered_sections)
            else len(raw_text)
        )
        raw_block = raw_text[start:end]
        result[section_id] = _strip_leading_label(section_id, raw_block)

    return result


def build():
    os.makedirs(SITE_DATA, exist_ok=True)

    # Collect all conditions and cases
    all_conditions = {}  # cond -> {case -> case_dir}
    all_cases = set()

    for cond in sorted(os.listdir(PREDICTIONS)):
        cond_dir = os.path.join(PREDICTIONS, cond)
        if not os.path.isdir(cond_dir) or cond.startswith(".") or cond in ("Old",):
            continue
        cases = {}
        for case in sorted(os.listdir(cond_dir)):
            case_dir = os.path.join(cond_dir, case)
            if not os.path.isdir(case_dir):
                continue
            if not os.path.exists(os.path.join(case_dir, "summary_clean.txt")):
                continue
            cases[case] = case_dir
            all_cases.add(case)
        if cases:
            all_conditions[cond] = cases

    all_cases = sorted(all_cases)
    # Sort conditions by CONDITION_ORDER, then alphabetically for unlisted ones
    order_map = {c: i for i, c in enumerate(CONDITION_ORDER)}
    cond_list = sorted(all_conditions.keys(), key=lambda c: (order_map.get(c, 999), c))

    # Build case_name -> slug mapping (ASCII-safe filenames for GitHub Pages)
    case_slugs = {}
    for idx, case in enumerate(all_cases, start=1):
        case_slugs[case] = f"case_{idx:03d}"

    # Also build slug mapping for ALL GT cases (may include cases not in predictions)
    gt_case_names = []
    if os.path.isdir(GT_SUMMARY_DIR):
        for fname in sorted(os.listdir(GT_SUMMARY_DIR)):
            if fname.startswith("摘要_") and fname.endswith(".txt"):
                gt_case_names.append(fname[len("摘要_") : -len(".txt")])
    # Add GT-only cases to slug map
    next_idx = len(all_cases) + 1
    for gt_case in gt_case_names:
        if gt_case not in case_slugs:
            case_slugs[gt_case] = f"case_{next_idx:03d}"
            next_idx += 1

    # For each case, find which conditions are available
    case_to_conditions = {}
    for case in all_cases:
        case_to_conditions[case] = [
            c for c in cond_list if case in all_conditions.get(c, {})
        ]

    # Build per-condition per-case JSON (same format as /api/view/{case})
    manifest_conditions = {}
    for cond in cond_list:
        label = CONDITION_LABELS.get(cond, cond)
        group = CONDITION_GROUPS.get(cond, "other")
        cases = all_conditions[cond]
        eval_count = 0

        cond_out_dir = os.path.join(SITE_DATA, cond)
        os.makedirs(cond_out_dir, exist_ok=True)

        for case, case_dir in cases.items():
            sections = load_sections(case_dir)
            chunks, citations_map = load_chunks_for_case(case, case_dir)
            metadata = load_metadata(case_dir)

            eval_dir = os.path.join(case_dir, "eval")
            eval_scores = (
                extract_eval_summary(eval_dir) if os.path.isdir(eval_dir) else None
            )
            if eval_scores:
                eval_count += 1

            # Build response in EXACT /api/view/{case} format
            view_data = {
                "case_name": case,
                "condition": cond,
                "available_conditions": case_to_conditions.get(case, []),
                "condition_labels": CONDITION_LABELS,
                "condition_groups": CONDITION_GROUPS,
                "sections": sections,
                "citations_map": citations_map,
                "chunks": chunks,
                "verdict_type": metadata.get("verdict_type", "unknown"),
                "complexity_score": metadata.get("complexity_score", 0),
                "eval": eval_scores,
            }

            slug = case_slugs[case]
            out_path = os.path.join(cond_out_dir, slug + ".json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(view_data, f, ensure_ascii=False, indent=1)

        manifest_conditions[cond] = {
            "label": label,
            "group": group,
            "case_count": len(cases),
            "eval_count": eval_count,
        }
        print(f"  {cond:45s}  {len(cases):2d} cases  {eval_count:2d} evals")

    # Build cases list (same as /api/view-cases)
    cases_json_path = os.path.join(SITE_DATA, "cases.json")
    with open(cases_json_path, "w", encoding="utf-8") as f:
        json.dump(all_cases, f, ensure_ascii=False, indent=1)

    # Build GT data (same format as /api/view-gt/{case})
    if os.path.isdir(GT_SUMMARY_DIR):
        gt_out_dir = os.path.join(SITE_DATA, "gt")
        os.makedirs(gt_out_dir, exist_ok=True)
        gt_count = 0
        for gt_case in gt_case_names:
            raw = read_text(os.path.join(GT_SUMMARY_DIR, f"摘要_{gt_case}.txt"))
            parsed = parse_gt_sections(raw)
            gt_data = {
                "case_name": gt_case,
                "sections": [
                    {"id": sid, "title": title, "content": parsed.get(sid, "")}
                    for sid, _, title in SECTION_FILES
                ],
            }
            slug = case_slugs[gt_case]
            with open(
                os.path.join(gt_out_dir, slug + ".json"), "w", encoding="utf-8"
            ) as f:
                json.dump(gt_data, f, ensure_ascii=False, indent=1)
            gt_count += 1
        print(f"  {'_gt (teacher summaries)':45s}  {gt_count:2d} cases")

    # Build timeline data (extraction v3.9 only)
    tl_out_dir = os.path.join(SITE_DATA, "timeline")
    os.makedirs(tl_out_dir, exist_ok=True)
    tl_count = 0
    tl_realign_count = 0
    extraction_dir = EXTRACTIONS_DIR_V39
    if not os.path.isdir(extraction_dir):
        print("  WARNING: extraction v3.9 directory not found, skipping timeline")
        extraction_dir = None

    for case_name in sorted(os.listdir(extraction_dir)) if extraction_dir else []:
        master_path = os.path.join(extraction_dir, case_name, "master.json")
        if not os.path.exists(master_path):
            continue
        master = read_json(master_path)
        if not isinstance(master, dict):
            continue
        tl_result = master.get("timeline", master.get("timeline_result", {}))
        events = tl_result.get("timeline", tl_result.get("events", []))
        if not events:
            continue
        # Load chunks for this case (used by timeline source panel)
        chunk_path = os.path.join(CHUNKS_DIR, case_name + ".json")
        chunks_data = []
        if os.path.exists(chunk_path):
            raw_chunks = read_json(chunk_path)
            if isinstance(raw_chunks, list):
                chunks_data = [
                    {
                        "chunk_id": c.get("chunk_id", ""),
                        "title": c.get("title", ""),
                        "content": c.get("content", ""),
                        "start_char": c.get("start_char", 0),
                        "end_char": c.get("end_char", 0),
                    }
                    for c in raw_chunks
                ]
        # Realign char_start/char_end using smart_align against source text
        source_path = os.path.join(SOURCE_TEXT_DIR, case_name + ".txt")
        if os.path.exists(source_path):
            source_text = open(source_path, encoding="utf-8").read()
            realigned = 0
            for evt in events:
                txt = (evt.get("extraction_text") or "").strip()
                if not txt:
                    continue
                hit = smart_align(source_text, txt)
                if hit:
                    evt["char_start"] = hit.start
                    evt["char_end"] = hit.end
                    realigned += 1
            if realigned:
                tl_realign_count = tl_realign_count + realigned

        # Collect time_gaps (v3.9: top-level or inside timeline_summary)
        tl_summary = tl_result.get("timeline_summary", {})
        time_gaps = tl_result.get("time_gaps", tl_summary.get("time_gaps", []))
        tl_data = {
            "case_name": case_name,
            "events": events,
            "timeline_summary": tl_summary,
            "time_gaps": time_gaps,
            "causation_chain": tl_result.get("causation_chain", []),
            "chunks": chunks_data,
        }
        slug = case_slugs.get(case_name)
        if not slug:
            slug = f"case_{next_idx:03d}"
            case_slugs[case_name] = slug
            next_idx += 1
        with open(
            os.path.join(tl_out_dir, slug + ".json"), "w", encoding="utf-8"
        ) as f:
            json.dump(tl_data, f, ensure_ascii=False, indent=1)
        tl_count += 1
    print(f"  {'timeline (extraction v3.9 only)':45s}  {tl_count:2d} cases  ({tl_realign_count} spans realigned)")

    # Build manifest (includes slug mapping for frontend)
    manifest = {
        "conditions": manifest_conditions,
        "condition_labels": CONDITION_LABELS,
        "condition_groups": CONDITION_GROUPS,
        "cases": all_cases,
        "case_slugs": case_slugs,
    }
    with open(os.path.join(SITE_DATA, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    total = sum(c["case_count"] for c in manifest_conditions.values())
    print(
        f"\n  Total: {len(manifest_conditions)} conditions, {len(all_cases)} cases, {total} data files"
    )


if __name__ == "__main__":
    build()
