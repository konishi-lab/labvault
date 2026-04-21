"""allowed_users に初期 admin を登録する。

使い方:
    python seed_admin.py <email> [display_name]

例:
    python seed_admin.py hirosuke-yonekubo@g.ecc.u-tokyo.ac.jp "米久保 紘資"

ADC 認証必須。Firestore の allowed_users/{email} に role=admin で upsert する。
"""

from __future__ import annotations

import datetime as dt
import os
import sys

from google.cloud import firestore


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    email = sys.argv[1].strip().lower()
    display_name = sys.argv[2] if len(sys.argv) >= 3 else email

    project = os.environ.get("LABVAULT_GCP_PROJECT")
    database = os.environ.get("LABVAULT_FIRESTORE_DATABASE", "(default)")
    if not project:
        print("LABVAULT_GCP_PROJECT not set", file=sys.stderr)
        return 1

    db = firestore.Client(project=project, database=database)
    ref = db.collection("allowed_users").document(email)

    now = dt.datetime.now(dt.UTC)
    ref.set(
        {
            "email": email,
            "display_name": display_name,
            "role": "admin",
            "active": True,
            "added_at": now,
        },
        merge=True,
    )
    print(f"OK: {email} registered as admin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
