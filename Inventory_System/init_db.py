"""
Creates the SQLite DB, the two tables, and seeds Item A with 100 units.

Run once before you start the API:
    python init_db.py
"""

import os
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    String,
    DateTime,
    func,
)

DB_URL = os.getenv(
    "DATABASE_URL", "sqlite:///inventory.db?check_same_thread=False"
)

engine = create_engine(DB_URL, future=True)
metadata = MetaData()

# -----------------------------
# Inventory table
# -----------------------------
inventory_tbl = Table(
    "inventory",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("item_name", String(64), nullable=False, unique=True),
    Column("stock", Integer, nullable=False),
)

# -----------------------------
# Purchase record table
# -----------------------------
purchase_tbl = Table(
    "purchase_record",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("item_id", Integer, nullable=False),
    Column(
        "purchased_at",
        DateTime,
        nullable=False,
        server_default=func.now(),  # ✅ AUTO timestamp
    ),
)

def main():
    # Drop & recreate tables (clean start)
    metadata.drop_all(engine, checkfirst=True)
    metadata.create_all(engine)

    # Seed Item A with 100 units
    with engine.begin() as conn:
        conn.execute(
            inventory_tbl.insert().values(item_name="Item A", stock=100)
        )

    print("✅ SQLite DB created – Item A with 100 units.")

if __name__ == "__main__":
    main()
