import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCENARIO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCENARIO_DIR))
import verify_fixture  # noqa: E402


IMAGE = "image-registry.openshift-image-registry.svc:5000/data-processing/report-generator@sha256:" + "a" * 64
OTHER_IMAGE = "image-registry.openshift-image-registry.svc:5000/data-processing/report-generator@sha256:" + "b" * 64


def deployment_fixture():
    return {
        "metadata": {"uid": "deployment-1"},
        "spec": {
            "replicas": 2,
            "template": {
                "spec": {"containers": [{"name": "app", "image": IMAGE}]}
            },
        },
    }


def replica_set(name, uid, image, owner_uid="deployment-1"):
    return {
        "metadata": {
            "name": name,
            "uid": uid,
            "ownerReferences": [
                {"kind": "Deployment", "name": "report-generator", "uid": owner_uid}
            ],
        },
        "spec": {
            "template": {
                "spec": {"containers": [{"name": "app", "image": image}]}
            }
        },
    }


def pod(name, uid, replica_set_uid="rs-current", image=IMAGE, restart_count=0, reason=None):
    terminated = {"reason": reason} if reason else {}
    return {
        "metadata": {
            "name": name,
            "uid": uid,
            "labels": {"app": "report-generator"},
            "ownerReferences": [{"kind": "ReplicaSet", "uid": replica_set_uid}],
        },
        "spec": {"containers": [{"name": "app", "image": image}]},
        "status": {
            "containerStatuses": [
                {
                    "name": "app",
                    "restartCount": restart_count,
                    "lastState": {"terminated": terminated},
                    "state": {"running": {"startedAt": "2026-01-01T00:00:00Z"}},
                }
            ]
        },
    }


def progress_samples():
    return [
        {
            "event": "worker.progress",
            "batches_completed": 10,
            "records_processed": 1000,
            "cache_entries": 1000,
            "reconciliations_completed": 10,
            "rss_bytes": 40_000_000,
        },
        {
            "event": "worker.progress",
            "batches_completed": 20,
            "records_processed": 2000,
            "cache_entries": 2000,
            "reconciliations_completed": 20,
            "rss_bytes": 80_000_000,
        },
        {
            "event": "worker.progress",
            "batches_completed": 30,
            "records_processed": 3000,
            "cache_entries": 3000,
            "reconciliations_completed": 30,
            "rss_bytes": 120_000_000,
        },
    ]


def healthy_observations(cache_entries=1500, restart_count=0, image=IMAGE, rss_growth=False):
    def progress(records, rss_bytes=50_000_000):
        return {
            "event": "worker.progress",
            "batches_completed": records // 100,
            "records_processed": records,
            "cache_entries": cache_entries,
            "reconciliations_completed": records // 100,
            "rss_bytes": rss_bytes,
        }

    return [
        {
            "desired_replicas": 2,
            "pods": [
                {
                    "name": "report-generator-a",
                    "uid": "pod-a",
                    "image": image,
                    "restart_count": restart_count,
                    "last_reason": None,
                    "started_at": "2026-01-01T00:00:00Z",
                    "state": "running",
                    "deletion_timestamp": None,
                    "progress": progress(1000),
                },
                {
                    "name": "report-generator-b",
                    "uid": "pod-b",
                    "image": image,
                    "restart_count": restart_count,
                    "last_reason": None,
                    "started_at": "2026-01-01T00:00:01Z",
                    "state": "running",
                    "deletion_timestamp": None,
                    "progress": progress(1100),
                },
            ],
        },
        {
            "desired_replicas": 2,
            "pods": [
                {
                    "name": "report-generator-a",
                    "uid": "pod-a",
                    "image": image,
                    "restart_count": restart_count,
                    "last_reason": None,
                    "started_at": "2026-01-01T00:00:00Z",
                    "state": "running",
                    "deletion_timestamp": None,
                    "progress": progress(2000, 80_000_000 if rss_growth else 50_000_000),
                },
                {
                    "name": "report-generator-b",
                    "uid": "pod-b",
                    "image": image,
                    "restart_count": restart_count,
                    "last_reason": None,
                    "started_at": "2026-01-01T00:00:01Z",
                    "state": "running",
                    "deletion_timestamp": None,
                    "progress": progress(2100, 80_000_000 if rss_growth else 50_000_000),
                },
            ],
        },
    ]


