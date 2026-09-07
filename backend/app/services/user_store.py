"""
User account storage. A small, low-write-volume table, so we query it with
FINAL to force ReplacingMergeTree deduplication at read time -- correctness
matters more than raw speed for "does this email already have an account"
and "log this person in", and this table will never hold enough rows for
FINAL's cost to matter.

Every write re-inserts the full row (ReplacingMergeTree has no in-place
UPDATE) with a fresh `version`; record_login() carries the existing row's
`created_at` forward unchanged so a login can never clobber the account's
real creation timestamp.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.db.clickhouse_client import insert_rows, query
from app.models.schemas import UserPublic, UserRole

_COLUMNS = [
    "user_id", "email", "hashed_password", "display_name", "role",
    "is_active", "created_at", "last_login_at", "version",
]


def _next_version() -> int:
    return time.time_ns() // 1000  # microseconds, matching toUnixTimestamp64Micro


def count_users() -> int:
    rows = query("SELECT count() AS n FROM users FINAL")
    return int(rows[0]["n"]) if rows else 0


def get_user_by_email(email: str) -> dict | None:
    rows = query(
        "SELECT * FROM users FINAL WHERE email = {email:String} AND is_active = 1 LIMIT 1",
        {"email": email.lower()},
    )
    return rows[0] if rows else None


def get_user_by_id(user_id: UUID) -> dict | None:
    rows = query(
        "SELECT * FROM users FINAL WHERE user_id = {user_id:UUID} AND is_active = 1 LIMIT 1",
        {"user_id": str(user_id)},
    )
    return rows[0] if rows else None


def create_user(email: str, hashed_password: str, display_name: str, role: UserRole) -> UserPublic:
    user_id = uuid4()
    created_at = datetime.now(timezone.utc)
    insert_rows(
        "users",
        _COLUMNS,
        [[
            str(user_id), email.lower(), hashed_password, display_name, role.value,
            1, created_at, None, _next_version(),
        ]],
    )
    return UserPublic(
        user_id=user_id, email=email.lower(), display_name=display_name,
        role=role, created_at=created_at,
    )


def record_login(existing_user_row: dict) -> None:
    """Re-insert `existing_user_row` (as returned by get_user_by_email/id)
    with last_login_at bumped to now and a fresh version -- created_at,
    role, password hash, etc. all carry forward unchanged."""
    insert_rows(
        "users",
        _COLUMNS,
        [[
            str(existing_user_row["user_id"]), existing_user_row["email"],
            existing_user_row["hashed_password"], existing_user_row["display_name"],
            existing_user_row["role"], existing_user_row["is_active"],
            existing_user_row["created_at"], datetime.now(timezone.utc), _next_version(),
        ]],
    )
