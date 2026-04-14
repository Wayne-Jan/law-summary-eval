#!/usr/bin/env python3
"""Plot fact coverage & omission severity stacked bar chart.

Each bar = 100% of GT claims, broken into:
  Matched (green) | Partial (light green) | Minor (gray) | Important (amber) | Critical (soft red)

Usage:
    python3 scripts/plot_fact_severity_bar.py --volume upper
    python3 scripts/plot_fact_severity_bar.py --volume upper --all-conditions
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import gridspec

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Helvetica', 'Arial', 'DejaVu Sans'],
    'font.size': 9,
    'axes.linewidth': 0.4,
    'axes.spines.top': False,
    'axes.spines.right': False,
    'axes.spines.left': False,
    'axes.spines.bottom': True,
    'savefig.pad_inches': 0.05,
})

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures" / "weighted_recall_trials"
PRED_DIR = Path("/mnt/d/lens-opensource/data/predictions")
VOLUMES_MAP = {"upper": "上冊", "middle": "中冊", "lower": "下冊"}

# Excluded conditions (too small to be representative)
EXCLUDED_CONDITIONS = {
    "baseline_ollama_qwen3-next-80b-cloud",
    "baseline_ollama_nemotron-3-super-cloud",
    "baseline_ollama_mistral-large-3-675b-cloud",
}

LABELS = {
    "claude_afg_v5.1": "LENS Haiku 4.5-A",
    "ablation_no_afg": "LENS Haiku 4.5-B",
    "ablation_no_react": "LENS Haiku 4.5-C",
    "baseline_claude-haiku": "Claude Haiku 4.5",
    "baseline_claude-sonnet": "Claude Sonnet 4.6",
    "baseline_gemini-3.0-flash": "Gemini 3.0 Flash",
    "baseline_gemini-3.1-pro": "Gemini 3.1 Pro",
    "baseline_gpt-5.3": "GPT-5.3 Instant",
    "baseline_gpt-5.4-thinking": "GPT-5.4 Thinking",
    "LENS-Full-DeepSeek_v31": "LENS DeepSeek v3.1-A",
    "LENS-NoReact-DeepSeek_v31": "LENS DeepSeek v3.1-B",
    "LENS-NoAFG-DeepSeek_v31": "LENS DeepSeek v3.1-C",
    "baseline_ollama_deepseek-v3.1-671b-cloud": "DeepSeek V3.1",
    "baseline_ollama_glm-5-cloud": "GLM 5",
    "baseline_ollama_gpt-oss-120b-cloud": "GPT-OSS",
    "baseline_ollama_kimi-k2.5-cloud": "Kimi K2.5",
    "baseline_ollama_gemma4-31b-cloud": "Gemma 4",
    "LENS-Full-DeepSeek_v31_writer_gemma4": "LENS Gemma 4",
    "baseline_ollama_qwen3.5-397b-cloud": "Qwen3.5",
}

# Colors
C_MATCHED   = "#86efac"
C_PARTIAL   = "#bbf7d0"
C_MINOR     = "#d1d5db"
C_IMPORTANT = "#fcd34d"
C_CRITICAL  = "#fca5a5"

T_MATCHED   = "#065f46"
T_PARTIAL   = "#166534"
T_MINOR     = "#374151"
T_IMPORTANT = "#92400e"
T_CRITICAL  = "#991b1b"

MIN_INSIDE_PCT = 3.0
BREAK_START = 55


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


def group_sort_key(cond_key: str) -> tuple:
    if cond_key in ("claude_afg_v5.1", "ablation_no_afg", "ablation_no_react"):
        return (0, {"claude_afg_v5.1": 0, "ablation_no_afg": 1, "ablation_no_react": 2}[cond_key])
    if cond_key.startswith("LENS-"):
        order = {"LENS-Full-DeepSeek_v31": 0, "LENS-NoReact-DeepSeek_v31": 1, "LENS-NoAFG-DeepSeek_v31": 2}
        return (0, order.get(cond_key, 99))
    if cond_key.startswith("baseline_") and not cond_key.startswith("baseline_ollama_"):
        return (1, cond_key)
    return (1, cond_key)


def collect_data(volume_zh: str, target_group: str, all_conditions: bool) -> list[dict]:
    rows = []
    for cond_dir in sorted(PRED_DIR.iterdir()):
        if not cond_dir.is_dir():
            continue
        cond = cond_dir.name
        grp = classify_group(cond)
        if grp is None or grp != target_group:
            continue
        totals = {"matched": 0, "partial": 0, "missing": 0,
                  "critical": 0, "important": 0, "minor": 0, "gt_total": 0, "n": 0}
        vol_dir = cond_dir / volume_zh
        if not vol_dir.is_dir():
            if all_conditions:
                rows.append({"cond": cond, "label": LABELS.get(cond, cond), **totals})
            continue
        for case_d in vol_dir.iterdir():
            if not case_d.is_dir() or case_d.name.startswith("_ws_"):
                continue
            fr = case_d / "eval" / "fact_recall.json"
            if not fr.exists():
                continue
            data = json.loads(fr.read_text())
            s = data.get("summary", {})
            if s.get("recall") is None:
                continue
            sev = s.get("missing_severity", {})
            totals["gt_total"] += s.get("gt_claims_total", 0)
            totals["matched"] += s.get("matched", 0)
            totals["partial"] += s.get("partial", 0)
            totals["missing"] += s.get("missing", 0)
            totals["critical"] += sev.get("critical", 0)
            totals["important"] += sev.get("important", 0)
            totals["minor"] += sev.get("minor", 0)
            totals["n"] += 1
        # Distribute unlabeled missing into minor
        sev_sum = totals["critical"] + totals["important"] + totals["minor"]
        unlabeled = totals["missing"] - sev_sum
        if unlabeled > 0:
            totals["minor"] += unlabeled
        if totals["n"] > 0 or all_conditions:
            rows.append({"cond": cond, "label": LABELS.get(cond, cond), **totals})
    rows.sort(key=lambda r: group_sort_key(r["cond"]))
    return rows


def fmt_pct(pct: float) -> str:
    if pct >= 10:
        return f'{pct:.0f}%'
    return f'{pct:.1f}%'


def draw_segmented_bar(ax, y, segments, bar_h):
    left = 0
    for pct, bg, _ in segments:
        if pct <= 0:
            continue
        ax.barh(y, pct, left=left, height=bar_h, color=bg, edgecolor='none', zorder=2)
        left += pct


def annotate_visible_segments(ax, y, segments, x_min: float, x_max: float, bar_h: float) -> None:
    """Label each segment. Inside if wide enough, above if medium, skip if too narrow."""
    # First pass: collect all labels with positions
    entries = []
    left = 0
    for pct, _, fg in segments:
        if pct <= 0:
            left += pct
            continue
        seg_left = left
        seg_right = left + pct
        visible_left = max(seg_left, x_min)
        visible_right = min(seg_right, x_max)
        visible_width = visible_right - visible_left
        if visible_width > 0:
            entries.append((visible_left, visible_right, visible_width, pct, fg))
        left += pct

    for vis_left, vis_right, vis_w, pct, fg in entries:
        label = fmt_pct(pct)
        cx = vis_left + vis_w / 2
        if vis_w >= MIN_INSIDE_PCT:
            ax.text(cx, y, label, ha='center', va='center',
                    fontsize=8, fontweight='600', color=fg, zorder=4)
        elif vis_w >= 1.5:
            # Check if placing above would collide with neighbors
            ax.text(cx, y - bar_h / 2 - 0.12, label, ha='center', va='top',
                    fontsize=6.5, fontweight='600', color=fg, zorder=4)


def plot_single(rows: list[dict], title: str, output_path: Path, dpi: int) -> None:
    n = len(rows)
    if n == 0:
        print(f"  (skipped — no data for {title})")
        return

    fig_h = max(3.5, n * 0.72 + 2.2)
    fig = plt.figure(figsize=(10, fig_h))
    gs = gridspec.GridSpec(1, 2, width_ratios=[1.1, 4.4], wspace=0.04)
    ax_left = fig.add_subplot(gs[0, 0])
    ax_right = fig.add_subplot(gs[0, 1], sharey=ax_left)

    bar_h = 0.48

    for i, row in enumerate(rows):
        gt = row["gt_total"]
        if gt == 0:
            continue
        matched_pct = row["matched"] / gt * 100
        partial_pct = row["partial"] / gt * 100
        m_pct = row["minor"] / gt * 100
        i_pct = row["important"] / gt * 100
        c_pct = row["critical"] / gt * 100

        segments = [
            (matched_pct, C_MATCHED, T_MATCHED),
            (partial_pct, C_PARTIAL, T_PARTIAL),
            (m_pct, C_MINOR, T_MINOR),
            (i_pct, C_IMPORTANT, T_IMPORTANT),
            (c_pct, C_CRITICAL, T_CRITICAL),
        ]

        draw_segmented_bar(ax_left, i, segments, bar_h)
        draw_segmented_bar(ax_right, i, segments, bar_h)
        annotate_visible_segments(ax_left, i, segments, 0, BREAK_START, bar_h)
        annotate_visible_segments(ax_right, i, segments, BREAK_START, 100, bar_h)

    ax_left.set_yticks(range(n))
    ax_left.set_yticklabels([r["label"] for r in rows], fontsize=10)
    ax_left.tick_params(axis='y', length=0)
    ax_right.tick_params(axis='y', left=False, labelleft=False)

    ax_left.set_xlim(0, BREAK_START)
    ax_right.set_xlim(BREAK_START, 100)
    ax_left.set_xticks([0])
    ax_left.set_xticklabels(['0%'], fontsize=8.5, color='#64748b')
    ax_right.set_xticks([60, 70, 80, 90, 100])
    ax_right.set_xticklabels(['60%', '70%', '80%', '90%', '100%'], fontsize=8.5, color='#64748b')

    for ax in (ax_left, ax_right):
        ax.spines['bottom'].set_color('#cbd5e1')
        ax.xaxis.grid(True, linestyle='-', alpha=0.1, linewidth=0.4)
        ax.set_axisbelow(True)

    ax_left.spines['right'].set_visible(False)
    ax_right.spines['left'].set_visible(False)

    d = .009
    kwargs = dict(transform=ax_left.transAxes, color='#64748b', clip_on=False, linewidth=0.8)
    ax_left.plot((1 - d, 1 + d), (-d, +d), **kwargs)
    ax_left.plot((1 - d, 1 + d), (1 - d, 1 + d), **kwargs)
    kwargs.update(transform=ax_right.transAxes)
    ax_right.plot((-d, +d), (-d, +d), **kwargs)
    ax_right.plot((-d, +d), (1 - d, 1 + d), **kwargs)

    fig.suptitle(title, fontsize=12, y=0.97, color='#1e293b', fontweight='bold')
    fig.supxlabel("GT Claim Coverage", fontsize=10, y=0.04)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.18, right=0.985, top=0.92, bottom=0.11)
    fig.savefig(output_path, dpi=dpi, facecolor='white', bbox_inches='tight')
    plt.close(fig)
    print(output_path)


def save_legend(output_path: Path, dpi: int) -> None:
    handles = [
        mpatches.Patch(facecolor=C_MATCHED, label='Matched'),
        mpatches.Patch(facecolor=C_PARTIAL, label='Partial'),
        mpatches.Patch(facecolor=C_MINOR, label='Minor'),
        mpatches.Patch(facecolor=C_IMPORTANT, label='Important'),
        mpatches.Patch(facecolor=C_CRITICAL, label='Critical'),
    ]
    fig_leg, ax_leg = plt.subplots(figsize=(4, 1.2))
    ax_leg.axis('off')
    ax_leg.legend(handles=handles, loc='center', frameon=True,
                  fancybox=False, edgecolor='#DDDDDD', framealpha=1.0,
                  fontsize=10, handletextpad=0.5, borderpad=0.6,
                  ncol=5, columnspacing=1.0,
                  title='GT Claim Coverage', title_fontsize=10)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig_leg.savefig(output_path, dpi=dpi, facecolor='white', bbox_inches='tight')
    plt.close(fig_leg)
    print(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot fact severity stacked bar chart.")
    parser.add_argument("--volume", choices=sorted(VOLUMES_MAP), default="upper")
    parser.add_argument("--all-conditions", action="store_true",
                        help="Show all conditions on Y axis, even those without data.")
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    vol_zh = VOLUMES_MAP[args.volume]
    out_dir = args.output_dir or DEFAULT_OUTPUT_DIR

    for grp, grp_label in [("commercial", "Commercial"), ("opensource", "Open-Source")]:
        rows = collect_data(vol_zh, grp, args.all_conditions)
        title = f"Fact Coverage & Omission Severity — {grp_label} ({args.volume.title()})"
        out_path = out_dir / f"{args.volume}_fact_severity_{grp}.png"
        plot_single(rows, title, out_path, args.dpi)

    legend_path = out_dir / f"{args.volume}_fact_severity_legend.png"
    save_legend(legend_path, args.dpi)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
