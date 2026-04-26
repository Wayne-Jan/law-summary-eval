#!/usr/bin/env python3
"""Render metrics heatmaps from static eval_metrics JSON snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures" / "metric_heatmaps"

VOLUME_FILES = {
    "upper": DATA_DIR / "eval_metrics_upper.json",
    "middle": DATA_DIR / "eval_metrics_middle.json",
    "lower": DATA_DIR / "eval_metrics_lower.json",
}

METRIC_CONFIG = {
    "rule": {
        "data_key": "rule_based",
        "avg_key": "rule_based_avg",
        "title": "Rule-Based Heatmap",
        "vmin": 0.0,
        "vmax": 1.0,
        "threshold": 0.72,
        "dims": {
            "citation_rate": "Citation Rate",
            "date_f1": "Date F1",
            "num_f1": "Number F1",
            "verdict_match": "Verdict Match",
            "institution_attr": "Institution Attribution",
            "hallucination_rate_rule": "Hallucination (Inv.)",
            "compression_ratio": "Compression Ratio",
            "gt_length_ratio": "GT Length Ratio",
        },
    },
    "quality": {
        "data_key": "quality",
        "avg_key": "quality_avg",
        "title": "Quality Heatmap",
        "vmin": 2.5,
        "vmax": 5.0,
        "threshold": 3.7,
        "ticks": [2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
        "dims": {
            "fluency": "Fluency",
            "redundancy": "Conciseness",
            "coherence": "Coherence",
            "compliance": "Compliance",
            "coverage": "Coverage",
            "precision": "Precision",
            "terminology": "Terminology",
            "structure": "Structure",
            "scope": "Scope",
            "reasoning": "Reasoning",
            "timeline_clarity": "Timeline Clarity",
            "reasoning_completeness": "Reasoning Completeness",
            "accessibility": "Accessibility",
            "uncertainty_calibration": "Uncertainty Calibration",
        },
    },
}

CANONICAL_PRIORITY = {
    "claude_afg_v5.1": 0,
    "ablation_no_afg": 1,
    "ablation_no_react": 2,
    "baseline_claude-sonnet": 10,
    "baseline_claude-haiku": 11,
    "baseline_gpt-5.4-thinking": 12,
    "baseline_gpt-5.3": 13,
    "baseline_gemini-3.1-pro": 14,
    "baseline_gemini-3.0-flash": 15,
    "LENS-Full-DeepSeek_v31_writer_gemma4": 20,
    "LENS-Full-GPT-OSS_writer_gpt_oss": 20.5,
    "LENS-Full-DeepSeek_v31": 21,
    "LENS-NoAFG-DeepSeek_v31": 22,
    "LENS-NoReact-DeepSeek_v31": 23,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot evaluation heatmaps from static metrics JSON.")
    parser.add_argument(
        "--volume",
        choices=sorted(VOLUME_FILES),
        default="upper",
        help="Volume snapshot to use.",
    )
    parser.add_argument(
        "--metric",
        choices=sorted(METRIC_CONFIG),
        required=True,
        help="Metric family to render.",
    )
    parser.add_argument(
        "--group",
        choices=("all", "commercial", "opensource"),
        default="all",
        help="Optional model group filter.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PNG path. Defaults to figures/metric_heatmaps/{volume}_{metric}_{group}.png",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Export resolution.",
    )
    return parser.parse_args()


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_group(group: str) -> str:
    mapping = {
        "commercial": "商用模型",
        "opensource": "開源模型",
    }
    return mapping.get(group, group)


def short_label(label: str) -> str:
    text = label.replace("LENS-", "LENS ").strip()
    if " (" in text:
        text = text.split(" (", 1)[0]
    return text


def canonical_priority(cond_key: str, cond: dict) -> int:
    if cond_key in CANONICAL_PRIORITY:
        return CANONICAL_PRIORITY[cond_key]
    if cond.get("group") == "開源模型" and cond_key.startswith("baseline_ollama_"):
        return 200
    if cond.get("group") == "商用模型":
        return 100
    return 300


def avg_from_cases(cond: dict, data_key: str, field_key: str) -> float | None:
    values = [
        (case_data.get(data_key) or {}).get(field_key)
        for case_data in (cond.get("cases") or {}).values()
    ]
    values = [v for v in values if v is not None]
    if not values:
        return None
    return float(sum(values) / len(values))


def build_matrix(snapshot: dict, metric: str, group: str) -> pd.DataFrame:
    cfg = METRIC_CONFIG[metric]
    conditions = snapshot["conditions"]
    items: list[tuple[str, dict]] = []
    wanted_group = normalize_group(group)

    for cond_key, cond in conditions.items():
        if group != "all" and cond.get("group") != wanted_group:
            continue
        items.append((cond_key, cond))

    items.sort(
        key=lambda item: (
            canonical_priority(item[0], item[1]),
            short_label(item[1].get("label") or item[0]).lower(),
        )
    )

    matrix = {}
    for _, cond in items:
        label = short_label(cond.get("label") or "")
        matrix[label] = {
            dim_label: avg_from_cases(cond, cfg["data_key"], dim_key)
            for dim_key, dim_label in cfg["dims"].items()
        }

    df = pd.DataFrame(matrix).T
    if df.empty:
        return df
    df = df.T
    df = df.dropna(how="all", axis=0)
    df = df.apply(pd.to_numeric, errors="coerce")
    return df


def build_annotation(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    labels = pd.DataFrame("", index=df.index, columns=df.columns)
    for row in df.index:
        for col in df.columns:
            value = df.at[row, col]
            if pd.isna(value):
                labels.at[row, col] = "--"
            elif metric == "quality":
                labels.at[row, col] = f"{value:.1f}"
            elif row == "GT Length Ratio":
                labels.at[row, col] = f"{value:.2f}"
            else:
                labels.at[row, col] = f"{value:.3f}"
    return labels


def plot_heatmap(df: pd.DataFrame, metric: str, volume: str, group: str, output_path: Path, dpi: int) -> None:
    cfg = METRIC_CONFIG[metric]
    if df.empty:
        raise ValueError("No data available for the selected volume/group/metric.")

    annot = build_annotation(df, metric)
    cmap = plt.get_cmap("YlGnBu").copy()
    cmap.set_bad("#f3f4f6")

    width = max(10.0, 0.72 * len(df.columns) + 3.8)
    height = max(4.8, 0.62 * len(df.index) + 2.2)

    plt.figure(figsize=(width, height))
    ax = sns.heatmap(
        df,
        annot=annot,
        fmt="",
        cmap=cmap,
        vmin=cfg["vmin"],
        vmax=cfg["vmax"],
        linewidths=0.6,
        linecolor="#d9e2f3",
        cbar=True,
        annot_kws={"size": 10, "weight": "bold"},
    )

    title_suffix = {
        "upper": "Upper Volume",
        "middle": "Middle Volume",
        "lower": "Lower Volume",
    }[volume]
    group_suffix = {
        "all": "All Models",
        "commercial": "Commercial Models",
        "opensource": "Open-Source Models",
    }[group]
    ax.set_title(f"{cfg['title']} — {title_suffix} ({group_suffix})", fontsize=16, pad=14)
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_xticklabels(ax.get_xticklabels(), rotation=40, ha="right", fontsize=11)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=11)

    cbar = ax.collections[0].colorbar
    cbar.ax.set_ylabel("Score", fontsize=12)
    cbar.ax.tick_params(labelsize=10)
    if cfg.get("ticks"):
        cbar.set_ticks(cfg["ticks"])

    for text in ax.texts:
        raw = text.get_text()
        if raw == "--":
            text.set_color("#94a3b8")
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        text.set_color("white" if value >= cfg["threshold"] else "#0d1b2a")

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close()


def default_output_path(volume: str, metric: str, group: str) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{volume}_{metric}_{group}_heatmap.png"


def main() -> int:
    args = parse_args()
    snapshot = load_snapshot(VOLUME_FILES[args.volume])
    df = build_matrix(snapshot, args.metric, args.group)
    output_path = args.output or default_output_path(args.volume, args.metric, args.group)
    plot_heatmap(df, args.metric, args.volume, args.group, output_path, args.dpi)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
