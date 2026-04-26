#!/usr/bin/env python3
"""Plot recall vs weighted recall dumbbell chart from per-case JSON files.

Trial figure only. Does not affect the existing fact-recall dumbbell script.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pandas as pd

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Helvetica', 'Arial', 'DejaVu Sans'],
    'font.size': 8,
    'axes.labelsize': 9,
    'axes.titlesize': 10,
    'xtick.labelsize': 8,
    'ytick.labelsize': 9,
    'savefig.bbox': 'tight',
    'savefig.pad_inches': 0.03,
    'axes.linewidth': 0.6,
    'axes.spines.top': False,
    'axes.spines.right': False,
})


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures" / "weighted_recall_trials"

VOLUME_MAP = {
    "upper": "上冊",
    "middle": "中冊",
    "lower": "下冊",
}

COLOR_RECALL = "#cbd5e1"
COLOR_WEIGHTED = "#475569"
COLOR_LINE = "#94a3b8"
MARKER_SIZE = 80

EXCLUDED_CONDITIONS = {
    "baseline_ollama_qwen3-next-80b-cloud",
    "baseline_ollama_nemotron-3-super-cloud",
    "baseline_ollama_mistral-large-3-675b-cloud",
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
    "LENS-Full-DeepSeek_v31": 21,
    "LENS-NoReact-DeepSeek_v31": 22,
    "LENS-NoAFG-DeepSeek_v31": 23,
    "LENS-Full-GPT-OSS_writer_gpt_oss": 24,
}

DISPLAY_LABELS = {
    "claude_afg_v5.1": "LENS-Haiku 4.5-A",
    "ablation_no_afg": "LENS-Haiku 4.5-B",
    "ablation_no_react": "LENS-Haiku 4.5-C",
    "LENS-Full-DeepSeek_v31": "LENS-DeepSeek v3.1-A",
    "LENS-NoReact-DeepSeek_v31": "LENS-DeepSeek v3.1-B",
    "LENS-NoAFG-DeepSeek_v31": "LENS-DeepSeek v3.1-C",
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
    "baseline_ollama_gemma4-31b-cloud": "Gemma 4",
    "LENS-Full-DeepSeek_v31_writer_gemma4": "LENS-Gemma 4",
    "LENS-Full-GPT-OSS_writer_gpt_oss": "LENS-GPT-OSS",
    "baseline_ollama_qwen3-next-80b-cloud": "Qwen3 Next (80B / 3A)",
    "baseline_ollama_qwen3.5-397b-cloud": "Qwen3.5 (397B / 17A)",
    "baseline_ollama_nemotron-3-super-cloud": "Nemotron 3 Super (120B / 12A)",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot recall vs weighted recall dumbbell chart.")
    parser.add_argument("--volume", choices=sorted(VOLUME_MAP), default="upper")
    parser.add_argument("--zoom", action="store_true", help="Zoom X axis to 0.4-1.0.")
    parser.add_argument("--sort-by", choices=("weighted_recall", "recall", "gap", "source"), default="source")
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def short_label(label: str) -> str:
    text = label.replace("LENS-", "LENS ").strip()
    if " (" in text:
        text = text.split(" (", 1)[0]
    return text


def mean_or_none(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return None if not vals else float(sum(vals) / len(vals))


def to_scalar(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        avg = value.get("avg")
        if isinstance(avg, (int, float)):
            return float(avg)
    return None


def classify_group(cond_key: str) -> str | None:
    if cond_key in EXCLUDED_CONDITIONS:
        return None
    if cond_key in ("claude_afg_v5.1", "ablation_no_afg", "ablation_no_react"):
        return "commercial"
    if cond_key.startswith("baseline_ollama_"):
        return "opensource"
    if cond_key.startswith("baseline_"):
        return "commercial"
    if cond_key.startswith("LENS-"):
        return "opensource"
    return "opensource"


def group_sort_key(cond_key: str, src_order: int) -> tuple:
    if cond_key in CANONICAL_PRIORITY:
        return (CANONICAL_PRIORITY[cond_key], src_order)
    if cond_key.startswith("baseline_ollama_"):
        return (200, src_order)
    if cond_key.startswith("baseline_"):
        return (100, src_order)
    return (300, src_order)


def build_dataframe(volume: str, target_group: str, sort_by: str) -> pd.DataFrame:
    rows = []
    target_volume = VOLUME_MAP[volume]
    cond_keys = sorted(
        p.name for p in DATA_DIR.iterdir() if p.is_dir() and p.name != "gt" and not p.name.startswith("timeline")
    )

    for src_order, cond_key in enumerate(cond_keys):
        group = classify_group(cond_key)
        if group is None or group != target_group:
            continue
        cond_dir = DATA_DIR / cond_key
        if not cond_dir.exists():
            continue
        recall_values: list[float | None] = []
        weighted_values: list[float | None] = []
        n_cases = 0
        for case_path in sorted(cond_dir.glob("case_*.json")):
            obj = json.loads(case_path.read_text(encoding="utf-8"))
            if str(obj.get("volume") or "") != target_volume:
                continue
            eval_obj = obj.get("eval") or {}
            recall = to_scalar(eval_obj.get("fact_recall"))
            weighted = to_scalar(eval_obj.get("weighted_recall"))
            recall_values.append(recall)
            weighted_values.append(weighted)
            if recall is not None and weighted is not None:
                n_cases += 1
        recall_mean = mean_or_none(recall_values)
        weighted_mean = mean_or_none(weighted_values)
        if recall_mean is None or weighted_mean is None:
            continue
        label = short_label(DISPLAY_LABELS.get(cond_key) or cond_key)
        rows.append({
            "cond_key": cond_key,
            "label": label,
            "recall": recall_mean,
            "weighted_recall": weighted_mean,
            "gap": recall_mean - weighted_mean,
            "n_cases": n_cases,
            "src_order": src_order,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if sort_by == "source":
        df["_sort"] = df.apply(lambda r: group_sort_key(r["cond_key"], r["src_order"]), axis=1)
        df = df.sort_values("_sort", ascending=True).drop(columns="_sort").reset_index(drop=True)
    elif sort_by == "gap":
        df = df.sort_values("gap", ascending=True).reset_index(drop=True)
    else:
        df = df.sort_values(sort_by, ascending=True).reset_index(drop=True)
    return df


def plot_single(df: pd.DataFrame, title: str, zoom: bool, output_path: Path, dpi: int) -> None:
    if df.empty:
        print(f"  (skipped — no data for {title})")
        return

    n = len(df)
    fig_h = max(3.5, 0.45 * n + 1.0)
    fig, ax = plt.subplots(figsize=(8.5, fig_h))

    for i, (_, row) in enumerate(df.iterrows()):
        recall = row["recall"]
        weighted = row["weighted_recall"]
        gap = recall - weighted

        line_c = COLOR_LINE if gap >= 0.03 else "#d1d5db"
        ax.plot([weighted, recall], [i, i], color=line_c, linewidth=2.4, alpha=0.7, zorder=1)

        low_value = min(recall, weighted)
        high_value = max(recall, weighted)

        ax.scatter(recall, i, s=MARKER_SIZE, c=COLOR_RECALL, marker='s',
                   edgecolors='white', linewidths=0.8, zorder=3)
        recall_is_low = recall == low_value
        ax.annotate(f'{recall:.4f}', xy=(recall, i), xytext=(-6, 0) if recall_is_low else (6, 0),
                    textcoords='offset points', ha='right' if recall_is_low else 'left', va='center',
                    fontsize=8.5, color="#64748b", fontweight='bold')

        ax.scatter(weighted, i, s=MARKER_SIZE, c=COLOR_WEIGHTED, marker='s',
                   edgecolors='white', linewidths=0.8, zorder=4)
        weighted_is_low = weighted == low_value
        ax.annotate(f'{weighted:.4f}', xy=(weighted, i), xytext=(-6, 0) if weighted_is_low else (6, 0),
                    textcoords='offset points', ha='right' if weighted_is_low else 'left', va='center',
                    fontsize=8.5, color=COLOR_WEIGHTED, fontweight='bold')

    ax.set_yticks(list(range(n)))
    ax.set_yticklabels(df["label"], fontsize=9)
    ax.invert_yaxis()

    x_lo = 0.4 if zoom else 0.0
    ax.set_xlim(x_lo, 1.03)
    ax.set_xlabel("Score", fontsize=10)
    ax.set_title(title, fontsize=11, pad=10)
    ax.xaxis.grid(True, linestyle='-', alpha=0.15, linewidth=0.5)
    ax.set_axisbelow(True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    fig.savefig(output_path, dpi=dpi, facecolor='white')
    plt.close(fig)
    print(output_path)


def save_legend(output_path: Path, dpi: int) -> None:
    legend_elements = [
        Line2D([0], [0], marker='s', color='w', markerfacecolor=COLOR_RECALL,
               markersize=10, label='Recall'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor=COLOR_WEIGHTED,
               markersize=10, label='Weighted Recall'),
    ]
    fig_leg, ax_leg = plt.subplots(figsize=(3.1, 1.2))
    ax_leg.axis('off')
    ax_leg.legend(handles=legend_elements, loc='center', frameon=True,
                  fancybox=False, edgecolor='#DDDDDD', framealpha=1.0,
                  fontsize=11, handletextpad=0.6, borderpad=0.6,
                  markerscale=1.3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig_leg.savefig(output_path, dpi=dpi, facecolor='white')
    plt.close(fig_leg)
    print(output_path)


def main() -> int:
    args = parse_args()
    out_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    suffix = "_zoom" if args.zoom else ""

    for grp, grp_label in [("commercial", "Commercial"), ("opensource", "Open-Source")]:
        df = build_dataframe(args.volume, grp, args.sort_by)
        title = f"Recall vs Weighted Recall — {grp_label} ({args.volume.title()})"
        out_path = out_dir / f"{args.volume}_weighted_recall_dumbbell_{grp}{suffix}.png"
        plot_single(df, title, args.zoom, out_path, args.dpi)

    legend_path = out_dir / f"{args.volume}_weighted_recall_dumbbell_legend.png"
    save_legend(legend_path, args.dpi)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