class VerifyFixtureTests(unittest.TestCase):
    def test_select_current_pods_follows_current_replicaset_and_image(self):
        deployment = deployment_fixture()
        replica_sets = [
            replica_set("report-generator-old", "rs-old", OTHER_IMAGE),
            replica_set("report-generator-current", "rs-current", IMAGE),
        ]
        pods = [
            pod("old", "pod-old", "rs-old", OTHER_IMAGE),
            pod("current", "pod-current"),
            pod("deleting", "pod-deleting"),
        ]
        pods[2]["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"

        selected = verify_fixture.select_current_pods(deployment, replica_sets, pods, IMAGE)

        self.assertEqual([item["metadata"]["name"] for item in selected], ["current"])

    def test_pod_image_extraction_uses_named_container(self):
        resource = {
            "spec": {
                "containers": [
                    {"name": "sidecar", "image": OTHER_IMAGE},
                    {"name": "app", "image": IMAGE},
                ]
            }
        }
        self.assertEqual(verify_fixture.image_for_container(resource), IMAGE)
        self.assertIsNone(
            verify_fixture.image_for_container(
                {"spec": {"containers": [{"name": "sidecar", "image": OTHER_IMAGE}]}}
            )
        )

    def test_progress_parser_ignores_non_progress_and_malformed_lines(self):
        logs = "\n".join(
            [
                "not json",
                json.dumps({"event": "report.completed"}),
                json.dumps(progress_samples()[0]),
                json.dumps({"event": "worker.progress", "rss_bytes": "not-an-int"}),
            ]
        )
        samples = verify_fixture.parse_progress_logs(logs)
        self.assertEqual(len(samples), 1)
        self.assertTrue(verify_fixture.progress_evidence_valid(progress_samples()))
        self.assertFalse(verify_fixture.progress_evidence_valid(progress_samples()[:2]))

    def test_fault_predicate_requires_stable_oom_lifetime_and_growth(self):
        before = verify_fixture.container_status(pod("p", "uid", restart_count=3, reason="OOMKilled"))
        after = verify_fixture.container_status(pod("p", "uid", restart_count=3, reason="OOMKilled"))
        self.assertTrue(verify_fixture.fault_observation_valid(before, after, progress_samples()))

        changed = verify_fixture.container_status(pod("p", "uid", restart_count=4, reason="OOMKilled"))
        self.assertFalse(verify_fixture.fault_observation_valid(before, changed, progress_samples()))
        self.assertFalse(verify_fixture.fault_observation_valid(before, after, progress_samples()[:2]))

    def test_healthy_predicate_requires_stable_bounded_processing(self):
        self.assertTrue(verify_fixture.healthy_observation_valid(healthy_observations(), IMAGE))
        self.assertFalse(
            verify_fixture.healthy_observation_valid(
                healthy_observations(cache_entries=2500), IMAGE
            )
        )
        self.assertFalse(
            verify_fixture.healthy_observation_valid(
                healthy_observations(restart_count=1), IMAGE
            )
        )
        self.assertFalse(
            verify_fixture.healthy_observation_valid(
                healthy_observations(image=OTHER_IMAGE), IMAGE
            )
        )

        residual = healthy_observations()
        residual[0]["desired_replicas"] = 0
        self.assertFalse(verify_fixture.healthy_observation_valid(residual, IMAGE))

        replaced = healthy_observations()
        replaced[1]["pods"][0]["uid"] = "pod-replaced"
        self.assertFalse(verify_fixture.healthy_observation_valid(replaced, IMAGE))

        stopped = healthy_observations()
        stopped[1]["pods"][1]["progress"] = None
        self.assertFalse(verify_fixture.healthy_observation_valid(stopped, IMAGE))

    def test_rss_warning_is_observable_without_rejecting_bounded_reference(self):
        observations = healthy_observations(rss_growth=True)
        observations.append(
            {
                "desired_replicas": 2,
                "pods": [
                    {
                        **observations[-1]["pods"][0],
                        "progress": {
                            **observations[-1]["pods"][0]["progress"],
                            "records_processed": 3000,
                            "reconciliations_completed": 30,
                            "rss_bytes": 100_000_000,
                        },
                    },
                    {
                        **observations[-1]["pods"][1],
                        "progress": {
                            **observations[-1]["pods"][1]["progress"],
                            "records_processed": 3100,
                            "reconciliations_completed": 31,
                            "rss_bytes": 100_000_000,
                        },
                    },
                ],
            }
        )
        self.assertTrue(verify_fixture.healthy_rss_growth_warning(observations))

    def test_oc_json_rejects_malformed_response(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": "not-json", "stderr": ""})()
        with patch("verify_fixture.subprocess.run", return_value=completed):
            with self.assertRaises(verify_fixture.VerificationError):
                verify_fixture.run_oc_json(["get", "pods"])


if __name__ == "__main__":
    unittest.main()
