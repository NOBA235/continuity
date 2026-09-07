"""
Thin, typed wrapper around clickhouse-connect.

This is the single place that talks to ClickHouse over the native HTTP
interface. Every other module goes through `get_clickhouse_client()` so
connection handling (pooling, retries, secure/plaintext) lives in one spot.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Iterable, Sequence

import clickhouse_connect
from clickhouse_connect.driver.client import Client
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings

logger = logging.getLogger("continuity_agent.clickhouse")


@lru_cache
def get_clickhouse_client() -> Client:
    """
    Build (once per process) a live ClickHouse client from Settings.

    Uses clickhouse-connect's HTTP(S) interface, which is what ClickHouse
    Cloud and self-hosted deployments both expose on port 8443/8123.
    """
    settings = get_settings()
    client = clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
        secure=settings.clickhouse_secure,
        settings={"async_insert": 1, "wait_for_async_insert": 1},
    )
    client.ping()
    logger.info(
        "Connected to ClickHouse at %s:%s/%s",
        settings.clickhouse_host,
        settings.clickhouse_port,
        settings.clickhouse_database,
    )
    return client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def insert_rows(table: str, column_names: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    """
    Batch-insert rows into `table`. Retries transient network failures with
    exponential backoff -- ClickHouse Cloud instances can briefly reject
    connections during autoscaling events.
    """
    rows = list(rows)
    if not rows:
        return 0
    client = get_clickhouse_client()
    client.insert(table, rows, column_names=list(column_names))
    logger.debug("Inserted %d row(s) into %s", len(rows), table)
    return len(rows)


def query(sql: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a parameterized SELECT and return rows as a list of dicts."""
    client = get_clickhouse_client()
    result = client.query(sql, parameters=parameters or {})
    columns = result.column_names
    return [dict(zip(columns, row)) for row in result.result_rows]


def command(sql: str, parameters: dict[str, Any] | None = None) -> Any:
    """Run DDL or other non-SELECT statements (CREATE TABLE, ALTER, ...)."""
    client = get_clickhouse_client()
    return client.command(sql, parameters=parameters or {})
