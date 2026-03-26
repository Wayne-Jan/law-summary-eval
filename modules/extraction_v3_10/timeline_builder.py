"""Evidence-span aware timeline builder for extraction v3.10."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import DEFAULT_V310_CONFIG, V310Config
from .prompts.timeline_builder_prompt import (
    TIMELINE_BUILDER_SYSTEM_PROMPT,
    build_timeline_builder_prompt,
)
from modules.extraction_v3.argument_extractor import ArgumentExtractResult
from modules.extraction_v3.entity_mapper import EntityMapResult
from modules.extraction_v3.llm_client import (
    LLMClient,
    ProgressCallback,
    StreamCallback,
    parse_json_from_llm,
)
from modules.extraction_v3.scanner import ScanResult
from modules.extraction_v3.semantic_scanner import SemanticScanResult


@dataclass
class SourceSpan:
    role: str = "primary"
    quote: str = ""
    char_start: int = -1
    char_end: int = -1
    alignment_status: str = ""
    alignment_method: str = ""
    alignment_confidence: float = 0.0


@dataclass
class TimelineEvent:
    event_id: int
    timestamp: str
    timestamp_normalized: str
    event_type: str
    description: str
    actors: List[str] = field(default_factory=list)
    location: str = ""
    critical_decision: bool = False
    decision_content: str = ""
    vital_signs: Dict[str, str] = field(default_factory=dict)
    extraction_text: str = ""
    source_spans: List[SourceSpan] = field(default_factory=list)
    char_start: int = -1
    char_end: int = -1
    alignment_status: str = ""
    alignment_method: str = ""
    alignment_confidence: float = 0.0


@dataclass
class TimeGap:
    from_event_id: int
    to_event_id: int
    gap_hours: float
    explanation: str = ""


@dataclass
class TimeSpan:
    start: str
    end: str
    duration_hours: float


@dataclass
class TimelineSummary:
    total_events: int = 0
    time_span: TimeSpan = field(default_factory=lambda: TimeSpan("", "", 0.0))
    critical_decisions_count: int = 0
    has_initial_contact: bool = False
    has_deterioration: bool = False
    has_final_outcome: bool = False
    time_gaps: List[TimeGap] = field(default_factory=list)


@dataclass
class CausationStep:
    step: int
    event_id: int
    description: str


@dataclass
class TimelineBuildResult:
    timeline: List[TimelineEvent] = field(default_factory=list)
    timeline_summary: TimelineSummary = field(default_factory=TimelineSummary)
    causation_chain: List[CausationStep] = field(default_factory=list)
    llm_model: str = ""
    llm_latency_ms: float = 0.0
    extraction_round: int = 1

    def to_dict(self) -> dict:
        return {
            "timeline": [
                {
                    "event_id": e.event_id,
                    "timestamp": e.timestamp,
                    "timestamp_normalized": e.timestamp_normalized,
                    "event_type": e.event_type,
                    "description": e.description,
                    "actors": e.actors,
                    "location": e.location,
                    "critical_decision": e.critical_decision,
                    "decision_content": e.decision_content,
                    "vital_signs": e.vital_signs,
                    "extraction_text": e.extraction_text,
                    "source_spans": [
                        {
                            "role": s.role,
                            "quote": s.quote,
                            "char_start": s.char_start,
                            "char_end": s.char_end,
                            "alignment_status": s.alignment_status,
                            "alignment_method": s.alignment_method,
                            "alignment_confidence": s.alignment_confidence,
                        }
                        for s in e.source_spans
                    ],
                    "char_start": e.char_start,
                    "char_end": e.char_end,
                    "alignment_status": e.alignment_status,
                    "alignment_method": e.alignment_method,
                    "alignment_confidence": e.alignment_confidence,
                }
                for e in self.timeline
            ],
            "timeline_summary": {
                "total_events": self.timeline_summary.total_events,
                "time_span": {
                    "start": self.timeline_summary.time_span.start,
                    "end": self.timeline_summary.time_span.end,
                    "duration_hours": self.timeline_summary.time_span.duration_hours,
                },
                "critical_decisions_count": self.timeline_summary.critical_decisions_count,
                "has_initial_contact": self.timeline_summary.has_initial_contact,
                "has_deterioration": self.timeline_summary.has_deterioration,
                "has_final_outcome": self.timeline_summary.has_final_outcome,
                "time_gaps": [
                    {
                        "from_event_id": g.from_event_id,
                        "to_event_id": g.to_event_id,
                        "gap_hours": g.gap_hours,
                        "explanation": g.explanation,
                    }
                    for g in self.timeline_summary.time_gaps
                ],
            },
            "causation_chain": [
                {
                    "step": c.step,
                    "event_id": c.event_id,
                    "description": c.description,
                }
                for c in self.causation_chain
            ],
            "_meta": {
                "llm_model": self.llm_model,
                "llm_latency_ms": self.llm_latency_ms,
                "extraction_round": self.extraction_round,
            },
        }


class TimelineBuilder:
    def __init__(self, config: V310Config = DEFAULT_V310_CONFIG):
        self.config = config
        self.llm_client = LLMClient(ollama_base_url=config.ollama_base_url)

    async def build_timeline(
        self,
        judgment_text: str,
        scan_result: ScanResult,
        entity_map_result: EntityMapResult,
        argument_result: ArgumentExtractResult,
        semantic_result: Optional[SemanticScanResult] = None,
        max_text_length: int = 100000,
        progress_callback: Optional[ProgressCallback] = None,
        stream_callback: Optional[StreamCallback] = None,
    ) -> TimelineBuildResult:
        prompt = build_timeline_builder_prompt(
            judgment_text=judgment_text,
            scanner_result=scan_result.to_dict(),
            entity_map_result=entity_map_result.to_dict(),
            argument_result=argument_result.to_dict(),
            semantic_result=semantic_result.to_dict() if semantic_result else None,
            max_text_length=max_text_length,
        )

        model_config = self.config.models["timeline_builder"]
        response = await self.llm_client.generate(
            prompt=prompt,
            model_config=model_config,
            system_prompt=TIMELINE_BUILDER_SYSTEM_PROMPT,
            progress_callback=progress_callback,
            stream_callback=stream_callback,
        )

        if not response.success:
            raise RuntimeError(f"Timeline Builder LLM 調用失敗：{response.error}")

        result_json = parse_json_from_llm(response.content)
        if result_json is None:
            raise ValueError(f"無法解析 LLM 回應為 JSON：{response.content[:500]}")

        result = self._parse_result(result_json)
        result.llm_model = response.model
        result.llm_latency_ms = response.latency_ms
        result.extraction_round = 1
        return result

    def build_timeline_sync(
        self,
        judgment_text: str,
        scan_result: ScanResult,
        entity_map_result: EntityMapResult,
        argument_result: ArgumentExtractResult,
        semantic_result: Optional[SemanticScanResult] = None,
        max_text_length: int = 100000,
    ) -> TimelineBuildResult:
        return asyncio.run(
            self.build_timeline(
                judgment_text,
                scan_result,
                entity_map_result,
                argument_result,
                semantic_result,
                max_text_length,
            )
        )

    def _parse_source_spans(self, spans_json: Any, extraction_text: str) -> List[SourceSpan]:
        spans: List[SourceSpan] = []
        if isinstance(spans_json, list):
            for idx, item in enumerate(spans_json):
                if not isinstance(item, dict):
                    continue
                quote = str(item.get("quote") or "").strip()
                if not quote and idx == 0:
                    quote = extraction_text
                spans.append(
                    SourceSpan(
                        role=str(item.get("role") or ("primary" if idx == 0 else "supporting")),
                        quote=quote,
                    )
                )
        if not spans and extraction_text:
            spans.append(SourceSpan(role="primary", quote=extraction_text))
        return spans

    def _parse_result(self, json_data: dict) -> TimelineBuildResult:
        result = TimelineBuildResult()

        for e in json_data.get("timeline", []):
            extraction_text = str(e.get("extraction_text", "")).strip()
            source_spans = self._parse_source_spans(e.get("source_spans"), extraction_text)
            if source_spans and not extraction_text:
                extraction_text = source_spans[0].quote
            result.timeline.append(
                TimelineEvent(
                    event_id=e.get("event_id", 0),
                    timestamp=e.get("timestamp", ""),
                    timestamp_normalized=e.get("timestamp_normalized", ""),
                    event_type=e.get("event_type", ""),
                    description=e.get("description", ""),
                    actors=e.get("actors", []),
                    location=e.get("location", ""),
                    critical_decision=e.get("critical_decision", False),
                    decision_content=e.get("decision_content", ""),
                    vital_signs=e.get("vital_signs", {}),
                    extraction_text=extraction_text,
                    source_spans=source_spans,
                    char_start=e.get("char_start", -1),
                    char_end=e.get("char_end", -1),
                    alignment_status=e.get("alignment_status", ""),
                    alignment_method=e.get("alignment_method", ""),
                    alignment_confidence=float(e.get("alignment_confidence", 0.0) or 0.0),
                )
            )

        summary = json_data.get("timeline_summary", {})
        time_span_data = summary.get("time_span", {})
        result.timeline_summary = TimelineSummary(
            total_events=summary.get("total_events", len(result.timeline)),
            time_span=TimeSpan(
                start=time_span_data.get("start", ""),
                end=time_span_data.get("end", ""),
                duration_hours=time_span_data.get("duration_hours", 0.0),
            ),
            critical_decisions_count=summary.get("critical_decisions_count", 0),
            has_initial_contact=summary.get("has_initial_contact", False),
            has_deterioration=summary.get("has_deterioration", False),
            has_final_outcome=summary.get("has_final_outcome", False),
            time_gaps=[
                TimeGap(
                    from_event_id=g.get("from_event_id", 0),
                    to_event_id=g.get("to_event_id", 0),
                    gap_hours=g.get("gap_hours", 0.0),
                    explanation=g.get("explanation", ""),
                )
                for g in summary.get("time_gaps", [])
            ],
        )

        for c in json_data.get("causation_chain", []):
            result.causation_chain.append(
                CausationStep(
                    step=c.get("step", 0),
                    event_id=c.get("event_id", 0),
                    description=c.get("description", ""),
                )
            )

        return result

