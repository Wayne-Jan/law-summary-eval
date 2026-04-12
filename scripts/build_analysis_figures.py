#!/usr/bin/env python3
"""Rebuild analysis figures used by metrics.html."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

VOLUMES = ("upper", "middle", "lower")


def run_step(args: list[str]) -> None:
    cmd = [PYTHON, *args]
    print(f"[figures] {' '.join(args)}")
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def main() -> int:
    for volume in VOLUMES:
        run_step(["scripts/plot_metrics_heatmap.py", "--volume", volume, "--metric", "quality"])
        run_step(["scripts/plot_fact_recall_dumbbell.py", "--volume", volume, "--zoom"])
        run_step(["scripts/plot_fact_severity_trials.py", "--volume", volume])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
