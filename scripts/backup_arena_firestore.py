#!/usr/bin/env python3
"""Daily Firestore snapshot backup for arena votes.

Reads latest arena vote records from:
  arena_evals/{evaluatorUid}/records/{recordId}

Builds a normalized daily export grouped by evaluator, then writes immutable
daily snapshot data to:
  arena_backups_daily/{YYYY-MM-DD}
  arena_backups_daily/{YYYY-MM-DD}/evaluators/{evaluator}

Also writes local backups to:
  {local_root}/arena/{YYYY-MM-DD}/
    all.json
    manifest.json
    evaluators/{name}.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
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


REPO_ROOT = Path(__file__).resolve().parents[1]
ARENA_HTML = REPO_ROOT / "arena.html"
ARENA_CONFIG_PATH = REPO_ROOT / "data" / "arena_config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backup arena Firestore records into daily snapshots.")
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


def load_arena_runtime_constants() -> Tuple[str, str]:
    text = ARENA_HTML.read_text(encoding="utf-8")
    campaign_match = re.search(r"const\s+ARENA_CAMPAIGN_ID\s*=\s*'([^']+)'", text)
    version_match = re.search(r"const\s+ARENA_STORAGE_VERSION\s*=\s*'([^']+)'", text)
    if not campaign_match or not version_match:
        raise SystemExit("Failed to parse ARENA_CAMPAIGN_ID / ARENA_STORAGE_VERSION from arena.html")
    return campaign_match.group(1), version_match.group(1)


def load_arena_config() -> Dict[str, Any]:
    return json.loads(ARENA_CONFIG_PATH.read_text(encoding="utf-8"))


def make_hash_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove snapshot-run volatile fields so unchanged content hashes stay stable."""
    cloned = json.loads(json.dumps(payload, ensure_ascii=False))
    meta = cloned.get("meta") or {}
    meta.pop("snapshot_timestamp", None)
    for item in (cloned.get("evaluators") or {}).values():
        item_meta = item.get("meta") or {}
        item_meta.pop("snapshot_timestamp", None)
    return cloned


def get_all_pairs(config: Dict[str, Any]) -> list[tuple[str, str]]:
    conditions = list(config.get("conditions") or [])
    pairs: list[tuple[str, str]] = []
    for i in range(len(conditions)):
        for j in range(i + 1, len(conditions)):
            pair = tuple(sorted((conditions[i], conditions[j])))
            pairs.append(pair)
    return pairs


def get_pair_weight(config: Dict[str, Any], cond_a: str, cond_b: str) -> int:
    backbone_map = config.get("backbone_map") or {}
    role_map = config.get("role_map") or {}
    weights = config.get("pair_weights") or {}
    back_a = backbone_map.get(cond_a)
    back_b = backbone_map.get(cond_b)
    role_a = role_map.get(cond_a)
    role_b = role_map.get(cond_b)
    same_bb = back_a == back_b
    roles = "_".join(sorted([str(role_a or ""), str(role_b or "")]))
    if same_bb:
        if roles == "baseline_full":
            return int(weights.get("same_backbone_full_vs_baseline", 0) or 0)
        return 0
    if roles == "full_full":
        return int(weights.get("cross_backbone_full_vs_full", 0) or 0)
    if roles == "baseline_baseline":
        return int(weights.get("cross_backbone_baseline_vs_baseline", 0) or 0)
    return int(weights.get("cross_backbone_other", 0) or 0)


def get_effective_pairs(config: Dict[str, Any]) -> list[Dict[str, Any]]:
    pairs = []
    for cond_a, cond_b in get_all_pairs(config):
        weight = get_pair_weight(config, cond_a, cond_b)
        if weight <= 0:
            continue
        pairs.append({"condA": cond_a, "condB": cond_b, "weight": weight})
    return sorted(
        pairs,
        key=lambda item: (
            -int(item["weight"]),
            str(item["condA"]),
            str(item["condB"]),
        ),
    )


