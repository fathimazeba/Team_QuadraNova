"""
Core Database & Transaction Management for Brightloop.
Enforces WAL mode, foreign key constraints, busy timeouts, and atomic Unit of Work.
"""

import sqlite3
import os
from contextlib import contextmanager
from typing import Optional, Generator

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "brightloop.db")
SCHEMA_SQL_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

class DatabaseManager:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
            timeout=10.0
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def init_schema(self) -> None:
        if not os.path.exists(SCHEMA_SQL_PATH):
            raise FileNotFoundError(f"Schema file not found at {SCHEMA_SQL_PATH}")
        with open(SCHEMA_SQL_PATH, "r", encoding="utf-8") as f:
            ddl = f.read()

        conn = self.get_connection()
        try:
            conn.executescript(ddl)
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def transaction(self, existing_conn: Optional[sqlite3.Connection] = None) -> Generator[sqlite3.Connection, None, None]:
        if existing_conn is not None:
            # Join existing active transaction scope
            yield existing_conn
            return

        conn = self.get_connection()
        conn.execute("BEGIN IMMEDIATE;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

# Shared singleton instance
db_manager = DatabaseManager()