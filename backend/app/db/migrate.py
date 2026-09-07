"""
Applies db/schema.sql against the configured ClickHouse instance.

ClickHouse's HTTP interface executes one statement per request, so this
splits the .sql file on top-level semicolons and runs each CREATE
statement through `command()`. Safe to run repeatedly: every statement is
`CREATE ... IF NOT EXISTS`.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.db.clickhouse_client import command

logger = logging.getLogger("continuity_agent.migrate")

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _split_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    for raw_statement in sql_text.split(";"):
        statement = raw_statement.strip()
        # Strip full-line comments so an all-comment fragment isn't executed.
        lines = [ln for ln in statement.splitlines() if not ln.strip().startswith("--")]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            statements.append(cleaned)
    return statements


def run_migrations() -> None:
    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    statements = _split_statements(sql_text)
    logger.info("Applying %d schema statement(s) from %s", len(statements), SCHEMA_PATH.name)
    for statement in statements:
        command(statement)
    logger.info("Schema is up to date.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migrations()
