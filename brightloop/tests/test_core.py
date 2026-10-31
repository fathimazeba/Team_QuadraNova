"""
Unit and Integration Tests for Brightloop Core Infrastructure.
Validates Database constraints, Transaction Rollbacks, Money precision,
Scrypt hashing, Session hashing, and Transactional Outbox leases/reclamation.
"""

import unittest
import os
import tempfile
import sqlite3
from decimal import Decimal
from datetime import datetime, timedelta

from brightloop.core.database import DatabaseManager
from brightloop.core.money import Money, CurrencyMismatchError
from brightloop.core.security import (
    validate_password_strength, hash_password, verify_password,
    hash_token, generate_session_credentials, PasswordComplexityError
)
from brightloop.core.outbox import OutboxRepository

class TestCoreInfrastructure(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db = DatabaseManager(self.temp_db.name)
        self.db.init_schema()

    def tearDown(self):
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    # 1. Database Schema & Invariant Constraints Tests
    def test_database_foreign_keys_and_check_constraints(self):
        with self.db.transaction() as conn:
            # Valid insert
            conn.execute(
                "INSERT INTO products (name, type, sales_price_minor_units) VALUES (?, ?, ?)",
                ("Test Product", "SOFTWARE", 5000)
            )

            # Invariant: Negative sales_price_minor_units must fail
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO products (name, type, sales_price_minor_units) VALUES (?, ?, ?)",
                    ("Invalid Product", "SOFTWARE", -100)
                )

            # Invariant: Currency must be 3 uppercase letters
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO customers (company_name, currency) VALUES (?, ?)",
                    ("Bad Currency Inc", "usd") # lowercase fails
                )

            # Invariant: Discount usage count cannot exceed max_usage_count
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO discount_rules (
                        name, code, discount_type, value_minor_units_or_basis_points,
                        scope, start_date, max_usage_count, current_usage_count
                    ) VALUES ('Promo', 'PROMO10', 'PERCENTAGE', 1000, 'WHOLE_SUBSCRIPTION', '2026-01-01', 5, 6)
                    """
                )

    def test_discount_redemption_uniqueness_on_invoice(self):
        with self.db.transaction() as conn:
            # Setup prerequisite records
            conn.execute("INSERT INTO customers (company_name) VALUES ('Acme')")
            cust_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute("INSERT INTO subscription_plans (name, billing_frequency, available_from) VALUES ('Plan', 'MONTHLY', '2026-01-01')")
            plan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                "INSERT INTO subscriptions (subscription_number, customer_id, plan_id, status, start_date) VALUES ('SUB-1', ?, ?, 'ACTIVE', '2026-01-01')",
                (cust_id, plan_id)
            )
            sub_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                """
                INSERT INTO invoices (
                    invoice_number, subscription_id, customer_id, status,
                    issue_date, due_date, billing_period_start, billing_period_end, idempotency_key
                ) VALUES ('INV-1', ?, ?, 'DRAFT', '2026-01-01', '2026-01-31', '2026-01-01', '2026-01-31', 'IDEMP-1')
                """,
                (sub_id, cust_id)
            )
            inv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                """
                INSERT INTO discount_rules (
                    name, code, discount_type, value_minor_units_or_basis_points,
                    scope, start_date
                ) VALUES ('Early Bird', 'EARLY10', 'FIXED_AMOUNT', 1000, 'WHOLE_SUBSCRIPTION', '2026-01-01')
                """
            )
            disc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # First redemption succeeds
            conn.execute(
                "INSERT INTO discount_redemptions (discount_rule_id, subscription_id, invoice_id, amount_minor_units) VALUES (?, ?, ?, 1000)",
                (disc_id, sub_id, inv_id)
            )

            # Second redemption on the same invoice must trigger UNIQUE(discount_rule_id, invoice_id) error
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO discount_redemptions (discount_rule_id, subscription_id, invoice_id, amount_minor_units) VALUES (?, ?, ?, 1000)",
                    (disc_id, sub_id, inv_id)
                )

    # 2. Transaction Rollback Tests
    def test_atomic_transaction_rollback(self):
        try:
            with self.db.transaction() as conn:
                conn.execute("INSERT INTO customers (company_name) VALUES ('Rollback Corp')")
                raise RuntimeError("Simulated failure in multi-step orchestration")
        except RuntimeError:
            pass

        # Verify nothing was committed
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM customers WHERE company_name = 'Rollback Corp'")
            self.assertEqual(cursor.fetchone()[0], 0)

    # 3. Money & Minor Units Precision Tests
    def test_money_precision_and_rounding(self):
        # Exact conversion from Decimal
        m1 = Money.from_decimal("1200.50", "USD")
        self.assertEqual(m1.minor_units, 120050)
        self.assertEqual(m1.to_decimal(), Decimal("1200.50"))

        # Banker's / Commercial Rounding HALF_UP
        m2 = Money.from_decimal(Decimal("10.005"), "USD")
        self.assertEqual(m2.minor_units, 1001)

        # Arithmetic operations
        m3 = Money(5000, "USD")
        m4 = Money(2500, "USD")
        self.assertEqual((m3 + m4).minor_units, 7500)
        self.assertEqual((m3 - m4).minor_units, 2500)

        # Basis points calculation: 18.5% tax on $100.00
        tax = Money(10000, "USD").apply_basis_points(1850)
        self.assertEqual(tax.minor_units, 1850)

        # Currency mismatch safety
        m_eur = Money(5000, "EUR")
        with self.assertRaises(CurrencyMismatchError):
            _ = m3 + m_eur

    # 4. Security, Scrypt Hashing & Session Token Tests
    def test_scrypt_password_hashing_and_complexity(self):
        pwd = "BrightLoop#2026"
        validate_password_strength(pwd)

        with self.assertRaises(PasswordComplexityError):
            validate_password_strength("short")
        with self.assertRaises(PasswordComplexityError):
            validate_password_strength("nouppercase#123")
        with self.assertRaises(PasswordComplexityError):
            validate_password_strength("NOLOWERCASE#123")
        with self.assertRaises(PasswordComplexityError):
            validate_password_strength("NoSpecialChar123")

        pwd_hash, salt = hash_password(pwd)
        self.assertEqual(len(pwd_hash), 64)
        self.assertEqual(len(salt), 32)

        self.assertTrue(verify_password(pwd, pwd_hash, salt))
        self.assertFalse(verify_password("WrongPassword#1", pwd_hash, salt))

    def test_session_token_hashing(self):
        raw_token, token_hash, csrf_token = generate_session_credentials()
        self.assertNotEqual(raw_token, token_hash)
        self.assertEqual(hash_token(raw_token), token_hash)
        self.assertTrue(len(csrf_token) >= 32)

    # 5. Transactional Outbox Engine Tests
    def test_outbox_enqueue_lease_and_reclamation(self):
        outbox = OutboxRepository(self.db)

        # Enqueue event
        event_id = outbox.enqueue(
            event_type="GENERATE_INVOICE_PDF",
            payload={"invoice_id": 42},
            idempotency_key="PDF-INV-42"
        )
        self.assertGreater(event_id, 0)

        # Worker 1 leases event for 2 seconds
        events = outbox.lease_next_batch(worker_id="worker_alpha", batch_size=5, lease_seconds=2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].id, event_id)
        self.assertEqual(events[0].locked_by, "worker_alpha")
        self.assertEqual(events[0].status, "PROCESSING")

        # Worker 2 attempts to lease while worker 1 has an active lease -> gets 0
        events_worker2 = outbox.lease_next_batch(worker_id="worker_beta", batch_size=5)
        self.assertEqual(len(events_worker2), 0)

        # Simulate lease expiration manually
        past_time = (datetime.utcnow() - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db.transaction() as conn:
            conn.execute("UPDATE outbox_events SET lease_expires_at = ? WHERE id = ?", (past_time, event_id))

        # Worker 2 reclaims the expired lease
        reclaimed = outbox.lease_next_batch(worker_id="worker_beta", batch_size=5, lease_seconds=10)
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(reclaimed[0].id, event_id)
        self.assertEqual(reclaimed[0].locked_by, "worker_beta")

        # Mark event completed
        outbox.complete_event(event_id)

        # No more pending events
        empty_batch = outbox.lease_next_batch(worker_id="worker_alpha")
        self.assertEqual(len(empty_batch), 0)

if __name__ == "__main__":
    unittest.main()