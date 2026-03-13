"""
Initialize the SQLite database with the bus booking MVP schema.

This is intentionally idempotent: it uses CREATE TABLE IF NOT EXISTS and seeds
only if tables are empty.

Run:
  python init_db.py

Environment:
  - SQLITE_DB (optional): full path to the sqlite db file. If not set, uses the
    repository's default myapp.db location.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional


def _db_path() -> str:
    """Resolve SQLite DB path from env or default repo location."""
    env_path = os.getenv("SQLITE_DB")
    if env_path:
        return env_path

    # Default to this container's myapp.db
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "myapp.db")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.execute(f"SELECT COUNT(1) AS c FROM {table}")
    return int(cur.fetchone()["c"])


def _maybe_seed(conn: sqlite3.Connection) -> None:
    """
    Seed minimal demo data for MVP browsing.

    We seed only if core tables are empty, to avoid clobbering user data.
    """
    if _table_count(conn, "routes") > 0:
        return

    # Routes
    conn.execute(
        """
        INSERT INTO routes (origin, destination, distance_km, duration_min)
        VALUES (?, ?, ?, ?)
        """,
        ("San Francisco", "San Jose", 77, 75),
    )
    conn.execute(
        """
        INSERT INTO routes (origin, destination, distance_km, duration_min)
        VALUES (?, ?, ?, ?)
        """,
        ("San Francisco", "Sacramento", 140, 105),
    )

    # Buses + seat layouts
    # Layout is stored as JSON-ish text for simplicity in MVP.
    # We'll create a 4x10 grid: A/B left, C/D right with an aisle.
    seat_layout = {
        "rows": 10,
        "cols": 5,
        "legend": {"S": "seat", "_": "aisle"},
        "grid": [
            ["S", "S", "_", "S", "S"],
            ["S", "S", "_", "S", "S"],
            ["S", "S", "_", "S", "S"],
            ["S", "S", "_", "S", "S"],
            ["S", "S", "_", "S", "S"],
            ["S", "S", "_", "S", "S"],
            ["S", "S", "_", "S", "S"],
            ["S", "S", "_", "S", "S"],
            ["S", "S", "_", "S", "S"],
            ["S", "S", "_", "S", "S"],
        ],
        "seat_numbering": "ROWCOL",
    }
    conn.execute(
        """
        INSERT INTO buses (code, name, seat_layout_json)
        VALUES (?, ?, ?)
        """,
        ("BUS-100", "Blue Comet", str(seat_layout)),
    )
    conn.execute(
        """
        INSERT INTO buses (code, name, seat_layout_json)
        VALUES (?, ?, ?)
        """,
        ("BUS-200", "Aqua Arrow", str(seat_layout)),
    )

    # Trips (next few hours/days)
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    route_sf_sj = conn.execute("SELECT id FROM routes WHERE origin=? AND destination=?", ("San Francisco", "San Jose")).fetchone()["id"]
    route_sf_sac = conn.execute("SELECT id FROM routes WHERE origin=? AND destination=?", ("San Francisco", "Sacramento")).fetchone()["id"]
    bus_100 = conn.execute("SELECT id FROM buses WHERE code=?", ("BUS-100",)).fetchone()["id"]
    bus_200 = conn.execute("SELECT id FROM buses WHERE code=?", ("BUS-200",)).fetchone()["id"]

    trips = [
        (route_sf_sj, bus_100, (now + timedelta(hours=3)).isoformat(), 19.99),
        (route_sf_sj, bus_200, (now + timedelta(hours=6)).isoformat(), 24.99),
        (route_sf_sac, bus_100, (now + timedelta(days=1, hours=2)).isoformat(), 29.99),
    ]
    for route_id, bus_id, departure, price in trips:
        conn.execute(
            """
            INSERT INTO trips (route_id, bus_id, departure_time, price)
            VALUES (?, ?, ?, ?)
            """,
            (route_id, bus_id, departure, price),
        )

    # Seats for each bus (A1..A10, B1..B10, C1..C10, D1..D10)
    for bus in conn.execute("SELECT id FROM buses").fetchall():
        bus_id = int(bus["id"])
        for row in range(1, 11):
            for col in ["A", "B", "C", "D"]:
                seat_no = f"{col}{row}"
                conn.execute(
                    """
                    INSERT INTO seats (bus_id, seat_no, is_active)
                    VALUES (?, ?, 1)
                    """,
                    (bus_id, seat_no),
                )

    conn.commit()


def _create_schema(conn: sqlite3.Connection) -> None:
    # Core catalog
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            distance_km INTEGER,
            duration_min INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_routes_od ON routes(origin, destination);")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS buses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            seat_layout_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bus_id INTEGER NOT NULL,
            seat_no TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bus_id, seat_no),
            FOREIGN KEY(bus_id) REFERENCES buses(id) ON DELETE CASCADE
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seats_bus ON seats(bus_id);")

    # Trips
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id INTEGER NOT NULL,
            bus_id INTEGER NOT NULL,
            departure_time TEXT NOT NULL, -- ISO string
            price REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled', -- scheduled/cancelled
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(route_id) REFERENCES routes(id),
            FOREIGN KEY(bus_id) REFERENCES buses(id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trips_route_time ON trips(route_id, departure_time);")

    # Bookings
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_ref TEXT UNIQUE NOT NULL,
            trip_id INTEGER NOT NULL,
            passenger_name TEXT NOT NULL,
            passenger_email TEXT NOT NULL,
            passenger_phone TEXT,
            total_amount REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'confirmed', -- confirmed/cancelled
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(trip_id) REFERENCES trips(id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_trip ON bookings(trip_id);")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS booking_seats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            seat_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(booking_id, seat_id),
            UNIQUE(seat_id), -- prevent double-booking globally; used with transaction
            FOREIGN KEY(booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
            FOREIGN KEY(seat_id) REFERENCES seats(id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_booking_seats_booking ON booking_seats(booking_id);")

    # Minimal admin auth for MVP
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, -- MVP only; plaintext for simplicity (do NOT use in production)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Seed a default admin if none exists.
    cur = conn.execute("SELECT COUNT(1) AS c FROM admin_users")
    if int(cur.fetchone()["c"]) == 0:
        conn.execute(
            "INSERT INTO admin_users (username, password) VALUES (?, ?)",
            ("admin", "admin"),
        )

    # Track schema version in app_info (table already exists in template)
    conn.execute(
        """
        INSERT INTO app_info (key, value)
        VALUES ('bus_mvp_schema_version', '1')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )

    conn.commit()


def main(db_path: Optional[str] = None) -> None:
    db_path = db_path or _db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = _connect(db_path)
    try:
        _create_schema(conn)
        _maybe_seed(conn)
        print(f"Initialized bus MVP schema in: {db_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