def is_current_campaign_vote(
    vote: Dict[str, Any],
    config: Dict[str, Any],
    campaign_id: str,
) -> bool:
    if not isinstance(vote, dict):
        return False
    if vote.get("_campaign_id") != campaign_id:
        return False
    cond_a = str(vote.get("condition_a") or "")
    cond_b = str(vote.get("condition_b") or "")
    if not cond_a or not cond_b:
        return False
    pair = sorted([cond_a, cond_b])
    conditions = set(config.get("conditions") or [])
    if pair[0] not in conditions or pair[1] not in conditions:
        return False
    return get_pair_weight(config, pair[0], pair[1]) > 0


def load_arena_users(db) -> Dict[str, Dict[str, str]]:
    by_uid: Dict[str, Dict[str, str]] = {}
    for doc in db.collection("arena_users").stream():
        payload = doc.to_dict() or {}
        uid = str(payload.get("uid") or doc.id)
        by_uid[uid] = {
            "uid": uid,
            "name": str(payload.get("name") or uid),
            "email": str(payload.get("email") or ""),
            "role": str(payload.get("role") or ""),
        }
    return by_uid


def iter_evaluator_votes(
    db,
    config: Dict[str, Any],
    campaign_id: str,
    users_by_uid: Dict[str, Dict[str, str]],
) -> Iterable[Tuple[str, Dict[str, Any]]]:
    expected_names = list(config.get("evaluators") or [])
    seen_names: set[str] = set()

    for evaluator_ref in db.collection("arena_evals").list_documents():
        uid = evaluator_ref.id
        user = users_by_uid.get(uid, {"uid": uid, "name": uid, "email": "", "role": ""})
        name = str(user.get("name") or uid)
        votes = []
        for rec_doc in evaluator_ref.collection("records").stream():
            payload = rec_doc.to_dict() or {}
            vote = payload.get("data") or {}
            if is_current_campaign_vote(vote, config, campaign_id):
                votes.append(vote)
        votes.sort(key=lambda item: str(item.get("timestamp") or ""))
        seen_names.add(name)
        yield name, {
            "uid": uid,
            "email": str(user.get("email") or ""),
            "role": str(user.get("role") or ""),
            "votes": votes,
        }

    for name in expected_names:
        if name in seen_names:
            continue
        matched_uid = ""
        matched_email = ""
        matched_role = ""
        for uid, user in users_by_uid.items():
            if str(user.get("name") or "") == name:
                matched_uid = uid
                matched_email = str(user.get("email") or "")
                matched_role = str(user.get("role") or "")
                break
        yield name, {
            "uid": matched_uid,
            "email": matched_email,
            "role": matched_role,
            "votes": [],
        }


def calc_aggregate_elo(votes: list[Dict[str, Any]], config: Dict[str, Any]) -> list[Dict[str, Any]]:
    elo: Dict[str, Dict[str, Any]] = {}
    for cond in config.get("conditions") or []:
        elo[cond] = {"rating": 1000.0, "wins": 0, "draws": 0, "losses": 0, "matches": 0, "cases": set()}
    for vote in votes:
        cond_a = str(vote.get("condition_a") or "")
        cond_b = str(vote.get("condition_b") or "")
        if cond_a not in elo or cond_b not in elo:
            continue
        elo[cond_a]["matches"] += 1
        elo[cond_b]["matches"] += 1
        case_id = str(vote.get("case_id") or "")
        if case_id:
            elo[cond_a]["cases"].add(case_id)
            elo[cond_b]["cases"].add(case_id)
        expected_a = 1 / (1 + pow(10, (elo[cond_b]["rating"] - elo[cond_a]["rating"]) / 400))
        expected_b = 1 - expected_a
        k_value = 32
        winner = str(vote.get("winner") or "")
        if winner == "a":
            score_a = 1.0
            score_b = 0.0
            elo[cond_a]["wins"] += 1
            elo[cond_b]["losses"] += 1
        elif winner == "b":
            score_a = 0.0
            score_b = 1.0
            elo[cond_b]["wins"] += 1
            elo[cond_a]["losses"] += 1
        else:
            score_a = 0.5
            score_b = 0.5
            elo[cond_a]["draws"] += 1
            elo[cond_b]["draws"] += 1
        elo[cond_a]["rating"] += k_value * (score_a - expected_a)
        elo[cond_b]["rating"] += k_value * (score_b - expected_b)
    rows = []
    labels = config.get("condition_labels") or {}
    for cond, data in elo.items():
        rows.append(
            {
                "condition": cond,
                "label": str(labels.get(cond) or cond),
                "rating": int(round(float(data["rating"]))),
                "wins": int(data["wins"]),
                "draws": int(data["draws"]),
                "losses": int(data["losses"]),
                "matches": int(data["matches"]),
                "case_count": len(data["cases"]),
                "backbone": str((config.get("backbone_map") or {}).get(cond) or ""),
                "role": str((config.get("role_map") or {}).get(cond) or ""),
            }
        )
    return sorted(rows, key=lambda item: (-int(item["rating"]), str(item["condition"])))


