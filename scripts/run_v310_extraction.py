#!/usr/bin/env python3
"""Agentic Extraction v3.10 runner.

This runner keeps v3.9 unchanged and writes a separate v3.10 artifact set.
Timeline events are evidence-span aware:
- `extraction_text` stays as the primary exact anchor quote
- `source_spans[]` may contain multiple exact quotes for one event
- char offsets are filled deterministically after generation
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.extraction_v3.argument_extractor import ArgumentExtractor
from modules.extraction_v3.auditor import Auditor
from modules.extraction_v3.config import DEFAULT_CONFIG
from modules.extraction_v3.entity_mapper import EntityMapper
from modules.extraction_v3_9.alignment_verifier import AlignmentVerifierV39
from modules.extraction_v3_9.config import DEFAULT_V39_CONFIG
from modules.extraction_v3_9.cross_validator import CrossValidatorV39
from modules.extraction_v3_9.merged_scanner import MergedScannerV39
from modules.extraction_v3_10.config import DEFAULT_V310_CONFIG, V310Config
from modules.extraction_v3_10.span_alignment import align_timeline_events
from modules.extraction_v3_10.timeline_builder import TimelineBuilder
from modules.extraction_v3_8.strict_audit import run_strict_audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run extraction v3.10")
    parser.add_argument("--input-dir", type=Path, default=PROJECT_ROOT / "原始判決書")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "extractions_v3.10")
    parser.add_argument("--single", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--fast", action="store_true", help="Skip alignment verifier LLM stage")
    parser.add_argument("-v", "--verbose", action="store_true", default=True)
    parser.add_argument("--quiet", dest="verbose", action="store_false")
    return parser.parse_args()


def pick_files(args: argparse.Namespace) -> list[Path]:
    if args.single:
        p = args.input_dir / args.single
        if not p.exists():
            raise FileNotFoundError(str(p))
        return [p]
    files = sorted(args.input_dir.glob("*.txt"))
    if args.skip_existing:
        files = [f for f in files if not (args.output_dir / f.stem / "master.json").exists()]
    if args.limit:
        files = files[: args.limit]
    return files


def _build_master_dict(
    case_name: str,
    source_file: Path,
    scan_result,
    semantic_result,
    entity_result,
    argument_result,
    timeline_result,
    cross_validation,
    alignment_result,
    audit_result,
    strict_audit: dict,
    span_stats: dict,
    processing_time_seconds: float,
) -> dict:
    return {
        "version": "extraction_v3.10",
        "case_name": case_name,
        "source_file": str(source_file),
        "extraction_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "coordinates": scan_result.to_dict() if scan_result else {},
        "semantic": semantic_result.to_dict() if semantic_result else {},
        "entities": entity_result.to_dict() if entity_result else {},
        "arguments": argument_result.to_dict() if argument_result else {},
        "timeline": timeline_result.to_dict() if timeline_result else {},
        "cross_validation_report": cross_validation.to_dict() if cross_validation else {},
        "alignment_verification": alignment_result.to_dict() if alignment_result else {},
        "strict_audit": strict_audit,
        "audit_result": audit_result.to_dict() if audit_result else {},
        "metadata": {
            "pipeline_version": "3.10",
            "span_alignment": span_stats,
            "processing_time_seconds": processing_time_seconds,
        },
    }


async def run_case(
    source_file: Path,
    output_dir: Path,
    verbose: bool = True,
    fast: bool = False,
) -> dict:
    start_ts = time.perf_counter()
    judgment_text = source_file.read_text(encoding="utf-8")

    # v3.10 keeps the scanner/validator stack from v3.9, but changes the timeline contract.
    scan_model = MergedScannerV39(DEFAULT_V39_CONFIG)
    entity_mapper = EntityMapper(DEFAULT_CONFIG)
    argument_extractor = ArgumentExtractor(DEFAULT_CONFIG)
    timeline_builder = TimelineBuilder(DEFAULT_V310_CONFIG)
    cross_validator = CrossValidatorV39(DEFAULT_V39_CONFIG)
    alignment_verifier = AlignmentVerifierV39(DEFAULT_V39_CONFIG)
    auditor = Auditor(DEFAULT_CONFIG)

    scan_out = await scan_model.scan(judgment_text)
    scan_result = scan_out.scan_result
    semantic_result = scan_out.semantic_result

    entity_result = await entity_mapper.map_entities(judgment_text, scan_result)
    argument_result = await argument_extractor.extract_arguments(
        judgment_text,
        scan_result,
        entity_result,
    )
    timeline_result = await timeline_builder.build_timeline(
        judgment_text,
        scan_result,
        entity_result,
        argument_result,
        semantic_result=semantic_result,
    )

    span_stats = align_timeline_events(judgment_text, timeline_result.timeline).to_dict()

    cross_validation = await cross_validator.validate(
        judgment_text,
        entity_result.to_dict(),
        argument_result.to_dict(),
        timeline_result.to_dict(),
        scan_result.to_dict(),
    )

    alignment_result = None
    unresolved_count = sum(
        1 for evt in timeline_result.timeline if str(evt.alignment_status) == "UNRESOLVED"
    )
    if (not fast) and unresolved_count:
        alignment_result = await alignment_verifier.verify(
            judgment_text,
            timeline_result.to_dict()["timeline"],
        )

    audit_result = await auditor.audit(
        scan_result,
        entity_result,
        argument_result,
        timeline_result,
        judgment_text=judgment_text,
    )

    strict_audit = run_strict_audit(
        {
            "timeline": timeline_result.to_dict(),
            "entities": entity_result.to_dict(),
            "arguments": argument_result.to_dict(),
            "coordinates": scan_result.to_dict(),
        },
        judgment_text,
    )

    master = _build_master_dict(
        case_name=source_file.stem,
        source_file=source_file,
        scan_result=scan_result,
        semantic_result=semantic_result,
        entity_result=entity_result,
        argument_result=argument_result,
        timeline_result=timeline_result,
        cross_validation=cross_validation,
        alignment_result=alignment_result,
        audit_result=audit_result,
        strict_audit=strict_audit,
        span_stats=span_stats,
        processing_time_seconds=round(time.perf_counter() - start_ts, 4),
    )

    case_dir = output_dir / source_file.stem
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "master.json").write_text(
        json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (case_dir / "timeline.json").write_text(
        json.dumps(timeline_result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return master


async def main_async() -> int:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    files = pick_files(args)
    if args.verbose:
        print(f"v3.10: {len(files)} cases")

    for idx, source_file in enumerate(files, start=1):
        if args.verbose:
            print(f"[{idx}/{len(files)}] {source_file.name}")
        await run_case(source_file, output_dir, verbose=args.verbose, fast=args.fast)

    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
