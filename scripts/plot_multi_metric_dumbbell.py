#!/usr/bin/env python3
"""Multi-metric distribution chart with Compact Letter Display (CLD).

Each metric gets its own subplot. Within each subplot, every model shows
a horizontal range bar (min→max) with a dot at the median and CLD letters.
Split into commercial / opensource.

CLD uses Wilcoxon signed-rank test + Holm correction (α=0.05).

Usage:
    python3 scripts/plot_multi_metric_dumbbell.py --volume upper
    python3 scripts/plot_multi_metric_dumbbell.py --volume middle
    python3 scripts/plot_multi_metric_dumbbell.py --volume lower
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from statistics import median as stat_median

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import wilcoxon

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 8,
    "axes.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
})

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures" / "multi_metric_profile"

VOLUME_FILES = {
    "upper": DATA_DIR / "eval_metrics_upper.json",
    "middle": DATA_DIR / "eval_metrics_middle.json",
    "lower": DATA_DIR / "eval_metrics_lower.json",
}

METRICS = [
    {
        "key": "fact_recall",
        "label": "Fact Recall",
        "color": "#E74C3C",
        "get_case": lambda c: (c.get("fact_recall") or {}).get("avg"),
    },
    {
        "key": "quality",
        "label": "Quality",
        "color": "#2563eb",
        "get_case": lambda c: (c.get("quality") or {}).get("avg"),
    },
    {
        "key": "faithfulness",
        "label": "Faithfulness",
        "color": "#27AE60",
        "get_case": lambda c: c.get("faithfulness"),
    },
    {
        "key": "rougeL",
        "label": "ROUGE-L",
        "color": "#F39C12",
        "get_case": lambda c: (c.get("rouge_bertscore") or {}).get("rougeL"),
    },
    {
        "key": "bertscore",
        "label": "BERTScore F1",
        "color": "#8E44AD",
        "get_case": lambda c: (c.get("rouge_bertscore") or {}).get("bertscore_f1"),
    },
]

EXCLUDED_CONDITIONS = {
    "baseline_ollama_qwen3-next-80b-cloud",
    "baseline_ollama_nemotron-3-super-cloud",
    "baseline_ollama_mistral-large-3-675b-cloud",
}

# Canonical order matching metrics.html
CANONICAL_ORDER_COMMERCIAL = [
    "claude_afg_v5.1",
    "ablation_no_afg",
    "ablation_no_react",
    "baseline_claude-sonnet",
    "baseline_claude-haiku",
    "baseline_gpt-5.4-thinking",
    "baseline_gpt-5.3",
    "baseline_gemini-3.1-pro",
    "baseline_gemini-3.0-flash",
]

CANONICAL_ORDER_OPENSOURCE = [
    "LENS-Full-DeepSeek_v31_writer_gemma4",
    "LENS-Full-DeepSeek_v31",
    "LENS-NoAFG-DeepSeek_v31",
    "LENS-NoReact-DeepSeek_v31",
    "LENS-Full-GPT-OSS_writer_gpt_oss",
    "baseline_ollama_deepseek-v3.1-671b-cloud",
    "baseline_ollama_gemma4-31b-cloud",
    "baseline_ollama_glm-5-cloud",
    "baseline_ollama_gpt-oss-120b-cloud",
    "baseline_ollama_kimi-k2.5-cloud",
    "baseline_ollama_qwen3.5-397b-cloud",
]

DISPLAY_LABELS = {
    "claude_afg_v5.1": "LENS-Haiku-A",
    "ablation_no_afg": "LENS-Haiku-B",
    "ablation_no_react": "LENS-Haiku-C",
    "baseline_claude-sonnet": "Sonnet",
    "baseline_claude-haiku": "Haiku BL",
    "baseline_gpt-5.4-thinking": "GPT-5.4t",
    "baseline_gpt-5.3": "GPT-5.3",
    "baseline_gemini-3.1-pro": "Gemini-3.1",
    "baseline_gemini-3.0-flash": "Gemini-3.0",
    "LENS-Full-DeepSeek_v31_writer_gemma4": "LENS-Gemma 4",
    "LENS-Full-GPT-OSS_writer_gpt_oss": "LENS-GPT-OSS",
    "LENS-Full-DeepSeek_v31": "LENS-DS-A",
    "LENS-NoAFG-DeepSeek_v31": "LENS-DS-B",
    "LENS-NoReact-DeepSeek_v31": "LENS-DS-C",
    "baseline_ollama_deepseek-v3.1-671b-cloud": "DeepSeek V3.1",
    "baseline_ollama_gemma4-31b-cloud": "Gemma 4",
    "baseline_ollama_glm-5-cloud": "GLM 5",
    "baseline_ollama_gpt-oss-120b-cloud": "GPT-OSS",
    "baseline_ollama_kimi-k2.5-cloud": "Kimi K2.5",
    "baseline_ollama_qwen3.5-397b-cloud": "Qwen3.5",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot multi-metric distribution with CLD.")
    parser.add_argument("--volume", choices=sorted(VOLUME_FILES), default="upper")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


# ─── Statistics ──────────────────────────────────────────────────────

def holm_correction(pvalues: list[float]) -> list[float]:
    n = len(pvalues)
    indexed = sorted(enumerate(pvalues), key=lambda x: x[1])
    adjusted = [0.0] * n
    for rank, (orig_idx, p) in enumerate(indexed):
        adjusted[orig_idx] = min(1.0, p * (n - rank))
    for rank in range(1, n):
        orig_idx = indexed[rank][0]
        prev_idx = indexed[rank - 1][0]
        adjusted[orig_idx] = max(adjusted[orig_idx], adjusted[prev_idx])
    return adjusted


def cld_absorption(groups: list[str], sig: list[list[bool]]) -> dict[str, str]:
    n = len(groups)
    columns: list[set[int]] = [set(range(n))]
    for i in range(n):
        for j in range(i + 1, n):
            if not sig[i][j]:
                continue
            shared = [k for k, col in enumerate(columns) if i in col and j in col]
            for k in shared:
                col = columns[k]
                if i in col and j in col:
                    columns[k] = col - {j}
                    columns.append(col - {i})
    unique: list[set[int]] = []
    for col in columns:
        if not col:
            continue
        if not any(other is not col and col < other for other in columns):
            if col not in unique:
                unique.append(col)
    unique.sort(key=lambda col: min(col))
    result = {g: "" for g in groups}
    for li, col in enumerate(unique):
        for idx in col:
            result[groups[idx]] += chr(ord("a") + li)
    return result


def compute_cld(
    sorted_conds: list[str],
    cond_data: dict[str, dict],
    getter,
    alpha: float = 0.05,
) -> dict[str, str]:
    # Sort by median descending for CLD computation
    med_sorted = sorted(
        sorted_conds,
        key=lambda ck: stat_median(
            [getter(c) for c in cond_data[ck].values() if getter(c) is not None] or [0]
        ),
        reverse=True,
    )
    n = len(med_sorted)
    raw_p: dict[tuple[int, int], float] = {}
    for a, b in combinations(range(n), 2):
        ck_a, ck_b = med_sorted[a], med_sorted[b]
        common = set(cond_data[ck_a].keys()) & set(cond_data[ck_b].keys())
        pairs = [(getter(cond_data[ck_a][s]), getter(cond_data[ck_b][s])) for s in common]
        pairs = [(va, vb) for va, vb in pairs if va is not None and vb is not None]
        if len(pairs) < 10 or all(va == vb for va, vb in pairs):
            raw_p[(a, b)] = 1.0
        else:
            _, p = wilcoxon([p[0] for p in pairs], [p[1] for p in pairs])
            raw_p[(a, b)] = p
    keys = list(raw_p.keys())
    adj = holm_correction([raw_p[k] for k in keys])
    sig = [[False] * n for _ in range(n)]
    for i, (a, b) in enumerate(keys):
        if adj[i] < alpha:
            sig[a][b] = True
            sig[b][a] = True
    cld = cld_absorption(med_sorted, sig)
    return {ck: cld[ck] for ck in sorted_conds}


# ─── Plotting ────────────────────────────────────────────────────────

def compute_shared_xlims(
    all_cond_data: dict[str, dict],
) -> list[tuple[float, float]]:
    """Compute xlim for each metric across ALL conditions (both groups)."""
    xlims: list[tuple[float, float]] = []
    for m in METRICS:
        getter = m["get_case"]
        mk = m["key"]
        all_vals: list[float] = []
        for cases in all_cond_data.values():
            all_vals.extend(v for c in cases.values() if (v := getter(c)) is not None)
        if all_vals:
            data_min, data_max = min(all_vals), max(all_vals)
            span = data_max - data_min if data_max > data_min else 0.1
            pad = span * (0.04 if mk == "rougeL" else 0.08)
            xlim_lo = max(0, data_min - pad)
            right_pad = pad * 2.0
            xlim_hi = min(5.05 if mk == "quality" else 1.05, data_max + right_pad)
            # Round to nice 0.05 grid
            xlim_lo = float(np.floor(xlim_lo * 20) / 20)
            xlim_hi = float(np.ceil(xlim_hi * 20) / 20)
        else:
            xlim_lo, xlim_hi = 0.0, 1.0
        xlims.append((xlim_lo, xlim_hi))
    return xlims


def plot_group(
    sorted_conds: list[str],
    cond_data: dict[str, dict],
    title: str,
    output_path: Path,
    dpi: int,
    shared_xlims: list[tuple[float, float]] | None = None,
    shared_clds: list[dict[str, str]] | None = None,
) -> None:
    if not sorted_conds:
        print(f"  (skipped — no data for {title})")
        return

    n_models = len(sorted_conds)
    n_metrics = len(METRICS)
    fig_w = 2.95 * n_metrics
    fig_h = max(4.0, 0.55 * n_models + 1.5)
    fig, axes = plt.subplots(
        1,
        n_metrics,
        figsize=(fig_w, fig_h),
        sharey=True,
        gridspec_kw={"wspace": 0.0},
    )

    for col, m in enumerate(METRICS):
        ax = axes[col]
        getter = m["get_case"]
        mcolor = m["color"]
        mk = m["key"]
        cld_map = shared_clds[col] if shared_clds else compute_cld(sorted_conds, cond_data, getter)

        xlim_lo, xlim_hi = shared_xlims[col] if shared_xlims else (0.0, 1.0)

        for i, ck in enumerate(sorted_conds):
            vals = [getter(c) for c in cond_data[ck].values() if getter(c) is not None]
            if not vals:
                continue
            vmin, vmax, vmed = min(vals), max(vals), stat_median(vals)

            # Range bar
            ax.plot(
                [vmin, vmax], [i, i],
                color=mcolor, linewidth=2.5, alpha=0.55, zorder=1, solid_capstyle="round",
            )
            # Min/max caps
            for ep in [vmin, vmax]:
                ax.plot([ep, ep], [i - 0.15, i + 0.15], color=mcolor, linewidth=1.2, alpha=0.5, zorder=2)
            # Median dot
            ax.scatter(vmed, i, s=50, c=mcolor, marker="o", edgecolors="white", linewidths=0.8, zorder=4)
            # Median label
            fmt = f"{vmed:.2f}" if mk == "quality" else f"{vmed:.3f}"
            ax.annotate(
                fmt, xy=(vmed, i), xytext=(0, -11), textcoords="offset points",
                ha="center", va="top", fontsize=6.5, color=mcolor, fontweight="bold",
            )
            # CLD letter at max cap
            letter = cld_map.get(ck, "")
            ax.annotate(
                letter, xy=(vmax, i), xytext=(-4, 0), textcoords="offset points",
                ha="right", va="center", fontsize=8, color="#374151", fontweight="bold",
                fontstyle="italic",
            )

        ax.set_yticks(list(range(n_models)))
        if col == 0:
            ax.set_yticklabels([DISPLAY_LABELS.get(ck, ck) for ck in sorted_conds], fontsize=9)
        ax.invert_yaxis()
        ax.set_title(m["label"], fontsize=10, fontweight="600", color=mcolor, pad=8)
        ax.set_xlim(xlim_lo, xlim_hi)
        ax.xaxis.grid(True, linestyle="-", alpha=0.3, linewidth=0.6)
        ax.set_axisbelow(True)

    fig.suptitle(title, fontsize=12, fontweight="bold", color="#1e293b", y=1.02)
    fig.subplots_adjust(left=0.085, right=0.995, top=0.90, bottom=0.08, wspace=0.0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, facecolor="white")
    plt.close(fig)
    print(output_path)


def main() -> int:
    args = parse_args()
    snapshot = json.loads(VOLUME_FILES[args.volume].read_text(encoding="utf-8"))
    out_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    conditions = snapshot.get("conditions", {})

    # Collect case data for ALL non-excluded conditions to compute shared xlims + CLD
    all_canonical = CANONICAL_ORDER_COMMERCIAL + CANONICAL_ORDER_OPENSOURCE
    all_conds = [ck for ck in all_canonical if ck in conditions and ck not in EXCLUDED_CONDITIONS]
    all_cond_data = {ck: conditions[ck].get("cases") or {} for ck in all_conds}
    all_cond_data = {ck: v for ck, v in all_cond_data.items() if v}
    all_conds_with_data = [ck for ck in all_conds if ck in all_cond_data]

    shared_xlims = compute_shared_xlims(all_cond_data)
    shared_clds = [
        compute_cld(all_conds_with_data, all_cond_data, m["get_case"])
        for m in METRICS
    ]

    for group_name, canonical_order, group_label in [
        ("commercial", CANONICAL_ORDER_COMMERCIAL, "Commercial"),
        ("opensource", CANONICAL_ORDER_OPENSOURCE, "Open-Source"),
    ]:
        sorted_conds = [ck for ck in canonical_order if ck in conditions and ck not in EXCLUDED_CONDITIONS]
        cond_data = {ck: conditions[ck].get("cases") or {} for ck in sorted_conds}
        sorted_conds = [ck for ck in sorted_conds if cond_data[ck]]

        title = f"Per-Case Metric Distribution — {group_label}  ({args.volume.title()})"
        out_path = out_dir / f"{args.volume}_multi_metric_{group_name}_cld.png"
        plot_group(
            sorted_conds,
            cond_data,
            title,
            out_path,
            args.dpi,
            shared_xlims,
            shared_clds,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
