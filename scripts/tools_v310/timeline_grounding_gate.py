#!/usr/bin/env python3
"""Timeline grounding gate for v3.10 evidence spans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="v3.10 timeline grounding gate")
    parser.add_argument("--master", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--report")
    parser.add_argument("--max-unresolved-rate", type=float, default=0.05)
    parser.add_argument("--min-exact-rate", type=float, default=0.9)
    args = parser.parse_args()

    master_path = Path(args.master)
    source = Path(args.source).read_text(encoding="utf-8")
    master = json.loads(master_path.read_text(encoding="utf-8"))

    events = (master.get("timeline") or {}).get("timeline") or []
    total = len(events)
    exact = 0
    unresolved = 0
    unresolved_rows = []

    for idx, evt in enumerate(events):
        spans = evt.get("source_spans") or []
        if not isinstance(spans, list) or not spans:
            unresolved += 1
            unresolved_rows.append({"event_index": idx, "reason": "missing_source_spans"})
            continue

        event_ok = True
        span_exact = 0
        for span in spans:
            if not isinstance(span, dict):
                event_ok = False
                continue
            quote = str(span.get("quote") or "").strip()
            s = span.get("char_start")
            e = span.get("char_end")
            valid_span = (
                isinstance(s, int) and isinstance(e, int) and 0 <= s < e <= len(source)
            )
            if not valid_span:
                event_ok = False
                unresolved_rows.append({"event_index": idx, "reason": "invalid_span"})
                continue
            if quote and source[s:e].strip() == quote:
                span_exact += 1
            else:
                event_ok = False

        if event_ok and span_exact == len(spans):
            exact += 1
        else:
            unresolved += 1

    exact_rate = (exact / total) if total else 1.0
    unresolved_rate = (unresolved / total) if total else 0.0

    result = {
        "events": total,
        "exact_quote_match": exact,
        "exact_quote_match_rate": round(exact_rate, 4),
        "unresolved": unresolved,
        "unresolved_rate": round(unresolved_rate, 4),
        "thresholds": {
            "min_exact_rate": args.min_exact_rate,
            "max_unresolved_rate": args.max_unresolved_rate,
        },
        "pass": exact_rate >= args.min_exact_rate
        and unresolved_rate <= args.max_unresolved_rate,
        "unresolved_examples": unresolved_rows[:20],
    }

    master.setdefault("metadata", {})["timeline_grounding_gate"] = result
    master_path.write_text(
        json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.report:
        Path(args.report).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

