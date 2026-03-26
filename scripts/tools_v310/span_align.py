#!/usr/bin/env python3
"""Align source spans in v3.10 artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from modules.extraction_v3_10.span_alignment import align_timeline_events


def main() -> int:
    parser = argparse.ArgumentParser(description="v3.10 span alignment tool")
    parser.add_argument("--source", required=True, help="Judgment txt path")
    parser.add_argument("--master", required=True, help="master.json path")
    parser.add_argument("--report", help="Optional report path")
    args = parser.parse_args()

    source_text = Path(args.source).read_text(encoding="utf-8")
    master_path = Path(args.master)
    master = json.loads(master_path.read_text(encoding="utf-8"))

    timeline = (master.get("timeline") or {}).get("timeline") or []
    stats = align_timeline_events(source_text, timeline)
    master.setdefault("metadata", {})["span_alignment"] = stats.to_dict()
    master_path.write_text(
        json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.report:
        Path(args.report).write_text(
            json.dumps(stats.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(stats.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

