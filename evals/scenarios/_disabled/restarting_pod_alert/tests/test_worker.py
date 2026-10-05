import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCENARIO_DIR = Path(__file__).resolve().parents[1]
IMAGE_DIR = SCENARIO_DIR / "image"


def load_worker(version: str):
    cache_name = f"report_cache_{version.replace('.', '_')}"
    worker_name = f"worker_{version.replace('.', '_')}"
    cache_spec = importlib.util.spec_from_file_location(
        "report_cache", IMAGE_DIR / "releases" / version / "report_cache.py"
    )
    cache_module = importlib.util.module_from_spec(cache_spec)
    sys.modules["report_cache"] = cache_module
    cache_spec.loader.exec_module(cache_module)
    sys.modules.pop(cache_name, None)

    worker_spec = importlib.util.spec_from_file_location(
        worker_name, IMAGE_DIR / "worker.py"
    )
    worker_module = importlib.util.module_from_spec(worker_spec)
    sys.modules[worker_name] = worker_module
    worker_spec.loader.exec_module(worker_module)
    return worker_module, cache_module


class WorkerTests(unittest.TestCase):
    def test_record_contains_useful_business_fields(self):
        worker, _ = load_worker("1.0.1")
        record = worker.make_record(42)

        self.assertEqual(record["record_id"], "report-0000000042")
        self.assertTrue(record["account_id"].startswith("account-"))
        self.assertIn(record["currency"], {"USD", "EUR", "GBP"})
        self.assertGreaterEqual(len(record["line_items"]), 8)
        self.assertLessEqual(len(record["line_items"]), 24)
        self.assertGreater(record["line_items"][0]["quantity"], 0)
        self.assertGreater(record["line_items"][0]["unit_price_cents"], 0)
        self.assertEqual(
            record["line_items"][0]["quantity"]
            * record["line_items"][0]["unit_price_cents"],
            worker.calculate_total(record)
            - sum(
                item["quantity"] * item["unit_price_cents"]
                for item in record["line_items"][1:]
            ),
        )

    def test_releases_compute_equivalent_totals(self):
        worker_healthy, _ = load_worker("1.0.1")
        record_healthy = worker_healthy.make_record(73)
        worker_affected, _ = load_worker("1.0.2")
        record_affected = worker_affected.make_record(73)

        self.assertEqual(
            worker_healthy.calculate_total(record_healthy),
            worker_affected.calculate_total(record_affected),
        )
        self.assertEqual(
            [item["sku"] for item in record_healthy["line_items"]],
            [item["sku"] for item in record_affected["line_items"]],
        )

    def test_cache_release_difference_is_limited_to_retention(self):
        worker_healthy, healthy_cache_module = load_worker("1.0.1")
        worker_affected, affected_cache_module = load_worker("1.0.2")
        healthy_cache = healthy_cache_module.ReportCache(max_entries=2)
        affected_cache = affected_cache_module.ReportCache(max_entries=2)

        for key in ("a", "b", "c"):
            record = worker_healthy.make_record(ord(key) - 96)
            healthy_cache.put(key, record)
            affected_cache.put(key, record)

        self.assertEqual(len(healthy_cache), 2)
        self.assertIsNone(healthy_cache.get("a"))
        self.assertEqual(len(affected_cache), 3)
        self.assertIsNotNone(affected_cache.get("a"))

        affected_cache.put("b", {"updated": True})
        self.assertEqual(len(affected_cache), 3)
        self.assertEqual(affected_cache.get("b"), {"updated": True})

    def test_processing_and_reconciliation_use_the_cache(self):
        worker, cache_module = load_worker("1.0.1")
        cache = cache_module.ReportCache(max_entries=20)
        records = [worker.make_record(sequence) for sequence in range(1, 4)]

        summary = worker.process_batch(records, cache)
        reconciliation = worker.reconcile_recent(
            cache,
            (
                "report-0000000001",
                "report-0000000002",
                "report-0000000999",
            ),
        )

        self.assertEqual(summary["record_count"], 3)
        self.assertGreater(summary["total_cents"], 0)
        self.assertEqual(len(cache), 4)
        self.assertEqual(reconciliation["completed"], 3)
        self.assertEqual(reconciliation["cache_hits"], 2)
        self.assertEqual(reconciliation["cache_misses"], 1)
        self.assertEqual(reconciliation["cache_mismatches"], 0)
        self.assertEqual(reconciliation["recomputed_reports"], 1)
        self.assertGreater(reconciliation["reconciled_total_cents"], 0)

        cache.put("report-0000000001", {"record_id": "report-0000000001"})
        repaired = worker.reconcile_recent(cache, ("report-0000000001",))
        self.assertEqual(repaired["cache_mismatches"], 1)
        self.assertEqual(repaired["recomputed_reports"], 1)
        self.assertEqual(
            cache.get("report-0000000001")["total_cents"],
            worker.calculate_total(worker.make_record(1)),
        )

    def test_progress_is_flushed_jsonl_with_rss(self):
        worker, _ = load_worker("1.0.1")
        output = io.StringIO()
        with redirect_stdout(output):
            worker.emit("worker.progress", records_processed=100, rss_bytes=1234)

        entry = json.loads(output.getvalue())
        self.assertEqual(entry["event"], "worker.progress")
        self.assertEqual(entry["records_processed"], 100)
        self.assertEqual(entry["rss_bytes"], 1234)
        self.assertEqual(entry["component"], "report-generator")
        self.assertGreater(worker.current_rss_bytes(), 0)

    def test_invalid_runtime_settings_are_rejected(self):
        worker, _ = load_worker("1.0.1")
        with self.assertRaises(ValueError):
            worker._positive_int("BATCH_SIZE", "0")
        with self.assertRaises(ValueError):
            worker._positive_float("BATCH_INTERVAL_SECONDS", "nan")
        with self.assertRaises(ValueError):
            worker._sequence_from_record_id("not-a-report")


if __name__ == "__main__":
    unittest.main()
