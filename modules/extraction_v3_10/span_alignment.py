"""Deterministic span alignment helpers for extraction v3.10."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.extraction_v3_8.alignment_engine import smart_align


@dataclass
class AlignStats:
    events: int = 0
    source_spans: int = 0
    exact_spans: int = 0
    fuzzy_spans: int = 0
    unresolved_spans: int = 0
    exact_events: int = 0
    fuzzy_events: int = 0
    unresolved_events: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "events": self.events,
            "source_spans": self.source_spans,
            "exact_spans": self.exact_spans,
            "fuzzy_spans": self.fuzzy_spans,
            "unresolved_spans": self.unresolved_spans,
            "exact_events": self.exact_events,
            "fuzzy_events": self.fuzzy_events,
            "unresolved_events": self.unresolved_events,
        }


def _resolve_span(source_text: str, span: dict[str, Any]) -> tuple[bool, str, float]:
    quote = str(span.get("quote") or span.get("extraction_text") or "").strip()
    if not quote:
        span["alignment_status"] = "UNRESOLVED"
        span["alignment_method"] = "none"
        span["alignment_confidence"] = 0.0
        return False, "none", 0.0

    hit = smart_align(source_text, quote)
    if not hit:
        span["alignment_status"] = "UNRESOLVED"
        span["alignment_method"] = "none"
        span["alignment_confidence"] = 0.0
        return False, "none", 0.0

    span["quote"] = quote
    span["char_start"] = hit.start
    span["char_end"] = hit.end
    span["alignment_method"] = hit.method
    span["alignment_confidence"] = round(float(hit.confidence), 4)
    span["alignment_status"] = (
        "MATCH_EXACT" if hit.confidence >= 0.95 else "MATCH_FUZZY"
    )
    return True, hit.method, float(hit.confidence)


def align_timeline_events(source_text: str, events: list[dict[str, Any]]) -> AlignStats:
    stats = AlignStats(events=len(events))

    for evt in events:
        if not isinstance(evt, dict):
            continue

        source_spans = evt.get("source_spans")
        if not isinstance(source_spans, list) or not source_spans:
            primary_quote = str(evt.get("extraction_text") or "").strip()
            source_spans = [{"role": "primary", "quote": primary_quote}]
            evt["source_spans"] = source_spans

        span_statuses: list[str] = []
        span_confidences: list[float] = []
        primary_span = None
        event_has_unresolved = False
        event_has_fuzzy = False

        for idx, span in enumerate(source_spans):
            if not isinstance(span, dict):
                event_has_unresolved = True
                continue
            stats.source_spans += 1
            if idx == 0:
                span.setdefault("role", "primary")
                primary_span = span
            ok, _, conf = _resolve_span(source_text, span)
            status = str(span.get("alignment_status") or "UNRESOLVED")
            span_statuses.append(status)
            span_confidences.append(conf)
            if ok:
                if status == "MATCH_EXACT":
                    stats.exact_spans += 1
                else:
                    stats.fuzzy_spans += 1
                    event_has_fuzzy = True
            else:
                stats.unresolved_spans += 1
                event_has_unresolved = True

        if primary_span is not None:
            evt["extraction_text"] = str(primary_span.get("quote") or "").strip()

        resolved_spans = [
            s
            for s in source_spans
            if isinstance(s, dict)
            and isinstance(s.get("char_start"), int)
            and isinstance(s.get("char_end"), int)
            and 0 <= s["char_start"] < s["char_end"]
        ]
        if resolved_spans:
            first = resolved_spans[0]
            evt["char_start"] = first.get("char_start", -1)
            evt["char_end"] = first.get("char_end", -1)
        else:
            evt["char_start"] = -1
            evt["char_end"] = -1

        if event_has_unresolved:
            evt["alignment_status"] = "UNRESOLVED"
            stats.unresolved_events += 1
        elif event_has_fuzzy or any(s == "MATCH_FUZZY" for s in span_statuses):
            evt["alignment_status"] = "MATCH_FUZZY"
            stats.fuzzy_events += 1
        elif span_statuses:
            evt["alignment_status"] = "MATCH_EXACT"
            stats.exact_events += 1
        else:
            evt["alignment_status"] = "UNRESOLVED"
            stats.unresolved_events += 1

        if span_confidences:
            evt["alignment_confidence"] = round(sum(span_confidences) / len(span_confidences), 4)
        else:
            evt["alignment_confidence"] = 0.0
        evt["alignment_method"] = "deterministic_span_align"

    return stats