def build_export_payload(
    db,
    snapshot_timestamp: str,
    config: Dict[str, Any],
    campaign_id: str,
    storage_version: str,
) -> Dict[str, Any]:
    users_by_uid = load_arena_users(db)
    effective_pairs = get_effective_pairs(config)
    case_meta = {str(item.get("case_id") or ""): item for item in (config.get("cases") or [])}

    evaluators: Dict[str, Any] = {}
    all_votes: list[Dict[str, Any]] = []

    for name, item in sorted(iter_evaluator_votes(db, config, campaign_id, users_by_uid), key=lambda kv: kv[0]):
        votes = list(item.get("votes") or [])
        vote_count = len(votes)
        case_ids = sorted({str(v.get("case_id") or "") for v in votes if v.get("case_id")})
        pair_keys = sorted(
            {
                f"{v.get('case_id') or ''}||{'||'.join(sorted([str(v.get('condition_a') or ''), str(v.get('condition_b') or '')]))}"
                for v in votes
            }
        )
        last_timestamp = max((str(v.get("timestamp") or "") for v in votes), default="")
        evaluator_payload = {
            "meta": {
                "name": name,
                "uid": str(item.get("uid") or ""),
                "email": str(item.get("email") or ""),
                "role": str(item.get("role") or ""),
                "snapshot_timestamp": snapshot_timestamp,
                "storage_version": storage_version,
                "campaign_id": campaign_id,
            },
            "summary": {
                "vote_count": vote_count,
                "case_count": len(case_ids),
                "pair_count": len(pair_keys),
                "last_timestamp": last_timestamp,
                "completed_case_count": sum(
                    1
                    for case_id in case_ids
                    if sum(1 for vote in votes if str(vote.get("case_id") or "") == case_id) >= len(effective_pairs)
                ),
            },
            "votes": votes,
        }
        evaluators[name] = evaluator_payload
        all_votes.extend(votes)

    all_votes.sort(key=lambda item: str(item.get("timestamp") or ""))
    case_ids = sorted({str(v.get("case_id") or "") for v in all_votes if v.get("case_id")})
    pair_keys = sorted(
        {
            f"{v.get('case_id') or ''}||{'||'.join(sorted([str(v.get('condition_a') or ''), str(v.get('condition_b') or '')]))}"
            for v in all_votes
        }
    )

    aggregate = {
        "vote_count": len(all_votes),
        "case_count": len(case_ids),
        "pair_count": len(pair_keys),
        "expected_pairs_per_case": len(effective_pairs),
        "expected_vote_count_per_evaluator": len(effective_pairs) * len(config.get("cases") or []),
        "elo_snapshot": calc_aggregate_elo(all_votes, config),
        "effective_pairs": effective_pairs,
    }

    return {
        "meta": {
            "snapshot_timestamp": snapshot_timestamp,
            "storage_version": storage_version,
            "campaign_id": campaign_id,
            "evaluator_names": sorted(evaluators.keys()),
        },
        "config": {
            "conditions": list(config.get("conditions") or []),
            "condition_labels": dict(config.get("condition_labels") or {}),
            "backbone_map": dict(config.get("backbone_map") or {}),
            "role_map": dict(config.get("role_map") or {}),
            "cases": [case_meta[str(item.get("case_id") or "")] for item in (config.get("cases") or [])],
        },
        "evaluators": evaluators,
        "aggregate": aggregate,
    }


