"""
Core Transactional Outbox Engine.
Provides persistent background job queueing within the same database transaction,
worker lease acquisition, automatic stale lease reclamation, and retry management.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

class OutboxEvent:
    def __init__(
        self,
        id: int,
        event_type: str,
        payload: Dict[str, Any],
        status: str,
        scheduled_for: datetime,
        locked_by: Optional[str] = None,
        lease_expires_at: Optional[datetime] = None,
        retry_count: int = 0,
        max_retries: int = 5,
        last_error: Optional[str] = None,
        idempotency_key: Optional[str] = None
    ):
        self.id = id
        self.event_type = event_type
        self.payload = payload
        self.status = status
        self.scheduled_for = scheduled_for
        self.locked_by = locked_by
        self.lease_expires_at = lease_expires_at
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.last_error = last_error
        self.idempotency_key = idempotency_key

class OutboxRepository:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def enqueue(
        self,
        event_type: str,
        payload: Dict[str, Any],
        scheduled_for: Optional[datetime] = None,
        idempotency_key: Optional[str] = None,
        max_retries: int = 5,
        tx: Optional[sqlite3.Connection] = None
    ) -> int:
        if scheduled_for is None:
            scheduled_for = datetime.utcnow()

        payload_json = json.dumps(payload)
        scheduled_str = scheduled_for.strftime("%Y-%m-%d %H:%M:%S")

        with self.db_manager.transaction(existing_conn=tx) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO outbox_events (
                    event_type, payload_json, status, scheduled_for,
                    max_retries, idempotency_key
                ) VALUES (?, ?, 'PENDING', ?, ?, ?)
                """,
                (event_type, payload_json, scheduled_str, max_retries, idempotency_key)
            )
            return cursor.lastrowid

    def lease_next_batch(
        self,
        worker_id: str,
        batch_size: int = 10,
        lease_seconds: int = 60,
        tx: Optional[sqlite3.Connection] = None
    ) -> List[OutboxEvent]:
        """
        Atomically leases available or abandoned jobs.
        Reclaims jobs where status='PROCESSING' and lease_expires_at < CURRENT_TIMESTAMP.
        """
        now = datetime.utcnow()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        lease_expires = now + timedelta(seconds=lease_seconds)
        lease_expires_str = lease_expires.strftime("%Y-%m-%d %H:%M:%S")

        with self.db_manager.transaction(existing_conn=tx) as conn:
            cursor = conn.cursor()
            # Select candidate events
            cursor.execute(
                """
                SELECT id, event_type, payload_json, status, scheduled_for,
                       locked_by, lease_expires_at, retry_count, max_retries,
                       last_error, idempotency_key
                FROM outbox_events
                WHERE (status = 'PENDING' AND scheduled_for <= ?)
                   OR (status = 'PROCESSING' AND lease_expires_at < ?)
                ORDER BY scheduled_for ASC, id ASC
                LIMIT ?
                """,
                (now_str, now_str, batch_size)
            )
            rows = cursor.fetchall()
            if not rows:
                return []

            event_ids = [r["id"] for r in rows]
            placeholders = ",".join("?" for _ in event_ids)

            # Atomically lock and claim
            cursor.execute(
                f"""
                UPDATE outbox_events
                SET status = 'PROCESSING',
                    locked_by = ?,
                    locked_at = ?,
                    lease_expires_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                [worker_id, now_str, lease_expires_str] + event_ids
            )

            events = []
            for r in rows:
                events.append(OutboxEvent(
                    id=r["id"],
                    event_type=r["event_type"],
                    payload=json.loads(r["payload_json"]),
                    status='PROCESSING',
                    scheduled_for=datetime.fromisoformat(r["scheduled_for"]) if isinstance(r["scheduled_for"], str) else r["scheduled_for"],
                    locked_by=worker_id,
                    lease_expires_at=lease_expires,
                    retry_count=r["retry_count"],
                    max_retries=r["max_retries"],
                    last_error=r["last_error"],
                    idempotency_key=r["idempotency_key"]
                ))
            return events

    def complete_event(self, event_id: int, tx: Optional[sqlite3.Connection] = None) -> None:
        with self.db_manager.transaction(existing_conn=tx) as conn:
            conn.execute(
                """
                UPDATE outbox_events
                SET status = 'COMPLETED',
                    lease_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (event_id,)
            )

    def fail_event(
        self,
        event_id: int,
        error_message: str,
        backoff_seconds: int = 60,
        tx: Optional[sqlite3.Connection] = None
    ) -> None:
        """
        Increments retry count. If max_retries exceeded, sets status to FAILED.
        Otherwise schedules for future retry with exponential backoff.
        """
        now = datetime.utcnow()
        with self.db_manager.transaction(existing_conn=tx) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT retry_count, max_retries FROM outbox_events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            if not row:
                return

            new_count = row["retry_count"] + 1
            if new_count >= row["max_retries"]:
                cursor.execute(
                    """
                    UPDATE outbox_events
                    SET status = 'FAILED',
                        retry_count = ?,
                        last_error = ?,
                        lease_expires_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_count, error_message, event_id)
                )
            else:
                next_scheduled = now + timedelta(seconds=backoff_seconds * (2 ** (new_count - 1)))
                next_scheduled_str = next_scheduled.strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    """
                    UPDATE outbox_events
                    SET status = 'PENDING',
                        retry_count = ?,
                        last_error = ?,
                        scheduled_for = ?,
                        locked_by = NULL,
                        locked_at = NULL,
                        lease_expires_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_count, error_message, next_scheduled_str, event_id)
                )