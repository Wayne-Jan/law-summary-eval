#!/usr/bin/env python3
"""Plot fact-recall scatter from static eval_metrics JSON snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures" / "metric_heatmaps"

VOLUME_FILES = {
    "upper": DATA_DIR / "eval_metrics_upper.json",
    "middle": DATA_DIR / "eval_metrics_middle.json",
    "lower": DATA_DIR / "eval_metrics_lower.json",
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
    "LENS-NoReact-DeepSeek_v31": 21,
    "LENS-NoAFG-DeepSeek_v31": 22,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot fact recall scatter from static metrics JSON.")
    parser.add_argument("--volume", choices=sorted(VOLUME_FILES), default="upper")
    parser.add_argument("--group", choices=("all", "commercial", "opensource"), default="all")
    parser.add_argument("--cmap", default="viridis", help="Matplotlib colormap name.")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_group(group: str) -> str:
    return {"commercial": "商用模型", "opensource": "開源模型"}.get(group, group)


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


def mean_or_none(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return None if not vals else float(sum(vals) / len(vals))


def build_dataframe(snapshot: dict, group: str) -> pd.DataFrame:
    rows = []
    wanted_group = normalize_group(group)
    for cond_key, cond in snapshot["conditions"].items():
        if group != "all" and cond.get("group") != wanted_group:
            continue
        cases = list((cond.get("cases") or {}).values())
        recall = mean_or_none([(c.get("fact_recall") or {}).get("avg") for c in cases])
        precision = mean_or_none([(c.get("fact_recall") or {}).get("precision") for c in cases])
        f1 = mean_or_none([(c.get("fact_recall") or {}).get("f1") for c in cases])
        if recall is None or precision is None or f1 is None:
            continue
        rows.append(
            {
                "cond_key": cond_key,
                "label": short_label(cond.get("label") or cond_key),
                "group": cond.get("group") or "",
                "recall": recall,
                "precision": precision,
                "f1": f1,
                "n_cases": sum(1 for c in cases if (c.get("fact_recall") or {}).get("avg") is not None),
                "priority": canonical_priority(cond_key, cond),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["priority", "label"], kind="stable").reset_index(drop=True)


def default_output_path(volume: str, group: str, cmap: str) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{volume}_fact_recall_scatter_{group}_{cmap}.png"


def plot(df: pd.DataFrame, volume: str, group: str, cmap: str, output_path: Path, dpi: int) -> None:
    if df.empty:
        raise ValueError("No fact recall precision/recall/f1 data available.")

    fig, ax = plt.subplots(figsize=(12, 8))
    sizes = 110 + (df["n_cases"].fillna(0) * 8)
    scatter = ax.scatter(
        df["precision"],
        df["recall"],
        c=df["f1"],
        cmap=cmap,
        vmin=0.5,
        vmax=1.0,
        s=sizes,
        alpha=0.9,
        edgecolors="white",
        linewidths=1.2,
    )

    for _, row in df.iterrows():
        ax.annotate(
            row["label"],
            (row["precision"], row["recall"]),
            textcoords="offset points",
            xytext=(6, 6),
            ha="left",
            va="bottom",
            fontsize=9,
            color="#0f172a",
        )

    ax.set_xlim(0.5, 1.02)
    ax.set_ylim(0.5, 1.02)
    ax.set_xlabel("Precision", fontsize=12)
    ax.set_ylabel("Recall", fontsize=12)
    ax.set_title(
        f"Fact Recall Scatter — {volume.title()} Volume ({group.title()})",
        fontsize=15,
        pad=14,
    )
    ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.35)

    cbar = fig.colorbar(scatter, ax=ax, pad=0.02)
    cbar.set_label("F1", fontsize=11)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    snapshot = load_snapshot(VOLUME_FILES[args.volume])
    df = build_dataframe(snapshot, args.group)
    output_path = args.output or default_output_path(args.volume, args.group, args.cmap)
    plot(df, args.volume, args.group, args.cmap, output_path, args.dpi)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