def get_latest_snapshot_meta(db, exclude_snapshot_id: str = "") -> Dict[str, Any] | None:
    docs = (
        db.collection("arena_backups_daily")
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
    campaign_id: str,
    storage_version: str,
    previous_snapshot: Dict[str, Any] | None = None,
) -> None:
    snapshot_ref = db.collection("arena_backups_daily").document(snapshot_id)
    evaluators = payload.get("evaluators") or {}
    aggregate = payload.get("aggregate") or {}
    previous_snapshot_id = previous_snapshot.get("_id") if previous_snapshot else ""
    previous_content_hash = previous_snapshot.get("content_hash") if previous_snapshot else ""
    same_as_previous = bool(previous_snapshot_id) and previous_content_hash == payload_hash
    vote_count = int(aggregate.get("vote_count") or 0)
    status = "empty" if vote_count == 0 else ("unchanged" if same_as_previous else "ok")

    meta = {
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_id,
        "created_at": firestore.SERVER_TIMESTAMP,
        "content_hash": payload_hash,
        "same_as_previous": same_as_previous,
        "previous_snapshot_id": previous_snapshot_id,
        "previous_content_hash": previous_content_hash,
        "evaluator_count": len(evaluators),
        "evaluator_names": list((payload.get("meta") or {}).get("evaluator_names") or []),
        "vote_count": vote_count,
        "case_count": int(aggregate.get("case_count") or 0),
        "pair_count": int(aggregate.get("pair_count") or 0),
        "expected_pairs_per_case": int(aggregate.get("expected_pairs_per_case") or 0),
        "expected_vote_count_per_evaluator": int(aggregate.get("expected_vote_count_per_evaluator") or 0),
        "elo_snapshot": aggregate.get("elo_snapshot") or [],
        "is_empty": vote_count == 0,
        "status": status,
        "schema_version": "arena_daily_backup_v1",
        "storage_version": storage_version,
        "campaign_id": campaign_id,
    }

    existing_evaluator_docs = list(snapshot_ref.collection("evaluators").stream())
    batch = db.batch()
    batch.set(snapshot_ref, meta)
    live_names = set(evaluators.keys())
    for doc in existing_evaluator_docs:
        if doc.id not in live_names:
            batch.delete(doc.reference)
    for name, data in evaluators.items():
        summary = data.get("summary") or {}
        ref = snapshot_ref.collection("evaluators").document(name)
        batch.set(
            ref,
            {
                "evaluator": name,
                "uid": str((data.get("meta") or {}).get("uid") or ""),
                "email": str((data.get("meta") or {}).get("email") or ""),
                "role": str((data.get("meta") or {}).get("role") or ""),
                "vote_count": int(summary.get("vote_count") or 0),
                "case_count": int(summary.get("case_count") or 0),
                "pair_count": int(summary.get("pair_count") or 0),
                "completed_case_count": int(summary.get("completed_case_count") or 0),
                "last_timestamp": str(summary.get("last_timestamp") or ""),
                "content_hash": content_hash(data),
                "storage_version": storage_version,
                "campaign_id": campaign_id,
                "data": data,
            },
        )
    batch.commit()


