#!/usr/bin/env python3
"""Build volume-specific metrics JSON for the static metrics page.

This keeps the existing frontend schema intact and emits:
  - data/eval_metrics_upper.json
  - data/eval_metrics_middle.json
  - data/eval_metrics_lower.json

All three volumes are rebuilt from the source evaluation artifacts in
Law_extraction_refactor.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import OrderedDict
from pathlib import Path
from statistics import mean


REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data"
CURRENT_METRICS = DATA_DIR / "eval_metrics.json"
SOURCE_ROOT = Path("/mnt/d/Law_extraction_refactor")
PREDICTIONS_ROOT = SOURCE_ROOT / "data" / "predictions"
METRIC_EVAL_ROOT = SOURCE_ROOT / "experiments" / "metric_eval_pilot" / "outputs"
VOLUMES = ("上冊", "中冊", "下冊")
VOLUME_TO_FILE = {
    "上冊": "eval_metrics_upper.json",
    "中冊": "eval_metrics_middle.json",
    "下冊": "eval_metrics_lower.json",
}
EXTRA_CONDITIONS = OrderedDict(
    [
        ("opensource_afg_v11_5", {"label": "LENS-GPT-OSS-A", "group": "開源模型"}),
        ("opensource_afg_v11_5_no_react", {"label": "LENS-GPT-OSS-B", "group": "開源模型"}),
        ("opensource_afg_v11_5_no_afg", {"label": "LENS-GPT-OSS-C", "group": "開源模型"}),
        ("opensource_afg_v11_5_writer_nemotron_super", {"label": "LENS-Nemotron Super-A", "group": "開源模型"}),
        ("opensource_afg_v11_5_no_react_writer_nemotron_super", {"label": "LENS-Nemotron Super-B", "group": "開源模型"}),
        ("opensource_afg_v11_5_no_afg_writer_nemotron_super", {"label": "LENS-Nemotron Super-C", "group": "開源模型"}),
        ("baseline_ollama_nemotron-3-super-cloud", {"label": "Nemotron 3 Super (120B / 12A)", "group": "開源模型"}),
    ]
)

DISPLAY_LABELS = {
    "claude_afg_v5.1": "LENS-Haiku 4.5-A",
    "ablation_no_afg": "LENS-Haiku 4.5-B",
    "ablation_no_react": "LENS-Haiku 4.5-C",
    "opensource_afg_v11_5": "LENS-GPT-OSS-A",
    "opensource_afg_v11_5_no_react": "LENS-GPT-OSS-B",
    "opensource_afg_v11_5_no_afg": "LENS-GPT-OSS-C",
    "opensource_afg_v11_5_writer_nemotron_super": "LENS-Nemotron Super-A",
    "opensource_afg_v11_5_no_react_writer_nemotron_super": "LENS-Nemotron Super-B",
    "opensource_afg_v11_5_no_afg_writer_nemotron_super": "LENS-Nemotron Super-C",
    "baseline_claude-haiku": "Claude Haiku 4.5",
    "baseline_claude-sonnet": "Claude Sonnet 4.6",
    "baseline_gpt-5.3": "GPT-5.3 Instant",
    "baseline_gpt-5.4-thinking": "GPT-5.4 Thinking",
    "baseline_gemini-3.0-flash": "Gemini 3.0 Flash",
    "baseline_gemini-3.1-pro": "Gemini 3.1 Pro",
    "baseline_ollama_cogito-2.1-671b-cloud": "Cogito 2.1 (671B / 37A)",
    "baseline_ollama_deepseek-v3.1-671b-cloud": "DeepSeek V3.1 (671B / 37A)",
    "baseline_ollama_glm-5-cloud": "GLM 5 (744B / 40A)",
    "baseline_ollama_gpt-oss-120b-cloud": "GPT-OSS (117B / 5.1A)",
    "baseline_ollama_kimi-k2.5-cloud": "Kimi K2.5 (1T / 32A)",
    "baseline_ollama_mistral-large-3-675b-cloud": "Mistral Large 3 (675B / 41A)",
    "baseline_ollama_nemotron-3-super-cloud": "Nemotron 3 Super (120B / 12A)",
    "baseline_ollama_qwen3-next-80b-cloud": "Qwen3 Next (80B / 3A)",
    "baseline_ollama_qwen3.5-397b-cloud": "Qwen3.5 (397B / 17A)",
}

RULE_MAP = OrderedDict(
    [
        ("citation_rate", ("CitationRate", "score")),
        ("date_f1", ("DateF1", "score")),
        ("num_f1", ("NumF1", "score")),
        ("verdict_match", ("VerdictMatch", "score")),
        ("institution_attr", ("InstitutionAttr", "score")),
        ("hallucination_rate_rule", ("HallucinationRate_Rule", "score")),
        ("compression_ratio", ("CompressionRatio", "score")),
        ("gt_length_ratio", ("GT_LengthRatio", "score")),
    ]
)
FACT_KEYS = OrderedDict(
    [
        ("timeline_recall", "timeline_recall"),
        ("entity_recall", "entity_recall"),
        ("allegation_coverage", "allegation_coverage"),
        ("defense_recall", "defense_recall"),
        ("expert_opinion_recall", "expert_opinion_recall"),
        ("reasoning_coverage", "reasoning_coverage"),
        ("causation_chain_recall", "causation_chain_recall"),
        ("sentence_accuracy", "sentence_accuracy"),
    ]
)
QUALITY_KEYS = OrderedDict(
    [
        ("fluency", "fluency"),
        ("redundancy", "redundancy"),
        ("coherence", "coherence"),
        ("coverage", "coverage"),
        ("precision", "precision"),
        ("terminology", "terminology"),
        ("structure", "structure"),
        ("scope", "scope"),
        ("compliance", "compliance"),
        ("reasoning", "reasoning"),
        ("timeline_clarity", "timeline_clarity"),
        ("reasoning_completeness", "reasoning_completeness"),
        ("accessibility", "accessibility"),
        ("uncertainty_calibration", "uncertainty_calibration"),
    ]
)


def read_json(path: Path):
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        print(f"[warn] skip invalid json: {path} ({exc})", file=sys.stderr)
        return None


def read_csv_rows(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def safe_float(value):
    if value in (None, "", "null"):
        return None
    return float(value)


def mean_or_none(values):
    vals = [v for v in values if v is not None]
    return mean(vals) if vals else None


def load_existing_template():
    data = read_json(CURRENT_METRICS)
    if not data:
        raise FileNotFoundError(f"Missing template metrics file: {CURRENT_METRICS}")
    conditions = OrderedDict(
        (
            key,
            {
                "label": DISPLAY_LABELS.get(key, value["label"]),
                "group": value["group"],
            },
        )
        for key, value in data["conditions"].items()
    )
    for key, value in EXTRA_CONDITIONS.items():
        conditions.setdefault(key, value)
    return data, list(conditions.items())


def extract_rule(rule_path: Path):
    obj = read_json(rule_path)
    if not obj:
        return None
    result = OrderedDict()
    for out_key, (src_key, field_key) in RULE_MAP.items():
        src = obj.get(src_key) or {}
        result[out_key] = safe_float(src.get(field_key))
    result["avg"] = safe_float(obj.get("_summary", {}).get("rule_based_avg"))
    return result


def extract_fact(fact_path: Path):
    obj = read_json(fact_path)
    if not obj:
        return None
    metrics = obj.get("metrics", {})
    result = OrderedDict()
    for out_key, src_key in FACT_KEYS.items():
        result[out_key] = safe_float((metrics.get(src_key) or {}).get("score"))
    result["avg"] = safe_float(obj.get("overall_fact_recall"))
    return result


def extract_quality(quality_path: Path):
    obj = read_json(quality_path)
    if not obj:
        return None
    overall = obj.get("overall", {})
    result = OrderedDict()
    for out_key, src_key in QUALITY_KEYS.items():
        result[out_key] = safe_float(overall.get(src_key))
    result["avg"] = safe_float(overall.get("overall_quality"))
    return result


def extract_faithfulness(path: Path):
    obj = read_json(path)
    if not obj:
        return None
    return safe_float(obj.get("faithfulness_score"))


def load_rouge_by_case(cond: str, volume: str):
    volume_dir = METRIC_EVAL_ROOT / cond / volume
    summary = read_json(volume_dir / "summary.json")
    per_case = {}
    for row in read_csv_rows(volume_dir / "per_case_scores.csv"):
        if row.get("status") != "ok":
            continue
        case_name = row.get("case")
        if not case_name:
            continue
        per_case[case_name] = {
            "rouge1": safe_float(row.get("rouge1_f")),
            "rouge2": safe_float(row.get("rouge2_f")),
            "rougeL": safe_float(row.get("rougeL_f")),
            "bertscore_p": safe_float(row.get("bertscore_p")),
            "bertscore_r": safe_float(row.get("bertscore_r")),
            "bertscore_f1": safe_float(row.get("bertscore_f1")),
        }
    averages = None
    if summary:
        averages = {
            "rouge1": safe_float(summary.get("rouge1_f_mean")),
            "rouge2": safe_float(summary.get("rouge2_f_mean")),
            "rougeL": safe_float(summary.get("rougeL_f_mean")),
            "bertscore_p": safe_float(summary.get("bertscore_p_mean")),
            "bertscore_r": safe_float(summary.get("bertscore_r_mean")),
            "bertscore_f1": safe_float(summary.get("bertscore_f1_mean")),
        }
    elif per_case:
        keys = ("rouge1", "rouge2", "rougeL", "bertscore_p", "bertscore_r", "bertscore_f1")
        averages = {k: mean_or_none(v.get(k) for v in per_case.values()) for k in keys}
    n = None
    if summary:
        n = summary.get("n_cases_ok")
    elif per_case:
        n = len(per_case)
    return per_case, averages, n


def build_condition_volume(cond: str, label: str, group: str, volume: str):
    pred_dir = PREDICTIONS_ROOT / cond / volume
    if not pred_dir.exists():
        return None

    rouge_cases, rouge_avg, rouge_n = load_rouge_by_case(cond, volume)

    raw_cases = []
    for case_dir in sorted(p for p in pred_dir.iterdir() if p.is_dir()):
        case_name = case_dir.name
        eval_dir = case_dir / "eval"
        rule = extract_rule(eval_dir / "rule_metrics.json")
        fact = extract_fact(eval_dir / "fact_recall.json")
        quality = extract_quality(eval_dir / "quality.json")
        faithfulness = extract_faithfulness(eval_dir / "faithfulness.json")
        rouge = rouge_cases.get(case_name)

        if not any([rule, fact, quality, faithfulness is not None, rouge]):
            continue

        case_payload = OrderedDict()
        case_payload["case_name"] = case_name
        case_payload["rule_based"] = rule or {}
        case_payload["fact_recall"] = fact or {}
        case_payload["quality"] = quality or {}
        case_payload["faithfulness"] = faithfulness
        if rouge:
            case_payload["rouge_bertscore"] = rouge
        raw_cases.append((case_name, case_payload))

    if not raw_cases and not rouge_avg:
        return None

    avg_rule = mean_or_none(case["rule_based"].get("avg") for _, case in raw_cases if case["rule_based"])
    avg_fact = mean_or_none(case["fact_recall"].get("avg") for _, case in raw_cases if case["fact_recall"])
    avg_quality = mean_or_none(case["quality"].get("avg") for _, case in raw_cases if case["quality"])
    avg_faithfulness = mean_or_none(
        case.get("faithfulness") for _, case in raw_cases if case.get("faithfulness") is not None
    )

    payload = OrderedDict()
    payload["label"] = label
    payload["group"] = group
    payload["cases"] = raw_cases
    payload["averages"] = {
        "rule_based_avg": avg_rule,
        "fact_recall_avg": avg_fact,
        "quality_avg": avg_quality,
        "faithfulness_avg": avg_faithfulness,
    }
    if rouge_avg:
        payload["averages"]["rouge_bertscore"] = rouge_avg
        payload["averages"]["rouge_bertscore_n"] = rouge_n
    llm_count = sum(1 for _, c in raw_cases if c["quality"].get("avg") is not None)
    payload["eval_count"] = llm_count
    payload["total_cases"] = len(raw_cases)
    return payload


def build_volume_json(volume: str, condition_templates):
    conditions = OrderedDict()
    all_case_names = []

    for cond, template in condition_templates:
        built = build_condition_volume(cond, template["label"], template["group"], volume)
        if not built:
            continue
        case_names = [name for name, _ in built["cases"]]
        all_case_names.extend(case_names)
        conditions[cond] = built

    if not conditions:
        return None

    preferred_case_list = []
    if "claude_afg_v5.1" in conditions:
        preferred_case_list = [name for name, _ in conditions["claude_afg_v5.1"]["cases"]]
    else:
        preferred_case_list = sorted(set(all_case_names))

    case_list = list(preferred_case_list)
    for name in sorted(set(all_case_names)):
        if name not in case_list:
            case_list.append(name)

    case_slugs = {case_name: f"case_{idx:03d}" for idx, case_name in enumerate(case_list, start=1)}

    for cond_payload in conditions.values():
        cond_payload["cases"] = OrderedDict(
            (case_slugs[name], case_payload) for name, case_payload in cond_payload["cases"]
        )

    return {
        "conditions": conditions,
        "case_slugs": case_slugs,
        "case_list": case_list,
    }


def write_json(path: Path, obj):
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    _, condition_templates = load_existing_template()

    for volume in VOLUMES:
        built = build_volume_json(volume, condition_templates)
        if not built:
            raise RuntimeError(f"No data built for {volume}")
        out_path = DATA_DIR / VOLUME_TO_FILE[volume]
        write_json(out_path, built)
        print(
            f"built   {out_path}  "
            f"({len(built['conditions'])} conditions, {len(built['case_list'])} cases)"
        )

    # Keep the current default file intact. Only create volume-specific files.
    print(f"kept    {CURRENT_METRICS} as-is")


if __name__ == "__main__":
    main()
