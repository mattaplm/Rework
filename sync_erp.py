"""Manual one-off sync of items + colours + orders from SyteLine into
Postgres -- the scheduled background sync (services/scheduled_sync.py) and
Admin's manual buttons cover ongoing use; this is for running it by hand,
e.g. right after a fresh deploy.

    python sync_erp.py
"""

from __future__ import annotations

from services import erp_sync

if __name__ == "__main__":
    print(f"Synced {erp_sync.sync_items()} items.")
    print(f"Synced {erp_sync.sync_colours()} colours.")
    print(f"Synced orders: {erp_sync.sync_orders()}")