def write_local_snapshot(
    local_dir: str,
    snapshot_id: str,
    payload: Dict[str, Any],
    payload_hash: str,
    campaign_id: str,
    storage_version: str,
) -> None:
    root = Path(local_dir) / "arena"
    snapshot_dir = root / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "all.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    previous_snapshot_id = ""
    previous_content_hash = ""
    same_as_previous = False
    if root.exists():
        candidates = sorted(
            [p for p in root.iterdir() if p.is_dir() and p.name != snapshot_id and (p / "manifest.json").exists()],
            key=lambda path: path.name,
            reverse=True,
        )
        if candidates:
            previous_manifest = json.loads((candidates[0] / "manifest.json").read_text(encoding="utf-8"))
            previous_snapshot_id = str(previous_manifest.get("snapshot_id") or candidates[0].name)
            previous_content_hash = str(previous_manifest.get("content_hash") or "")
            same_as_previous = previous_content_hash == payload_hash

    aggregate = payload.get("aggregate") or {}
    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "content_hash": payload_hash,
        "same_as_previous": same_as_previous,
        "previous_snapshot_id": previous_snapshot_id,
        "previous_content_hash": previous_content_hash,
        "evaluator_count": len(payload.get("evaluators") or {}),
        "evaluator_names": list((payload.get("meta") or {}).get("evaluator_names") or []),
        "vote_count": int(aggregate.get("vote_count") or 0),
        "case_count": int(aggregate.get("case_count") or 0),
        "pair_count": int(aggregate.get("pair_count") or 0),
        "expected_pairs_per_case": int(aggregate.get("expected_pairs_per_case") or 0),
        "expected_vote_count_per_evaluator": int(aggregate.get("expected_vote_count_per_evaluator") or 0),
        "elo_snapshot": aggregate.get("elo_snapshot") or [],
        "is_empty": int(aggregate.get("vote_count") or 0) == 0,
        "status": "empty" if int(aggregate.get("vote_count") or 0) == 0 else ("unchanged" if same_as_previous else "ok"),
        "storage_version": storage_version,
        "campaign_id": campaign_id,
        "schema_version": "arena_daily_backup_v1",
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    eval_dir = snapshot_dir / "evaluators"
    eval_dir.mkdir(exist_ok=True)
    for old_file in eval_dir.glob("*.json"):
        if old_file.stem not in (payload.get("evaluators") or {}):
            old_file.unlink()
    for name, data in (payload.get("evaluators") or {}).items():
        (eval_dir / f"{name}.json").write_text(
            json.dumps({name: data}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def main() -> int:
    args = parse_args()
    db = init_firestore(args.service_account)
    campaign_id, storage_version = load_arena_runtime_constants()
    config = load_arena_config()
    snapshot_timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    payload = build_export_payload(
        db=db,
        snapshot_timestamp=snapshot_timestamp,
        config=config,
        campaign_id=campaign_id,
        storage_version=storage_version,
    )
    payload_hash = content_hash(make_hash_payload(payload))
    latest = get_latest_snapshot_meta(db, exclude_snapshot_id=args.snapshot_id)

    write_snapshot(
        db=db,
        snapshot_id=args.snapshot_id,
        payload=payload,
        payload_hash=payload_hash,
        campaign_id=campaign_id,
        storage_version=storage_version,
        previous_snapshot=latest,
    )
    if args.local_dir:
        write_local_snapshot(
            local_dir=args.local_dir,
            snapshot_id=args.snapshot_id,
            payload=payload,
            payload_hash=payload_hash,
            campaign_id=campaign_id,
            storage_version=storage_version,
        )

    aggregate = payload.get("aggregate") or {}
    print(
        f"Arena backup written: snapshot={args.snapshot_id} "
        f"evaluators={len(payload.get('evaluators') or {})} "
        f"votes={int(aggregate.get('vote_count') or 0)} "
        f"cases={int(aggregate.get('case_count') or 0)} "
        f"hash={payload_hash[:12]}... "
        f"same_as_previous={bool(latest and latest.get('content_hash') == payload_hash)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
