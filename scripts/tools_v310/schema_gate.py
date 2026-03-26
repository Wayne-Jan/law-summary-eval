#!/usr/bin/env python3
"""Deterministic schema gate for v3.10 artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED = {
    "timeline": ["timeline"],
    "master": [
        "case_name",
        "coordinates",
        "entities",
        "arguments",
        "timeline",
        "metadata",
    ],
}

ALLOWED_EVENT_TYPES = {
    "initial_contact",
    "diagnosis",
    "treatment",
    "vital_signs",
    "consultation",
    "deterioration",
    "critical_decision",
    "transfer",
    "final_outcome",
    "surgery",
    "medication",
    "verdict",
    "death",
}


def get_target(data: dict, stage: str):
    if stage == "master":
        return data
    return data.get(stage, data)


def _validate_timeline(target: dict, errors: list[str]) -> None:
    events = target.get("timeline")
    if not isinstance(events, list):
        errors.append("timeline must be list")
        return

    for i, evt in enumerate(events):
        if not isinstance(evt, dict):
            errors.append(f"timeline[{i}] is not object")
            continue

        for key in (
            "timestamp",
            "event_type",
            "description",
            "actors",
            "extraction_text",
            "source_spans",
            "char_start",
            "char_end",
        ):
            if key not in evt:
                errors.append(f"timeline[{i}] missing key: {key}")

        et = str(evt.get("event_type") or "").strip()
        if et and et not in ALLOWED_EVENT_TYPES:
            errors.append(f"timeline[{i}] invalid event_type: {et}")

        actors = evt.get("actors")
        if "actors" in evt and not isinstance(actors, list):
            errors.append(f"timeline[{i}] actors must be list")

        txt = str(evt.get("extraction_text") or "").strip()
        s = evt.get("char_start")
        e = evt.get("char_end")
        if not txt:
            errors.append(f"timeline[{i}] extraction_text empty")
        if not isinstance(s, int) or not isinstance(e, int):
            errors.append(f"timeline[{i}] char_start/char_end must be int")
        elif s < 0 or e <= s:
            errors.append(f"timeline[{i}] invalid char range: {s}-{e}")

        spans = evt.get("source_spans")
        if not isinstance(spans, list) or not spans:
            errors.append(f"timeline[{i}] source_spans must be non-empty list")
            continue
        for j, span in enumerate(spans):
            if not isinstance(span, dict):
                errors.append(f"timeline[{i}].source_spans[{j}] is not object")
                continue
            quote = str(span.get("quote") or "").strip()
            if not quote:
                errors.append(f"timeline[{i}].source_spans[{j}] quote empty")
            cs = span.get("char_start")
            ce = span.get("char_end")
            if not isinstance(cs, int) or not isinstance(ce, int):
                errors.append(f"timeline[{i}].source_spans[{j}] char_start/char_end must be int")
            elif cs < 0 or ce <= cs:
                errors.append(f"timeline[{i}].source_spans[{j}] invalid char range: {cs}-{ce}")


def main() -> int:
    parser = argparse.ArgumentParser(description="v3.10 schema gate")
    parser.add_argument("--stage", required=True, choices=sorted(REQUIRED.keys()))
    parser.add_argument("--input", required=True, help="Path to JSON file")
    parser.add_argument("--report", help="Optional report path")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    target = get_target(data, args.stage)

    errors = []
    if not isinstance(target, dict):
        errors.append(f"stage '{args.stage}' is not object")
    else:
        for key in REQUIRED[args.stage]:
            if key not in target:
                errors.append(f"missing key: {key}")

    if args.stage == "timeline" and isinstance(target, dict):
        _validate_timeline(target, errors)

    result = {
        "stage": args.stage,
        "valid": len(errors) == 0,
        "error_count": len(errors),
        "errors": errors,
    }
    if args.report:
        Path(args.report).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

