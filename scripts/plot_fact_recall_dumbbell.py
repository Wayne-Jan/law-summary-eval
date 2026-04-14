#!/usr/bin/env python3
"""Plot fact-recall dumbbell chart from static eval_metrics JSON snapshots.

Style reference: CEA_draft/figure_generation/gen_knn_mAP_only_dumbbell.py
  - ● Precision (blue), ■ Recall (red), ▲ F1 (green triangle on connector)
  - Values labeled directly on dots
  - F1 triangle + value shown above the connector line midpoint
  - Clean academic style, no top/right spines
  - Outputs commercial + opensource as separate images, one shared legend

Usage:
    python3 scripts/plot_fact_recall_dumbbell.py --volume upper
    python3 scripts/plot_fact_recall_dumbbell.py --volume upper --zoom
    python3 scripts/plot_fact_recall_dumbbell.py --volume upper --zoom --all-conditions
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
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures" / "metric_heatmaps"

VOLUME_FILES = {
    "upper": DATA_DIR / "eval_metrics_upper.json",
    "middle": DATA_DIR / "eval_metrics_middle.json",
    "lower": DATA_DIR / "eval_metrics_lower.json",
}

# Visual config — matching CEA Fig.9 / gen_knn_mAP_only style
COLOR_P = "#2563eb"    # blue  (Precision)
COLOR_R = "#E74C3C"    # red   (Recall)
COLOR_F1 = "#27AE60"   # green (F1)
COLOR_LINE = "#27AE60"
COLOR_LINE_SMALL = "#AAAAAA"
MARKER_SIZE = 75


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot fact recall dumbbell chart.")
    parser.add_argument("--volume", choices=sorted(VOLUME_FILES), default="upper")
    parser.add_argument("--zoom", action="store_true",
                        help="Zoom X axis to 0.4-1.0 to emphasize differences.")
    parser.add_argument("--sort-by", choices=("recall", "f1", "precision", "source"), default="source")
    parser.add_argument("--all-conditions", action="store_true",
                        help="Show all conditions on Y axis, even those without data.")
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def short_label(label: str) -> str:
    text = label.replace("LENS-", "LENS ").strip()
    if " (" in text:
        text = text.split(" (", 1)[0]
    return text


def mean_or_none(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return None if not vals else float(sum(vals) / len(vals))


# --- Group classification ---

# Excluded conditions (too small to be representative)
EXCLUDED_CONDITIONS = {
    "baseline_ollama_qwen3-next-80b-cloud",   # 80B / 3A
    "baseline_ollama_nemotron-3-super-cloud",  # 120B / 12A
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
    "LENS-NoAFG-DeepSeek_v31": 22,
    "LENS-NoReact-DeepSeek_v31": 23,
}


def classify_group(cond_key: str) -> str | None:
    """Return 'commercial', 'opensource', or None (excluded)."""
    if cond_key in EXCLUDED_CONDITIONS:
        return None
    if cond_key in ("claude_afg_v5.1", "ablation_no_afg", "ablation_no_react"):
        return "commercial"  # LENS Haiku = commercial
    if cond_key.startswith("baseline_ollama_"):
        return "opensource"
    if cond_key.startswith("baseline_"):
        return "commercial"
    if cond_key.startswith("LENS-"):
        return "opensource"  # LENS DeepSeek = opensource
    return "opensource"


def group_sort_key(cond_key: str, src_order: int) -> tuple:
    """Match the metrics page ordering within each split."""
    if cond_key in CANONICAL_PRIORITY:
        return (CANONICAL_PRIORITY[cond_key], src_order)
    if cond_key.startswith("baseline_ollama_"):
        return (200, src_order)
    if cond_key.startswith("baseline_"):
        return (100, src_order)
    return (300, src_order)


def build_dataframe(snapshot: dict, target_group: str, sort_by: str,
                    all_conditions: bool = False) -> pd.DataFrame:
    rows = []
    for src_order, (cond_key, cond) in enumerate(snapshot["conditions"].items()):
        grp = classify_group(cond_key)
        if grp is None or grp != target_group:
            continue
        cases = list((cond.get("cases") or {}).values())
        recall = mean_or_none([(c.get("fact_recall") or {}).get("avg") for c in cases])
        precision = mean_or_none([(c.get("fact_recall") or {}).get("precision") for c in cases])
        f1 = mean_or_none([(c.get("fact_recall") or {}).get("f1") for c in cases])
        if recall is None or precision is None or f1 is None:
            if not all_conditions:
                continue
        n = sum(1 for c in cases if (c.get("fact_recall") or {}).get("avg") is not None)
        rows.append({
            "cond_key": cond_key,
            "label": short_label(cond.get("label") or cond_key),
            "recall": recall,
            "precision": precision,
            "f1": f1,
            "n_cases": n,
            "src_order": src_order,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if sort_by == "source":
        df["_sort"] = df.apply(lambda r: group_sort_key(r["cond_key"], r["src_order"]), axis=1)
        df = df.sort_values("_sort", ascending=True).drop(columns="_sort").reset_index(drop=True)
    else:
        df = df.sort_values(sort_by, ascending=True).reset_index(drop=True)
    return df


def plot_single(df: pd.DataFrame, title: str, zoom: bool,
                output_path: Path, dpi: int) -> None:
    if df.empty:
        print(f"  (skipped — no data for {title})")
        return

    n = len(df)
    fig_h = max(3.5, 0.45 * n + 1.0)
    fig, ax = plt.subplots(figsize=(8.5, fig_h))

    for i, (_, row) in enumerate(df.iterrows()):
        p, r, f1 = row["precision"], row["recall"], row["f1"]
        if p is None or r is None or f1 is None:
            continue
        gap = (p - r) * 100

        # connector line
        line_c = COLOR_LINE if gap > 5 else COLOR_LINE_SMALL
        ax.plot([r, p], [i, i], color=line_c, linewidth=2.5,
                alpha=0.5, zorder=1)

        # Recall (square, red)
        ax.scatter(r, i, s=MARKER_SIZE, c=COLOR_R, marker='s',
                   edgecolors='white', linewidths=0.8, zorder=3)
        ax.annotate(f'{r:.4f}', xy=(r, i), xytext=(-6, 0),
                    textcoords='offset points', ha='right', va='center',
                    fontsize=8.5, color=COLOR_R, fontweight='bold')

        # Precision (circle, blue)
        ax.scatter(p, i, s=MARKER_SIZE, c=COLOR_P, marker='o',
                   edgecolors='white', linewidths=0.8, zorder=3)
        ax.annotate(f'{p:.4f}', xy=(p, i), xytext=(6, 0),
                    textcoords='offset points', ha='left', va='center',
                    fontsize=8.5, color=COLOR_P, fontweight='bold')

        # F1 (triangle, green)
        ax.scatter(f1, i, s=MARKER_SIZE, c=COLOR_F1, marker='^',
                   edgecolors='white', linewidths=0.8, zorder=4)
        ax.annotate(f'{f1:.3f}', xy=(f1, i), xytext=(0, 9),
                    textcoords='offset points', ha='center', va='bottom',
                    fontsize=8.5, fontweight='bold', color=COLOR_F1,
                    bbox=dict(boxstyle='round,pad=0.1', facecolor='white',
                              edgecolor='none', alpha=0.9))

    ax.set_yticks(list(range(n)))
    ax.set_yticklabels(df["label"], fontsize=9)
    ax.invert_yaxis()

    x_lo = 0.4 if zoom else 0.0
    ax.set_xlim(x_lo, 1.06)
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
        Line2D([0], [0], marker='o', color='w', markerfacecolor=COLOR_P,
               markersize=10, label='Precision'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor=COLOR_R,
               markersize=10, label='Recall'),
        Line2D([0], [0], marker='^', color='w', markerfacecolor=COLOR_F1,
               markersize=10, label='F1'),
    ]
    fig_leg, ax_leg = plt.subplots(figsize=(2.5, 1.2))
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
    snapshot = load_snapshot(VOLUME_FILES[args.volume])
    out_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    suffix = "_zoom" if args.zoom else ""

    for grp, grp_label in [("commercial", "Commercial"), ("opensource", "Open-Source")]:
        df = build_dataframe(snapshot, grp, args.sort_by, args.all_conditions)
        title = f"Fact Recall — {grp_label}  ({args.volume.title()})"
        out_path = out_dir / f"{args.volume}_fact_recall_dumbbell_{grp}{suffix}.png"
        plot_single(df, title, args.zoom, out_path, args.dpi)

    legend_path = out_dir / f"{args.volume}_fact_recall_dumbbell_legend.png"
    save_legend(legend_path, args.dpi)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
