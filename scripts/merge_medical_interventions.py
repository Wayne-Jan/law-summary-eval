#!/usr/bin/env python3
"""
Merge medical_interventions.json into timeline_v310 JSON files.

Reads from Law_extraction_refactor/data/medical_interventions/,
writes medical_interventions key into law-summary-eval/data/timeline_v310/case_XXX.json.

Usage:
  python scripts/merge_medical_interventions.py
  python scripts/merge_medical_interventions.py --dry-run
"""

import argparse
import json
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent.parent
EXTRACT_ROOT = Path("/mnt/d/Law_extraction_refactor")
MI_DIR = EXTRACT_ROOT / "data" / "medical_interventions"
TL_DIR = EVAL_ROOT / "data" / "timeline_v310"
MANIFEST_PATH = EVAL_ROOT / "data" / "manifest.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    case_slugs = manifest.get("case_slugs", {})

    # Build reverse: case_name → slug
    name_to_slug = {name: slug for name, slug in case_slugs.items()}

    merged = 0
    skipped = 0
    not_found = 0

    for mi_case_dir in sorted(MI_DIR.iterdir()):
        if not mi_case_dir.is_dir():
            continue
        mi_path = mi_case_dir / "medical_interventions.json"
        if not mi_path.exists():
            continue

        case_name = mi_case_dir.name
        slug = name_to_slug.get(case_name)
        if not slug:
            print(f"  SKIP (no slug): {case_name}")
            skipped += 1
            continue

        tl_path = TL_DIR / f"{slug}.json"
        if not tl_path.exists():
            print(f"  SKIP (no timeline): {slug} ← {case_name}")
            not_found += 1
            continue

        mi_data = json.loads(mi_path.read_text(encoding="utf-8"))
        # Only keep procedures and medications
        mi_payload = {
            "procedures": mi_data.get("procedures", []),
            "medications": mi_data.get("medications", []),
        }

        if args.dry_run:
            np = len(mi_payload["procedures"])
            nm = len(mi_payload["medications"])
            print(f"  DRY-RUN: {slug} ← {case_name} ({np}P/{nm}M)")
            merged += 1
            continue

        tl_data = json.loads(tl_path.read_text(encoding="utf-8"))
        tl_data["medical_interventions"] = mi_payload
        tl_path.write_text(
            json.dumps(tl_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        merged += 1

    print(f"\nDone: merged={merged}, skipped={skipped}, not_found={not_found}")


if __name__ == "__main__":
    main()
