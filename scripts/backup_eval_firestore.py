#!/usr/bin/env python3
"""Daily Firestore snapshot backup for law-summary-eval.

Reads latest evaluator records from:
  evals/{evaluator}/records/{recordId}

Builds normalized export JSON grouped by evaluator, then writes immutable daily
snapshot data to:
  eval_backups_daily/{YYYY-MM-DD}
  eval_backups_daily/{YYYY-MM-DD}/evaluators/{evaluator}

Each calendar day writes its own immutable snapshot document. Content hashes are
stored for change detection, but duplicate content does not suppress the daily
write.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError as exc:  # pragma: no cover
    print(
        "Missing dependency: firebase-admin\n"
        "Install with: python -m pip install firebase-admin",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


EVAL_CONDITIONS = [
    "claude_afg_v5.1",
    "ablation_no_afg",
    "ablation_no_react",
    "baseline_claude-haiku",
    "baseline_claude-sonnet",
]

USER_ROLES = {
    "王敏銓": "legal",
    "李惠宗": "legal",
    "丁鴻志": "medical",
    "施朝仁": "medical",
    "admin": "admin",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backup eval Firestore records into daily snapshots.")
    parser.add_argument(
        "--service-account",
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
        help="Path to Firebase service account JSON.",
    )
    parser.add_argument(
        "--snapshot-id",
        default=dt.date.today().isoformat(),
        help="Snapshot document id. Default: today's YYYY-MM-DD.",
    )
    parser.add_argument(
        "--local-dir",
        default=os.environ.get(
            "LAW_SUMMARY_EVAL_BACKUP_DIR",
            r"D:\law-summary-eval-backups" if os.name == "nt" else "/mnt/d/law-summary-eval-backups",
        ),
        help="Local backup root directory. Default: D:\\law-summary-eval-backups.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reserved compatibility flag. Daily snapshots are always written.",
    )
    return parser.parse_args()


def init_firestore(service_account_path: str):
    if not service_account_path:
        raise SystemExit("Missing --service-account path.")
    sa_path = Path(service_account_path)
    if not sa_path.exists():
        raise SystemExit(f"Service account file not found: {sa_path}")
    cred = credentials.Certificate(str(sa_path))
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()


def stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(data: Any) -> str:
    return hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()


def normalize_complete_flag(data: Dict[str, Any], score_keys_min: int = 0) -> bool:
    if not data:
        return False
    if data.get("_complete"):
        return True
    scores = data.get("scores") or {}
    return len(scores) >= score_keys_min


def resolve_evaluator_name(uid: str, records: Dict[str, Any]) -> str:
    """Extract the evaluator display name from record keys (keys use name, not UID)."""
    for key in records:
        if key.startswith("eval_v2_condorder_"):
            # eval_v2_condorder_{name}_{caseName}
            rest = key[len("eval_v2_condorder_"):]
            for name in USER_ROLES:
                if rest.startswith(name + "_"):
                    return name
        elif key.startswith("eval_v2_"):
            rest = key[len("eval_v2_"):]
            for name in USER_ROLES:
                if rest.startswith(name + "_"):
                    return name
    return uid


def iter_evaluator_records(db) -> Iterable[Tuple[str, Dict[str, Dict[str, Any]]]]:
    # Use list_documents() to include virtual parent docs (only subcollections exist)
    for evaluator_ref in db.collection("evals").list_documents():
        uid = evaluator_ref.id
        records: Dict[str, Dict[str, Any]] = {}
        for rec_doc in evaluator_ref.collection("records").stream():
            payload = rec_doc.to_dict() or {}
            key = payload.get("key")
            if not key:
                continue
            records[key] = payload.get("data") or {}
        if not records:
            continue
        # Resolve display name from keys (UID → name mapping)
        evaluator = resolve_evaluator_name(uid, records)
        yield evaluator, records


def split_phase_key(evaluator: str, key: str) -> Tuple[str, str, str] | None:
    prefix = f"eval_v2_{evaluator}_"
    if not key.startswith(prefix):
        return None
    middle = key[len(prefix):]
    phase_suffixes = {
        "phase1": "_phase1",
        "phaseFB": "_phaseFB",
        "phaseTL": "_phaseTL",
    }
    for cond in EVAL_CONDITIONS:
        for phase_name, phase_suffix in phase_suffixes.items():
            suffix = f"_{cond}{phase_suffix}"
            if middle.endswith(suffix):
                case_name = middle[: -len(suffix)]
                return case_name, cond, phase_name
    return None


def build_case_export(
    evaluator: str,
    role: str,
    case_name: str,
    cond_order: list[str],
    phase_records: Dict[Tuple[str, str, str], Dict[str, Any]],
    phase3_record: Dict[str, Any] | None,
    snapshot_timestamp: str,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "meta": {
            "evaluator": evaluator,
            "role": role,
            "case_name": case_name,
            "timestamp": snapshot_timestamp,
            "condition_order": cond_order,
            "rubric_version": "v2.1",
        },
        "phase1": {},
        "phaseFB": {},
        "phaseTL": {},
        "phase3": None,
    }

    for idx, cond in enumerate(cond_order):
        label = f"版本 {chr(65 + idx)}"
        p1 = phase_records.get((case_name, cond, "phase1")) or {}
        pfb = phase_records.get((case_name, cond, "phaseFB")) or {}
        ptl = phase_records.get((case_name, cond, "phaseTL")) or {}
        result["phase1"][label] = {
            "real_condition": cond,
            "scores": p1.get("scores") or {},
            "overall_comment": p1.get("overall_comment") or "",
            "revision_count": p1.get("revision_count") or 0,
        }
        result["phaseFB"][label] = {
            "real_condition": cond,
            "sections": pfb.get("sections") or {},
            "_complete": bool(pfb.get("_complete")),
        }
        result["phaseTL"][label] = {
            "real_condition": cond,
            "scores": ptl.get("scores") or {},
            "comment": ptl.get("comment") or "",
            "_complete": bool(ptl.get("_complete")),
        }

    if phase3_record is not None:
        result["phase3"] = {
            "ranking": phase3_record.get("ranking") or [],
            "ranking_reason": phase3_record.get("ranking_reason") or "",
            "revision_count": phase3_record.get("revision_count") or 0,
            "_complete": bool(phase3_record.get("_complete")),
        }
    return result


def build_export_payload(db, snapshot_timestamp: str) -> Dict[str, Any]:
    all_data: Dict[str, Any] = {}
    for evaluator, records in iter_evaluator_records(db):
        role = USER_ROLES.get(evaluator, "unknown")
        cond_orders: Dict[str, list[str]] = {}
        phase3_by_case: Dict[str, Dict[str, Any]] = {}
        phase_records: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        case_names: set[str] = set()

        cond_prefix = f"eval_v2_condorder_{evaluator}_"
        base_prefix = f"eval_v2_{evaluator}_"

        for key, data in records.items():
            if key.startswith(cond_prefix):
                case_name = key[len(cond_prefix):]
                order = data if isinstance(data, list) else []
                cond_orders[case_name] = [c for c in order if isinstance(c, str)] or list(EVAL_CONDITIONS)
                case_names.add(case_name)
                continue

            if key.startswith(base_prefix) and key.endswith("_phase3"):
                case_name = key[len(base_prefix): -len("_phase3")]
                phase3_by_case[case_name] = data
                case_names.add(case_name)
                continue

            split = split_phase_key(evaluator, key)
            if split:
                case_name, cond, phase_name = split
                phase_records[(case_name, cond, phase_name)] = data
                case_names.add(case_name)

        evaluator_cases: Dict[str, Any] = {}
        for case_name in sorted(case_names):
            cond_order = cond_orders.get(case_name) or list(EVAL_CONDITIONS)
            if len(cond_order) < len(EVAL_CONDITIONS):
                cond_order = cond_order + [c for c in EVAL_CONDITIONS if c not in cond_order]
            evaluator_cases[case_name] = build_case_export(
                evaluator=evaluator,
                role=role,
                case_name=case_name,
                cond_order=cond_order[: len(EVAL_CONDITIONS)],
                phase_records=phase_records,
                phase3_record=phase3_by_case.get(case_name),
                snapshot_timestamp=snapshot_timestamp,
            )

        all_data[evaluator] = {
            "role": role,
            "cases": evaluator_cases,
        }
    return all_data


def get_latest_snapshot_meta(db, exclude_snapshot_id: str = "") -> Dict[str, Any] | None:
    docs = (
        db.collection("eval_backups_daily")
        .order_by("snapshot_date", direction=firestore.Query.DESCENDING)
        .limit(5)
        .stream()
    )
    for doc in docs:
        data = doc.to_dict() or {}
        if exclude_snapshot_id and doc.id == exclude_snapshot_id:
            continue
        data["_id"] = doc.id
        return data
    return None


def write_snapshot(
    db,
    snapshot_id: str,
    payload: Dict[str, Any],
    payload_hash: str,
    previous_snapshot: Dict[str, Any] | None = None,
) -> None:
    today_ref = db.collection("eval_backups_daily").document(snapshot_id)
    evaluator_count = len(payload)
    case_count = sum(len(item.get("cases") or {}) for item in payload.values())
    record_count = 0
    for item in payload.values():
        for case_data in (item.get("cases") or {}).values():
            meta = case_data.get("meta") or {}
            phase1 = case_data.get("phase1") or {}
            phase_fb = case_data.get("phaseFB") or {}
            phase_tl = case_data.get("phaseTL") or {}
            phase3 = case_data.get("phase3")
            record_count += 1 if meta else 0
            record_count += len(phase1)
            record_count += len(phase_fb)
            record_count += len(phase_tl)
            record_count += 1 if phase3 is not None else 0
    is_empty = evaluator_count == 0 or case_count == 0
    previous_snapshot_id = previous_snapshot.get("_id") if previous_snapshot else ""
    previous_content_hash = previous_snapshot.get("content_hash") if previous_snapshot else ""
    same_as_previous = bool(previous_snapshot_id) and previous_content_hash == payload_hash
    status = "empty" if is_empty else ("unchanged" if same_as_previous else "ok")
    meta = {
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_id,
        "created_at": firestore.SERVER_TIMESTAMP,
        "content_hash": payload_hash,
        "same_as_previous": same_as_previous,
        "previous_snapshot_id": previous_snapshot_id,
        "previous_content_hash": previous_content_hash,
        "evaluator_count": evaluator_count,
        "case_count": case_count,
        "record_count": record_count,
        "is_empty": is_empty,
        "status": status,
        "schema_version": "eval_v2_daily_backup_v1",
    }
    batch = db.batch()
    batch.set(today_ref, meta)
    for evaluator, data in payload.items():
        ref = today_ref.collection("evaluators").document(evaluator)
        batch.set(
            ref,
            {
                "evaluator": evaluator,
                "role": data.get("role") or "unknown",
                "case_count": len(data.get("cases") or {}),
                "record_count": sum(
                    1 + len((case_data.get("phase1") or {}))
                    + len((case_data.get("phaseFB") or {}))
                    + len((case_data.get("phaseTL") or {}))
                    + (1 if case_data.get("phase3") is not None else 0)
                    for case_data in (data.get("cases") or {}).values()
                ),
                "content_hash": content_hash(data),
                "data": data,
            },
        )
    batch.commit()


def write_local_snapshot(local_dir: str, snapshot_id: str, payload: Dict[str, Any], payload_hash: str) -> None:
    root = Path(local_dir)
    snapshot_dir = root / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "all.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_manifest = None
    previous_snapshot_id = ""
    previous_content_hash = ""
    same_as_previous = False
    if root.exists():
        candidates = sorted(
            [
                p for p in root.iterdir()
                if p.is_dir() and p.name != snapshot_id and (p / "manifest.json").exists()
            ],
            key=lambda p: p.name,
            reverse=True,
        )
        if candidates:
            latest_manifest = json.loads((candidates[0] / "manifest.json").read_text(encoding="utf-8"))
            previous_snapshot_id = str(latest_manifest.get("snapshot_id") or candidates[0].name)
            previous_content_hash = str(latest_manifest.get("content_hash") or "")
            same_as_previous = previous_content_hash == payload_hash
    is_empty = len(payload) == 0 or all(not (item.get("cases") or {}) for item in payload.values())
    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "content_hash": payload_hash,
        "same_as_previous": same_as_previous,
        "previous_snapshot_id": previous_snapshot_id,
        "previous_content_hash": previous_content_hash,
        "evaluator_count": len(payload),
        "case_count": sum(len(item.get("cases") or {}) for item in payload.values()),
        "record_count": sum(
            1 + len((case_data.get("phase1") or {}))
            + len((case_data.get("phaseFB") or {}))
            + len((case_data.get("phaseTL") or {}))
            + (1 if case_data.get("phase3") is not None else 0)
            for item in payload.values()
            for case_data in (item.get("cases") or {}).values()
        ),
        "is_empty": is_empty,
        "status": "empty" if is_empty else ("unchanged" if same_as_previous else "ok"),
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    eval_dir = snapshot_dir / "evaluators"
    eval_dir.mkdir(exist_ok=True)
    for evaluator, data in payload.items():
        (eval_dir / f"{evaluator}.json").write_text(
            json.dumps({evaluator: data}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def main() -> int:
    args = parse_args()
    db = init_firestore(args.service_account)
    snapshot_timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    payload = build_export_payload(db, snapshot_timestamp)
    payload_hash = content_hash(payload)
    latest = get_latest_snapshot_meta(db, exclude_snapshot_id=args.snapshot_id)

    write_snapshot(db, args.snapshot_id, payload, payload_hash, previous_snapshot=latest)
    if args.local_dir:
        write_local_snapshot(args.local_dir, args.snapshot_id, payload, payload_hash)

    print(
        f"Backup written: snapshot={args.snapshot_id} evaluators={len(payload)} "
        f"cases={sum(len(item.get('cases') or {}) for item in payload.values())} "
        f"hash={payload_hash[:12]}... same_as_previous={bool(latest and latest.get('content_hash') == payload_hash)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
