"""
One-time utility: wipe the price_bars table. Use this after a data-quality
fix (like switching to split-adjusted close prices) that needs a clean
re-backfill to take full effect on already-stored history.

Only touches price_bars -- your ticker list and past scan_results are left
alone. Run from the project root with your .env loaded:

    export $(cat .env | xargs)
    python -m app.wipe_data

Then repopulate with:

    python -m app.backfill
"""
from sqlalchemy import text

from app.db import init_db, engine


def run():
    init_db()
    with engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM price_bars")).scalar()
    print(f"price_bars currently has {before} rows.")

    if before == 0:
        print("Nothing to delete.")
        return

    print("Deleting all rows from price_bars...")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM price_bars"))

    with engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM price_bars")).scalar()
    print(f"Done. price_bars now has {after} rows.")
    print("Next: run `python -m app.backfill` to repopulate with corrected data.")


if __name__ == "__main__":
    run()
