#!/usr/bin/env python3
"""Audit Firestore eval records — show what's stored per evaluator.

Usage:
  python scripts/audit_firestore.py --service-account <path>
  python scripts/audit_firestore.py --service-account <path> --delete-condorders
  python scripts/audit_firestore.py --service-account <path> --delete-all-for <evaluator>
"""

import argparse
import os
import sys
from collections import defaultdict

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    print("pip install firebase-admin", file=sys.stderr)
    raise SystemExit(2)


def init_db(sa_path):
    if not sa_path or not os.path.exists(sa_path):
        raise SystemExit(f"Service account not found: {sa_path}")
    cred = credentials.Certificate(sa_path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()


def audit(db):
    print("=" * 70)
    print("Firestore eval records audit")
    print("=" * 70)

    for ev_doc in db.collection("evals").stream():
        evaluator = ev_doc.id
        records = list(ev_doc.reference.collection("records").stream())

        condorders = []
        eval_records = []
        other = []

        for rec in records:
            data = rec.to_dict() or {}
            key = data.get("key", "")
            if "condorder" in key:
                condorders.append((key, data))
            elif "_phase" in key:
                eval_records.append((key, data))
            else:
                other.append((key, data))

        print(f"\n{'─' * 60}")
        print(f"評估者: {evaluator}")
        print(f"  總筆數: {len(records)}")
        print(f"  condorder (條件排序): {len(condorders)}")
        print(f"  eval 資料 (實際評分): {len(eval_records)}")
        print(f"  其他: {len(other)}")

        if eval_records:
            # Group by case
            cases = defaultdict(list)
            for key, data in eval_records:
                # Extract case name: eval_v2_{ev}_{caseName}_{cond}_phase{N}
                prefix = f"eval_v2_{evaluator}_"
                if key.startswith(prefix):
                    rest = key[len(prefix):]
                    cases[rest].append(data)

            print(f"\n  實際評分資料:")
            for case_key, items in sorted(cases.items()):
                saved = ""
                for item in items:
                    d = item.get("data", {})
                    if isinstance(d, dict) and d.get("_saved"):
                        saved = d["_saved"]
                        break
                has_scores = any(
                    isinstance(item.get("data", {}), dict) and item.get("data", {}).get("scores")
                    for item in items
                )
                complete = any(
                    isinstance(item.get("data", {}), dict) and item.get("data", {}).get("_complete")
                    for item in items
                )
                status = "完成" if complete else ("有分數" if has_scores else "空殼")
                print(f"    {case_key}")
                print(f"      狀態: {status} | 最後儲存: {saved}")

        if other:
            print(f"\n  其他 keys:")
            for key, _ in other:
                print(f"    {key}")


def delete_condorders(db):
    """Delete all condorder records (they get regenerated on page load)."""
    total = 0
    for ev_doc in db.collection("evals").stream():
        evaluator = ev_doc.id
        batch = db.batch()
        count = 0
        for rec in ev_doc.reference.collection("records").stream():
            data = rec.to_dict() or {}
            key = data.get("key", "")
            if "condorder" in key:
                batch.delete(rec.reference)
                count += 1
                if count >= 450:
                    batch.commit()
                    batch = db.batch()
                    total += count
                    count = 0
        if count > 0:
            batch.commit()
            total += count
        print(f"  {evaluator}: 刪除 {total} 筆 condorder")
    print(f"\n共刪除 {total} 筆 condorder 記錄")


def delete_all_for(db, evaluator):
    """Delete ALL records for a specific evaluator."""
    ref = db.collection("evals").document(evaluator).collection("records")
    docs = list(ref.stream())
    if not docs:
        print(f"  {evaluator}: 無資料")
        return

    confirm = input(f"確定要刪除 {evaluator} 的 {len(docs)} 筆記錄？(yes/no): ")
    if confirm.lower() != "yes":
        print("取消")
        return

    batch = db.batch()
    count = 0
    for doc in docs:
        batch.delete(doc.reference)
        count += 1
        if count >= 450:
            batch.commit()
            batch = db.batch()
            count = 0
    if count > 0:
        batch.commit()
    print(f"  已刪除 {evaluator} 的 {len(docs)} 筆記錄")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-account",
                        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS",
                                               r"D:\secrets\firebase\law-eval-2f86e-firebase-adminsdk-fbsvc-09d9ce2185.json"))
    parser.add_argument("--delete-condorders", action="store_true",
                        help="刪除所有 condorder 記錄（不影響實際評分資料）")
    parser.add_argument("--delete-all-for", type=str, default="",
                        help="刪除指定評估者的全部記錄")
    args = parser.parse_args()

    db = init_db(args.service_account)

    if args.delete_condorders:
        delete_condorders(db)
    elif args.delete_all_for:
        delete_all_for(db, args.delete_all_for)
    else:
        audit(db)


if __name__ == "__main__":
    main()
