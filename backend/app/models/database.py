"""SQLite database for storing food donations."""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Store DB file next to the backend folder
DB_PATH = Path(__file__).resolve().parent.parent.parent / "rizq_rescue.db"


def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection (creates DB + table on first call)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # return dict-like rows
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrency
    return conn


def init_db():
    """Create donations table if it doesn't exist."""
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS donations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            food_type   TEXT NOT NULL,
            quantity_kg REAL NOT NULL DEFAULT 0,
            serves_people INTEGER DEFAULT 0,
            status      TEXT NOT NULL DEFAULT 'pending',
            created_at  TEXT NOT NULL
        )
        """
    )
    # Backward-compatible migrations for older local DBs
    existing_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(donations)").fetchall()
    }
    if "volunteer_name" not in existing_cols:
        conn.execute("ALTER TABLE donations ADD COLUMN volunteer_name TEXT")
    if "volunteer_phone" not in existing_cols:
        conn.execute("ALTER TABLE donations ADD COLUMN volunteer_phone TEXT")
    if "assigned_at" not in existing_cols:
        conn.execute("ALTER TABLE donations ADD COLUMN assigned_at TEXT")

    conn.commit()
    conn.close()
    logger.info(f"Database initialised at {DB_PATH}")


def create_donation(
    food_type: str,
    quantity_kg: float,
    serves_people: int = 0,
) -> int:
    """Insert a new donation and return its id."""
    conn = get_connection()
    cur = conn.execute(
        """
        INSERT INTO donations (food_type, quantity_kg, serves_people, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
        """,
        (food_type, quantity_kg, serves_people, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    donation_id = cur.lastrowid
    conn.close()
    logger.info(
        f"Created donation #{donation_id}: {food_type}, {quantity_kg}kg, serves {serves_people}"
    )
    return donation_id


def get_donations() -> list[dict]:
    """Return all donations (newest first)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM donations ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_pending_donation() -> Optional[dict]:
    """Return the most recent pending donation, if any."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT * FROM donations
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_donation_status(donation_id: int, status: str) -> bool:
    """Update the status of a donation. Returns True if row found."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE donations SET status = ? WHERE id = ?",
        (status, donation_id),
    )
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def assign_volunteer_to_donation(
    donation_id: int,
    volunteer_name: str,
    volunteer_phone: str,
) -> bool:
    """Assign a volunteer and mark donation as assigned."""
    conn = get_connection()
    cur = conn.execute(
        """
        UPDATE donations
        SET status = 'assigned',
            volunteer_name = ?,
            volunteer_phone = ?,
            assigned_at = ?
        WHERE id = ?
        """,
        (
            volunteer_name,
            volunteer_phone,
            datetime.now(timezone.utc).isoformat(),
            donation_id,
        ),
    )
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def get_stats() -> dict:
    """Aggregate stats for the dashboard."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(*)          AS total_donations,
            COALESCE(SUM(quantity_kg), 0) AS total_kg,
            COUNT(CASE WHEN date(created_at) = date('now') THEN 1 END) AS donations_today
        FROM donations
        """
    ).fetchone()
    conn.close()
    return dict(row) if row else {"total_donations": 0, "total_kg": 0, "donations_today": 0}
