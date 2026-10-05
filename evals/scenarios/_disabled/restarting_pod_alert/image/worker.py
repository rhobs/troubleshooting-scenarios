from __future__ import annotations

import json
import math
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Iterable, Mapping

from report_cache import ReportCache

APP_VERSION = os.environ.get("APP_VERSION", "unknown")
CACHE_CAPACITY = 2000
PROGRESS_INTERVAL_SECONDS = 5.0


def make_record(sequence: int) -> dict[str, Any]:
    if sequence < 1:
        raise ValueError("sequence must be positive")

    currencies = ("USD", "EUR", "GBP")
    item_count = 8 + (sequence % 17)
    line_items = []
    for offset in range(item_count):
        line_items.append(
            {
                "sku": f"SKU-{(sequence * 13 + offset * 7) % 10000:04d}",
                "quantity": 1 + ((sequence + offset) % 4),
                "unit_price_cents": 125 + ((sequence * 31 + offset * 17) % 5000),
            }
        )

    return {
        "record_id": f"report-{sequence:010d}",
        "account_id": f"account-{(sequence % 1000) + 1:04d}",
        "currency": currencies[sequence % len(currencies)],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "line_items": line_items,
    }


def calculate_total(record: Mapping[str, Any]) -> int:
    return sum(
        int(item["quantity"]) * int(item["unit_price_cents"])
        for item in record["line_items"]
    )


def _report_for(record: Mapping[str, Any]) -> dict[str, Any]:
    line_items = [dict(item) for item in record["line_items"]]
    return {
        "record_id": record["record_id"],
        "account_id": record["account_id"],
        "currency": record["currency"],
        "created_at": record["created_at"],
        "line_item_count": len(line_items),
        "line_items": line_items,
        "total_cents": calculate_total(record),
    }


def process_batch(
    records: Iterable[Mapping[str, Any]], cache: ReportCache
) -> dict[str, int]:
    record_count = 0
    total_cents = 0
    for record in records:
        report = _report_for(record)
        cache.put(str(report["record_id"]), report)
        record_count += 1
        total_cents += int(report["total_cents"])
    return {"record_count": record_count, "total_cents": total_cents}


def _sequence_from_record_id(record_id: str) -> int:
    prefix, separator, value = record_id.partition("-")
    if prefix != "report" or not separator or not value.isdigit():
        raise ValueError(f"invalid record id: {record_id}")
    sequence = int(value)
    if sequence < 1:
        raise ValueError(f"invalid record id: {record_id}")
    return sequence


def _reports_match(cached: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(
        cached.get(field) == expected.get(field)
        for field in (
            "record_id",
            "account_id",
            "currency",
            "line_item_count",
            "line_items",
            "total_cents",
        )
    )


def reconcile_recent(
    cache: ReportCache, record_ids: Iterable[str]
) -> dict[str, int]:
    completed = 0
    cache_hits = 0
    cache_misses = 0
    cache_mismatches = 0
    recomputed_reports = 0
    reconciled_total_cents = 0
    for record_id in record_ids:
        sequence = _sequence_from_record_id(record_id)
        expected = _report_for(make_record(sequence))
        cached = cache.get(record_id)
        if cached is None:
            cache_misses += 1
            recomputed_reports += 1
            cache.put(record_id, expected)
            reconciled_total_cents += int(expected["total_cents"])
        elif _reports_match(cached, expected):
            cache_hits += 1
            reconciled_total_cents += int(cached["total_cents"])
        else:
            cache_mismatches += 1
            recomputed_reports += 1
            cache.put(record_id, expected)
            reconciled_total_cents += int(expected["total_cents"])
        completed += 1
    return {
        "completed": completed,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_mismatches": cache_mismatches,
        "recomputed_reports": recomputed_reports,
        "reconciled_total_cents": reconciled_total_cents,
    }


def current_rss_bytes() -> int:
    fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
    resident_pages = int(fields[1])
    return resident_pages * os.sysconf("SC_PAGE_SIZE")


def emit(event: str, **fields: Any) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": "INFO",
        "component": "report-generator",
        "event": event,
        **fields,
    }
    print(json.dumps(entry, separators=(",", ":")), flush=True)


def _positive_int(name: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _positive_float(name: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive finite number") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return parsed


def _recent_record_ids(
    first_sequence: int, batch_size: int
) -> tuple[str, ...]:
    distances = (batch_size, batch_size * 5, batch_size * 10, batch_size * 20)
    sequence_ids = {
        first_sequence - distance + batch_size // 2 for distance in distances
    }
    return tuple(
        f"report-{sequence:010d}"
        for sequence in sorted(sequence_ids)
        if sequence > 0
    )


def main() -> None:
    batch_size = _positive_int("BATCH_SIZE", os.environ.get("BATCH_SIZE", "100"))
    batch_interval = _positive_float(
        "BATCH_INTERVAL_SECONDS",
        os.environ.get("BATCH_INTERVAL_SECONDS", "0.25"),
    )
    cache = ReportCache(max_entries=CACHE_CAPACITY)
    stop_event = Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    emit(
        "worker.started",
        release=APP_VERSION,
        batch_size=batch_size,
        batch_interval_seconds=batch_interval,
        cache_capacity=CACHE_CAPACITY,
    )

    sequence = 1
    batch_number = 0
    records_processed = 0
    reconciliations_completed = 0
    cache_hits = 0
    cache_misses = 0
    cache_mismatches = 0
    recomputed_reports = 0
    reconciled_total_cents = 0
    next_progress = time.monotonic() + PROGRESS_INTERVAL_SECONDS

    while not stop_event.is_set():
        first_sequence = sequence
        records = [make_record(sequence + offset) for offset in range(batch_size)]
        sequence += batch_size
        summary = process_batch(records, cache)
        batch_number += 1
        records_processed += summary["record_count"]
        reconciliation = reconcile_recent(
            cache,
            _recent_record_ids(first_sequence, batch_size),
        )
        reconciliations_completed += reconciliation["completed"]
        cache_hits += reconciliation["cache_hits"]
        cache_misses += reconciliation["cache_misses"]
        cache_mismatches += reconciliation["cache_mismatches"]
        recomputed_reports += reconciliation["recomputed_reports"]
        reconciled_total_cents += reconciliation["reconciled_total_cents"]

        emit(
            "report.completed",
            batch_number=batch_number,
            record_count=summary["record_count"],
            computed_total_cents=summary["total_cents"],
        )

        now = time.monotonic()
        if now >= next_progress:
            emit(
                "worker.progress",
                release=APP_VERSION,
                batches_completed=batch_number,
                records_processed=records_processed,
                cache_entries=len(cache),
                reconciliations_completed=reconciliations_completed,
                cache_hits=cache_hits,
                cache_misses=cache_misses,
                cache_mismatches=cache_mismatches,
                recomputed_reports=recomputed_reports,
                reconciled_total_cents=reconciled_total_cents,
                rss_bytes=current_rss_bytes(),
            )
            next_progress = now + PROGRESS_INTERVAL_SECONDS

        stop_event.wait(batch_interval)

    emit(
        "worker.stopped",
        release=APP_VERSION,
        batches_completed=batch_number,
        records_processed=records_processed,
        cache_entries=len(cache),
        reconciliations_completed=reconciliations_completed,
    )


if __name__ == "__main__":
    main()
