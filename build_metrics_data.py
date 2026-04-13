#!/usr/bin/env python3
"""Build volume-specific metrics JSON for the static metrics page.

This keeps the existing frontend schema intact and emits:
  - data/eval_metrics_upper.json
  - data/eval_metrics_middle.json
  - data/eval_metrics_lower.json

All three volumes are rebuilt from the source evaluation artifacts in
lens-opensource.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import OrderedDict
from pathlib import Path
from statistics import mean
from functools import lru_cache


REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data"
CURRENT_METRICS = DATA_DIR / "eval_metrics.json"
SOURCE_ROOT = Path("/mnt/d/lens-opensource")
PREDICTIONS_ROOT = SOURCE_ROOT / "data" / "predictions"
METRIC_EVAL_ROOT = SOURCE_ROOT / "experiments" / "metric_eval_pilot" / "outputs"
VOLUMES = ("上冊", "中冊", "下冊")
VOLUME_TO_FILE = {
    "上冊": "eval_metrics_upper.json",
    "中冊": "eval_metrics_middle.json",
    "下冊": "eval_metrics_lower.json",
}
# Import shared exclusion list from build.py to keep them in sync
from build import EXCLUDED_CONDITIONS

EXTRA_CONDITIONS = OrderedDict(
    [
        ("LENS-Full-DeepSeek_v31", {"label": "LENS-DeepSeek v3.1-A", "group": "開源模型"}),
        ("LENS-NoAFG-DeepSeek_v31", {"label": "LENS-DeepSeek v3.1-B", "group": "開源模型"}),
        ("LENS-NoReact-DeepSeek_v31", {"label": "LENS-DeepSeek v3.1-C", "group": "開源模型"}),
        ("baseline_ollama_nemotron-3-super-cloud", {"label": "Nemotron 3 Super (120B / 12A)", "group": "開源模型"}),
        ("baseline_ollama_gemma4-31b-cloud", {"label": "Gemma 4 (30.7B)", "group": "開源模型"}),
        ("LENS-Full-DeepSeek_v31_writer_gemma4", {"label": "LENS-Gemma 4", "group": "開源模型"}),
    ]
)

DISPLAY_LABELS = {
    "claude_afg_v5.1": "LENS-Haiku 4.5-A",
    "ablation_no_afg": "LENS-Haiku 4.5-B",
    "ablation_no_react": "LENS-Haiku 4.5-C",
    "LENS-Full-DeepSeek_v31": "LENS-DeepSeek v3.1-A",
    "LENS-NoAFG-DeepSeek_v31": "LENS-DeepSeek v3.1-B",
    "LENS-NoReact-DeepSeek_v31": "LENS-DeepSeek v3.1-C",
    "baseline_claude-haiku": "Claude Haiku 4.5",
    "baseline_claude-sonnet": "Claude Sonnet 4.6",
    "baseline_gpt-5.3": "GPT-5.3 Instant",
    "baseline_gpt-5.4-thinking": "GPT-5.4 Thinking",
    "baseline_gemini-3.0-flash": "Gemini 3.0 Flash",
    "baseline_gemini-3.1-pro": "Gemini 3.1 Pro",
    "baseline_ollama_deepseek-v3.1-671b-cloud": "DeepSeek V3.1 (671B / 37A)",
    "baseline_ollama_glm-5-cloud": "GLM 5 (744B / 40A)",
    "baseline_ollama_gpt-oss-120b-cloud": "GPT-OSS (117B / 5.1A)",
    "baseline_ollama_kimi-k2.5-cloud": "Kimi K2.5 (1T / 32A)",
    "baseline_ollama_gemma4-31b-cloud": "Gemma 4 (30.7B)",
    "LENS-Full-DeepSeek_v31_writer_gemma4": "LENS-Gemma 4",
    "baseline_ollama_qwen3-next-80b-cloud": "Qwen3 Next (80B / 3A)",
    "baseline_ollama_qwen3.5-397b-cloud": "Qwen3.5 (397B / 17A)",
    "baseline_ollama_nemotron-3-super-cloud": "Nemotron 3 Super (120B / 12A)",
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


@lru_cache(maxsize=None)
def load_local_case_eval_index():
    index = {}
    for cond_dir in DATA_DIR.iterdir():
        if not cond_dir.is_dir():
            continue
        if cond_dir.name in {"gt"} or cond_dir.name.startswith("timeline"):
            continue
        for case_path in cond_dir.glob("case_*.json"):
            obj = read_json(case_path)
            if not obj:
                continue
            case_name = obj.get("case_name")
            volume = obj.get("volume")
            if not case_name or not volume:
                continue
            index[(cond_dir.name, volume, case_name)] = obj.get("eval") or {}
    return index


CONDITION_ORDER = [
    # LENS-Haiku (commercial)
    "claude_afg_v5.1",
    "ablation_no_afg",
    "ablation_no_react",
    # Commercial baselines
    "baseline_claude-sonnet",
    "baseline_claude-haiku",
    "baseline_gpt-5.4-thinking",
    "baseline_gpt-5.3",
    "baseline_gemini-3.1-pro",
    "baseline_gemini-3.0-flash",
    # LENS-DeepSeek (open-source)
    "LENS-Full-DeepSeek_v31",
    "LENS-NoAFG-DeepSeek_v31",
    "LENS-NoReact-DeepSeek_v31",
    "LENS-Full-DeepSeek_v31_writer_gemma4",
    # Open-source baselines (alphabetical)
]


def load_existing_template():
    data = read_json(CURRENT_METRICS)
    if not data:
        raise FileNotFoundError(f"Missing template metrics file: {CURRENT_METRICS}")
    # Collect all known conditions from template + EXTRA
    all_conds = OrderedDict()
    for key, value in data["conditions"].items():
        if key in EXCLUDED_CONDITIONS:
            continue
        all_conds[key] = {
            "label": DISPLAY_LABELS.get(key, value["label"]),
            "group": value["group"],
        }
    for key, value in EXTRA_CONDITIONS.items():
        if key in EXCLUDED_CONDITIONS:
            continue
        all_conds.setdefault(key, value)

    # Sort: explicit order first, then remaining open-source alphabetically
    ordered_keys = [k for k in CONDITION_ORDER if k in all_conds]
    remaining = sorted(k for k in all_conds if k not in CONDITION_ORDER)
    conditions = OrderedDict(
        (k, all_conds[k]) for k in ordered_keys + remaining
    )
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
    local_eval = None
    try:
        case_name = fact_path.parents[1].name
        volume = fact_path.parents[2].name
        cond = fact_path.parents[3].name
        local_eval = load_local_case_eval_index().get((cond, volume, case_name)) or {}
    except IndexError:
        local_eval = {}

    obj = read_json(fact_path)
    if obj:
        # Old format: metrics.{key}.score + overall_fact_recall
        metrics = obj.get("metrics", {})
        if metrics:
            result = OrderedDict()
            for out_key, src_key in FACT_KEYS.items():
                result[out_key] = safe_float((metrics.get(src_key) or {}).get("score"))
            result["avg"] = safe_float(obj.get("overall_fact_recall"))
            return result
        # Newer fact_recall.json format: summary.recall/precision/f1
        summary = obj.get("summary", {})
        if summary and summary.get("recall") is not None:
            result = OrderedDict()
            result["avg"] = safe_float(summary.get("recall"))
            result["weighted_recall"] = safe_float(summary.get("weighted_recall"))
            if result["weighted_recall"] is None:
                result["weighted_recall"] = safe_float(local_eval.get("weighted_recall"))
            result["precision"] = safe_float(summary.get("precision"))
            result["f1"] = safe_float(summary.get("f1"))
            return result

    # Fallback: report.json scores
    report = read_json(fact_path.parent / "report.json")
    if report:
        scores = report.get("scores", {})
        if scores.get("fact_recall") is not None:
            result = OrderedDict()
            result["avg"] = safe_float(scores.get("fact_recall"))
            result["weighted_recall"] = safe_float(scores.get("weighted_recall"))
            if result["weighted_recall"] is None:
                result["weighted_recall"] = safe_float(local_eval.get("weighted_recall"))
            result["precision"] = safe_float(scores.get("fact_precision"))
            result["f1"] = safe_float(scores.get("fact_f1"))
            return result

    if local_eval and local_eval.get("fact_recall") is not None:
        result = OrderedDict()
        result["avg"] = safe_float(local_eval.get("fact_recall"))
        result["weighted_recall"] = safe_float(local_eval.get("weighted_recall"))
        result["precision"] = safe_float(local_eval.get("fact_precision"))
        result["f1"] = safe_float(local_eval.get("fact_f1"))
        return result
    return None


def extract_quality(quality_path: Path):
    obj = read_json(quality_path)
    if obj:
        overall = obj.get("overall", {})
        result = OrderedDict()
        for out_key, src_key in QUALITY_KEYS.items():
            result[out_key] = safe_float(overall.get(src_key))
        result["avg"] = safe_float(overall.get("overall_quality"))
        return result

    # Fallback: report.json scores. Only avg is guaranteed in the new summary schema.
    report = read_json(quality_path.parent / "report.json")
    if report:
        scores = report.get("scores", {})
        if scores.get("quality_overall") is not None:
            result = OrderedDict()
            result["avg"] = safe_float(scores.get("quality_overall"))
            return result
    return None


def extract_faithfulness(path: Path):
    obj = read_json(path)
    if obj:
        return safe_float(obj.get("faithfulness_score"))
    # New format: no faithfulness.json, read from report.json
    report_path = path.parent / "report.json"
    report = read_json(report_path)
    if report:
        scores = report.get("scores", {})
        fc = scores.get("faithfulness_combined")
        if isinstance(fc, dict):
            return safe_float(fc.get("score"))
    return None


def load_rouge_by_case(cond: str, volume: str):
    volume_dir = METRIC_EVAL_ROOT / cond / volume
    summary = read_json(volume_dir / "summary.json")
    per_case = {}
    csv_path = volume_dir / "per_case_scores.csv"

    # Fallback: if per-volume CSV doesn't exist, use all_volumes and filter
    if not csv_path.exists():
        csv_path = METRIC_EVAL_ROOT / cond / "all_volumes" / "per_case_scores.csv"
        summary = read_json(METRIC_EVAL_ROOT / cond / "all_volumes" / "summary.json")

    for row in read_csv_rows(csv_path):
        if row.get("status") != "ok":
            continue
        # When using all_volumes fallback, filter by volume column
        row_volume = row.get("volume", "")
        if row_volume and row_volume != volume:
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
    # When using all_volumes fallback, don't use the global summary averages
    # (they cover all volumes); recompute from filtered cases instead.
    if summary and (METRIC_EVAL_ROOT / cond / volume).exists():
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
    if summary and (METRIC_EVAL_ROOT / cond / volume).exists():
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
        if case_name.startswith("_"):
            continue
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
    avg_weighted_fact = mean_or_none(
        case["fact_recall"].get("weighted_recall") for _, case in raw_cases if case["fact_recall"]
    )
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
        "fact_weighted_recall_avg": avg_weighted_fact,
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
