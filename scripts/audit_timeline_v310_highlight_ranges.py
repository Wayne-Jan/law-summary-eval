#!/usr/bin/env python3
"""Audit timeline_v310 span highlight ranges against quote text.

Focuses on spans whose UI highlight can drift because the stored char range
comes from fuzzy / partial alignment while the UI renders raw chunk offsets.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit timeline_v310 highlight ranges")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "timeline_v310",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "logs" / "timeline_v310_highlight_audit.json",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=30,
    )
    return parser.parse_args()


def normalize_loose(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def find_containing_chunk(chunks: list[dict], char_start: int) -> dict | None:
    for chunk in chunks:
        start = int(chunk.get("start_char", -1) or -1)
        end = int(chunk.get("end_char", -1) or -1)
        if start <= char_start < end:
            return chunk
    return None


def refine_span_range_in_chunk(
    chunk_content: str,
    rel_start: int,
    rel_end: int,
    quote: str,
    window_pad: int = 120,
) -> tuple[int, int, str] | None:
    if not quote:
        return None
    search_start = max(0, rel_start - window_pad)
    search_end = min(len(chunk_content), rel_end + window_pad)
    window_text = chunk_content[search_start:search_end]

    exact_idx = window_text.find(quote)
    if exact_idx >= 0:
        return (search_start + exact_idx, search_start + exact_idx + len(quote), "exact_in_window")

    normalized_quote = normalize_loose(quote)
    if not normalized_quote:
        return None

    normalized_chars: list[str] = []
    index_map: list[int] = []
    for idx, ch in enumerate(window_text):
        if not ch.isspace():
            normalized_chars.append(ch)
            index_map.append(idx)
    normalized_window = "".join(normalized_chars)
    normalized_idx = normalized_window.find(normalized_quote)
    if normalized_idx < 0:
        return None

    orig_start = index_map[normalized_idx]
    orig_end = index_map[normalized_idx + len(normalized_quote) - 1] + 1
    return (search_start + orig_start, search_start + orig_end, "normalized_in_window")


def classify_span(chunk_content: str, rel_start: int, rel_end: int, quote: str) -> dict:
    raw_exclusive = chunk_content[rel_start:rel_end]
    raw_inclusive = chunk_content[rel_start : min(len(chunk_content), rel_end + 1)]
    refined = refine_span_range_in_chunk(chunk_content, rel_start, rel_end, quote)
    refined_text = ""
    refined_method = None
    if refined:
        rs, re, refined_method = refined
        refined_text = chunk_content[rs:re]

    classification = "miss"
    if raw_exclusive == quote:
        classification = "raw_exact"
    elif raw_inclusive == quote:
        classification = "raw_inclusive_fix"
    elif refined_text == quote:
        classification = refined_method or "refined"
    elif normalize_loose(refined_text) == normalize_loose(quote) and refined_text:
        classification = f"{refined_method or 'refined'}_normalized"

    return {
        "classification": classification,
        "raw_exclusive": raw_exclusive,
        "raw_inclusive": raw_inclusive,
        "refined_text": refined_text,
        "refined_method": refined_method,
    }


def main() -> int:
    args = parse_args()
    args.output_json.parent.mkdir(parents=True, exist_ok=True)

    case_count = 0
    span_count = 0
    status_counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    samples: list[dict] = []

    for path in sorted(args.input_dir.glob("case_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        chunks = payload.get("chunks") or []
        events = payload.get("events") or []
        case_count += 1
        for event in events:
            event_id = int(event.get("event_id", 0) or 0)
            for span in event.get("source_spans") or []:
                status = str(span.get("alignment_status") or "UNRESOLVED")
                if status not in {"MATCH_FUZZY", "PARTIAL_UNRESOLVED", "UNRESOLVED"}:
                    continue
                char_start = int(span.get("char_start", -1) or -1)
                char_end = int(span.get("char_end", -1) or -1)
                quote = str(span.get("quote") or "")
                chunk = find_containing_chunk(chunks, char_start)
                if not chunk or char_end <= char_start:
                    classification = "missing_chunk"
                    classification_counts[classification] += 1
                    status_counts[status] += 1
                    span_count += 1
                    if len(samples) < args.sample_limit:
                        samples.append(
                            {
                                "file": path.name,
                                "case_name": payload.get("case_name"),
                                "event_id": event_id,
                                "span_id": span.get("span_id"),
                                "status": status,
                                "classification": classification,
                                "quote": quote,
                            }
                        )
                    continue

                rel_start = char_start - int(chunk.get("start_char", 0) or 0)
                rel_end = char_end - int(chunk.get("start_char", 0) or 0)
                result = classify_span(str(chunk.get("content") or ""), rel_start, rel_end, quote)
                classification = result["classification"]
                classification_counts[classification] += 1
                status_counts[status] += 1
                span_count += 1

                if classification not in {"raw_exact", "raw_inclusive_fix", "exact_in_window", "normalized_in_window", "normalized_in_window_normalized"}:
                    if len(samples) < args.sample_limit:
                        samples.append(
                            {
                                "file": path.name,
                                "case_name": payload.get("case_name"),
                                "event_id": event_id,
                                "span_id": span.get("span_id"),
                                "status": status,
                                "classification": classification,
                                "quote": quote,
                                "raw_exclusive": result["raw_exclusive"],
                                "raw_inclusive": result["raw_inclusive"],
                                "refined_text": result["refined_text"],
                                "refined_method": result["refined_method"],
                            }
                        )

    report = {
        "case_count": case_count,
        "audited_span_count": span_count,
        "status_counts": dict(status_counts),
        "classification_counts": dict(classification_counts),
        "samples": samples,
    }
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"cases={case_count}")
    print(f"audited_spans={span_count}")
    print(f"status_counts={dict(status_counts)}")
    print(f"classification_counts={dict(classification_counts)}")
    print(f"report={args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
