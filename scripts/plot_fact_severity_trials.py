#!/usr/bin/env python3
"""Trial plots for fact omission severity design discussion.

Outputs one figure per volume:
1. Fact coverage & omission severity stacked bar
2. Separate legend file
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd


plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 9,
    "axes.linewidth": 0.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.pad_inches": 0.05,
})

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
OUT_DIR = REPO_ROOT / "figures" / "weighted_recall_trials"
VOLUME_MAP = {"upper": "上冊", "middle": "中冊", "lower": "下冊"}

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
    "baseline_ollama_mistral-large-3-675b-cloud": "Mistral Large 3 (675B / 41A)",
    "baseline_ollama_qwen3.5-397b-cloud": "Qwen3.5 (397B / 17A)",
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
    "LENS-Full-DeepSeek_v31": 20,
    "LENS-NoAFG-DeepSeek_v31": 21,
    "LENS-NoReact-DeepSeek_v31": 22,
}

EXCLUDED_CONDITIONS = {
    "baseline_ollama_qwen3-next-80b-cloud",
    "baseline_ollama_nemotron-3-super-cloud",
}

C_MATCHED = "#86efac"
C_PARTIAL = "#bbf7d0"
C_MINOR = "#d1d5db"
C_IMPORTANT = "#fcd34d"
C_CRITICAL = "#fca5a5"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot upper-volume trial figures for fact severity.")
    parser.add_argument("--volume", choices=sorted(VOLUME_MAP), default="upper")
    parser.add_argument("--dpi", type=int, default=400)
    return parser.parse_args()


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


def sort_key(cond_key: str) -> tuple[int, str]:
    if cond_key in CANONICAL_PRIORITY:
        return (CANONICAL_PRIORITY[cond_key], cond_key)
    if cond_key.startswith("baseline_ollama_"):
        return (200, cond_key)
    if cond_key.startswith("baseline_"):
        return (100, cond_key)
    return (300, cond_key)


def short_label(cond_key: str) -> str:
    label = DISPLAY_LABELS.get(cond_key, cond_key)
    if " (" in label:
        label = label.split(" (", 1)[0]
    return label


def mean_or_none(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return None if not vals else float(sum(vals) / len(vals))


def label_fontsize(value: float) -> float:
    if value >= 12:
        return 7.4
    if value >= 8:
        return 6.9
    if value >= 5:
        return 6.3
    if value >= 3:
        return 5.8
    if value >= 1.5:
        return 5.2
    return 4.6


def load_rows(volume: str) -> pd.DataFrame:
    target_volume = VOLUME_MAP[volume]
    rows = []
    for cond_dir in sorted(DATA_DIR.iterdir()):
        if not cond_dir.is_dir() or cond_dir.name == "gt" or cond_dir.name.startswith("timeline"):
            continue
        cond_key = cond_dir.name
        group = classify_group(cond_key)
        if group is None:
            continue
        matched = []
        partial = []
        minor = []
        important = []
        critical = []
        recall = []
        weighted = []
        for case_path in cond_dir.glob("case_*.json"):
            obj = json.loads(case_path.read_text(encoding="utf-8"))
            if obj.get("volume") != target_volume:
                continue
            ev = obj.get("eval") or {}
            detail = ev.get("fact_detail") or {}
            gt_total = detail.get("gt_total") or 0
            if gt_total <= 0:
                continue
            sev = ev.get("missing_severity") or {}
            matched.append((detail.get("matched") or 0) / gt_total * 100)
            partial.append((detail.get("partial") or 0) / gt_total * 100)
            minor.append((sev.get("minor") or 0) / gt_total * 100)
            important.append((sev.get("important") or 0) / gt_total * 100)
            critical.append((sev.get("critical") or 0) / gt_total * 100)
            recall.append(ev.get("fact_recall"))
            weighted.append(ev.get("weighted_recall"))
        if not recall:
            continue
        rows.append({
            "cond_key": cond_key,
            "label": short_label(cond_key),
            "group": group,
            "matched": mean_or_none(matched),
            "partial": mean_or_none(partial),
            "minor": mean_or_none(minor),
            "important": mean_or_none(important),
            "critical": mean_or_none(critical),
            "recall": mean_or_none(recall),
            "weighted_recall": mean_or_none(weighted),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(by="cond_key", key=lambda s: s.map(lambda x: sort_key(x))).reset_index(drop=True)


def plot_omission_only(df: pd.DataFrame, volume: str, out_path: Path, dpi: int,
                       group_label: str = "", x_max: int | None = None) -> None:
    n = len(df)
    fig_h = max(3.5, 0.45 * n + 1.0)
    fig, ax = plt.subplots(figsize=(12.8, fig_h))
    y = np.arange(len(df))
    left = np.zeros(len(df))
    segments = [
        ("partial", C_PARTIAL, "#166534", "Partial"),
        ("minor", C_MINOR, "#374151", "Minor"),
        ("important", C_IMPORTANT, "#92400e", "Important"),
        ("critical", C_CRITICAL, "#991b1b", "Critical"),
    ]
    for key, color, text_color, label in segments:
        vals = df[key].fillna(0).to_numpy()
        ax.barh(y, vals, left=left, height=0.52, color=color, edgecolor="none", label=label)
        for i, v in enumerate(vals):
            if key == "critical":
                continue
            if v > 0.02:
                ax.text(left[i] + v / 2, y[i], f"{v:.1f}%", ha="center", va="center",
                        fontsize=label_fontsize(v), color=text_color, fontweight="600", clip_on=True)
        left += vals

    # Critical: always label outside bar on the right
    critical_vals = df["critical"].fillna(0).to_numpy()
    total_vals = df[["partial", "minor", "important", "critical"]].fillna(0).sum(axis=1).to_numpy()

    ax.set_yticks(y)
    ax.set_yticklabels(df["label"], fontsize=9.5)
    ax.invert_yaxis()
    ax.tick_params(axis="y", length=0)
    for i, v in enumerate(critical_vals):
        if v <= 0:
            continue
        x = total_vals[i] + 0.9
        ax.text(x, y[i], f"{v:.1f}%", ha="left", va="center",
                fontsize=8, color="#991b1b", fontweight="700", clip_on=False)

    if x_max is None:
        x_max = int(np.ceil(total_vals.max() / 5) * 5) + 5 if len(total_vals) else 65
        x_max = max(x_max, 20)
    ax.set_xlim(0, x_max)
    ax.set_xticks(list(range(0, x_max + 1, 10)))
    ax.set_xlabel("Omitted GT Claims (%)", fontsize=10)
    title_suffix = f" — {group_label}" if group_label else ""
    ax.set_title(
        f"Fact Coverage & Omission Severity{title_suffix}  ({volume.title()})",
        fontsize=12,
        pad=12,
        color="#1e293b",
        fontweight="bold",
    )
    ax.xaxis.grid(True, linestyle="-", alpha=0.12, linewidth=0.5)
    ax.set_axisbelow(True)

    # Legend removed — separate legend file output
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, facecolor="white")
    plt.close(fig)


def save_legend(dpi: int, out_path: Path) -> None:
    handles = [
        mpatches.Patch(facecolor=C_PARTIAL, label="Partial"),
        mpatches.Patch(facecolor=C_MINOR, label="Minor"),
        mpatches.Patch(facecolor=C_IMPORTANT, label="Important"),
        mpatches.Patch(facecolor=C_CRITICAL, label="Critical"),
    ]
    fig, ax = plt.subplots(figsize=(4.2, 1.0))
    ax.axis("off")
    ax.legend(handles=handles, loc="center", frameon=False, ncol=4, fontsize=9)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    df = load_rows(args.volume)
    if df.empty:
        raise SystemExit("No data")
    out_base = OUT_DIR

    # Compute global x_max across both groups for consistent axes
    global_max = df[["partial", "minor", "important", "critical"]].fillna(0).sum(axis=1).max()
    global_x_max = int(np.ceil(global_max / 5) * 5) + 5
    global_x_max = max(global_x_max, 20)

    for grp, grp_label in [("commercial", "Commercial"), ("opensource", "Open-Source")]:
        df_grp = df[df["group"] == grp].reset_index(drop=True)
        if df_grp.empty:
            print(f"  (skipped — no data for {grp_label})")
            continue
        out_path = out_base / f"{args.volume}_trial_omission_only_{grp}.png"
        plot_omission_only(df_grp, args.volume, out_path, args.dpi, group_label=grp_label, x_max=global_x_max)
        print(out_path)

    legend_path = out_base / f"{args.volume}_trial_omission_only_legend.png"
    save_legend(args.dpi, legend_path)
    print(legend_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
