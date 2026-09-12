#!/usr/bin/env python3
"""Read-only checks for the report-generator fixture."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

NAMESPACE = "data-processing"
DEPLOYMENT = "report-generator"
CONTAINER = "app"
EXPECTED_REPLICAS = 2
CACHE_CAPACITY = 2000
POLL_INTERVAL_SECONDS = 5.0
DEFAULT_COMMAND_TIMEOUT = 30.0


class VerificationError(RuntimeError):
    """Raised when the fixture does not provide the required evidence."""


class OcCommandError(VerificationError):
    def __init__(self, args: Sequence[str], returncode: int, stderr: str):
        self.args = tuple(args)
        self.returncode = returncode
        self.stderr = stderr
        detail = stderr.strip() or f"oc exited with status {returncode}"
        super().__init__(f"oc {' '.join(args)} failed: {detail}")


@dataclass(frozen=True)
class WorkloadSnapshot:
    deployment: Mapping[str, Any]
    pods: tuple[Mapping[str, Any], ...]


def _metadata(resource: Mapping[str, Any]) -> Mapping[str, Any]:
    return resource.get("metadata", {})


def _container_from_spec(
    spec: Mapping[str, Any], container_name: str = CONTAINER
) -> Mapping[str, Any] | None:
    for container in spec.get("containers", []):
        if container.get("name") == container_name:
            return container
    return None


def image_for_template(
    template: Mapping[str, Any], container_name: str = CONTAINER
) -> str | None:
    container = _container_from_spec(template.get("spec", {}), container_name)
    return str(container["image"]) if container and container.get("image") else None


def image_for_container(
    resource: Mapping[str, Any], container_name: str = CONTAINER
) -> str | None:
    container = _container_from_spec(resource.get("spec", {}), container_name)
    return str(container["image"]) if container and container.get("image") else None


def _has_owner(
    resource: Mapping[str, Any], kind: str, uid: str | None = None
) -> bool:
    for owner in _metadata(resource).get("ownerReferences", []):
        if owner.get("kind") == kind and (uid is None or owner.get("uid") == uid):
            return True
    return False


def select_current_pods(
    deployment: Mapping[str, Any],
    replica_sets: Iterable[Mapping[str, Any]],
    pods: Iterable[Mapping[str, Any]],
    expected_image: str,
    container_name: str = CONTAINER,
) -> tuple[Mapping[str, Any], ...]:
    """Select non-deleting pods owned by the deployment's current image."""
    deployment_uid = _metadata(deployment).get("uid")
    current_replica_set_uids = set()
    for replica_set in replica_sets:
        if not _has_owner(replica_set, "Deployment", deployment_uid):
            continue
        if (
            image_for_template(
                replica_set.get("spec", {}).get("template", {}), container_name
            )
            != expected_image
        ):
            continue
        replica_set_uid = _metadata(replica_set).get("uid")
        if replica_set_uid:
            current_replica_set_uids.add(replica_set_uid)

    selected = []
    for pod in pods:
        metadata = _metadata(pod)
        if metadata.get("deletionTimestamp"):
            continue
        if metadata.get("labels", {}).get("app") != "report-generator":
            continue
        if not any(
            owner.get("kind") == "ReplicaSet"
            and owner.get("uid") in current_replica_set_uids
            for owner in metadata.get("ownerReferences", [])
        ):
            continue
        if image_for_container(pod, container_name) != expected_image:
            continue
        selected.append(pod)
    return tuple(sorted(selected, key=lambda pod: _metadata(pod).get("name", "")))


def container_status(
    pod: Mapping[str, Any], container_name: str = CONTAINER
) -> Mapping[str, Any] | None:
    for status in pod.get("status", {}).get("containerStatuses", []):
        if status.get("name") != container_name:
            continue
        state = status.get("state", {})
        last_state = status.get("lastState", {})
        terminated = last_state.get("terminated", {})
        if "running" in state:
            state_name = "running"
        elif "waiting" in state:
            state_name = "waiting"
        elif "terminated" in state:
            state_name = "terminated"
        else:
            state_name = "unknown"
        return {
            "pod_uid": _metadata(pod).get("uid"),
            "restart_count": int(status.get("restartCount", 0)),
            "last_reason": terminated.get("reason"),
            "last_exit_code": terminated.get("exitCode"),
            "started_at": state.get("running", {}).get("startedAt"),
            "state": state_name,
        }
    return None


def parse_progress_logs(logs: str) -> list[Mapping[str, Any]]:
    samples = []
    required = (
        "batches_completed",
        "records_processed",
        "cache_entries",
        "reconciliations_completed",
        "rss_bytes",
    )
    for line in logs.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("event") != "worker.progress":
            continue
        if not all(type(entry.get(field)) is int for field in required):
            continue
        samples.append(entry)
    return samples


def progress_evidence_valid(
    samples: Sequence[Mapping[str, Any]], minimum_samples: int = 3
) -> bool:
    if len(samples) < minimum_samples:
        return False
    first = samples[0]
    last = samples[-1]
    counters = ("batches_completed", "records_processed", "reconciliations_completed")
    if not all(last[field] > first[field] for field in counters):
        return False
    if last["cache_entries"] <= first["cache_entries"]:
        return False
    if last["rss_bytes"] <= first["rss_bytes"]:
        return False
    return True


def fault_observation_valid(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    samples: Sequence[Mapping[str, Any]],
) -> bool:
    identity_fields = ("pod_uid", "started_at", "restart_count")
    return (
        all(before.get(field) == after.get(field) for field in identity_fields)
        and after.get("restart_count", 0) >= 3
        and after.get("last_reason") == "OOMKilled"
        and progress_evidence_valid(samples)
    )


def _pod_identity(pod: Mapping[str, Any]) -> tuple[Any, ...]:
    return (pod.get("name"), pod.get("uid"), pod.get("started_at"))


def _valid_healthy_pod(pod: Mapping[str, Any], expected_image: str) -> bool:
    progress = pod.get("progress")
    return (
        bool(pod.get("name"))
        and bool(pod.get("uid"))
        and pod.get("image") == expected_image
        and not pod.get("deletion_timestamp")
        and pod.get("state") == "running"
        and pod.get("restart_count") == 0
        and pod.get("last_reason") is None
        and isinstance(progress, Mapping)
        and type(progress.get("records_processed")) is int
        and type(progress.get("reconciliations_completed")) is int
        and type(progress.get("cache_entries")) is int
        and type(progress.get("rss_bytes")) is int
    )


def healthy_observation_valid(
    observations: Sequence[Mapping[str, Any]],
    expected_image: str,
    cache_capacity: int = CACHE_CAPACITY,
) -> bool:
    if not observations:
        return False

    first = observations[0]
    if first.get("desired_replicas") != EXPECTED_REPLICAS:
        return False
    first_pods = {pod.get("name"): pod for pod in first.get("pods", [])}
    if len(first_pods) != EXPECTED_REPLICAS or None in first_pods:
        return False
    if not all(_valid_healthy_pod(pod, expected_image) for pod in first_pods.values()):
        return False

    for observation in observations:
        if observation.get("desired_replicas") != EXPECTED_REPLICAS:
            return False
        pods = {pod.get("name"): pod for pod in observation.get("pods", [])}
        if set(pods) != set(first_pods):
            return False
        for name, pod in pods.items():
            initial = first_pods[name]
            if not _valid_healthy_pod(pod, expected_image):
                return False
            if _pod_identity(pod) != _pod_identity(initial):
                return False
            if pod["progress"]["cache_entries"] > cache_capacity:
                return False

    for name, initial in first_pods.items():
        final = {pod["name"]: pod for pod in observations[-1]["pods"]}[name]
        initial_progress = initial["progress"]
        final_progress = final["progress"]
        if final_progress["records_processed"] <= initial_progress["records_processed"]:
            return False
        if final_progress["reconciliations_completed"] <= initial_progress[
            "reconciliations_completed"
        ]:
            return False
    return True


def healthy_rss_growth_warning(observations: Sequence[Mapping[str, Any]]) -> bool:
    if len(observations) < 3:
        return False
    names = [pod.get("name") for pod in observations[0].get("pods", [])]
    for name in names:
        values = []
        for observation in observations:
            pod = next(
                (item for item in observation.get("pods", []) if item.get("name") == name),
                None,
            )
            if not pod or not pod.get("progress"):
                break
            values.append(pod["progress"].get("rss_bytes"))
        if (
            len(values) == len(observations)
            and all(type(value) is int for value in values)
            and values[-1] > values[0]
            and all(left <= right for left, right in zip(values, values[1:]))
        ):
            return True
    return False


def healthy_startup_ready(observation: Mapping[str, Any]) -> bool:
    if observation.get("desired_replicas") != EXPECTED_REPLICAS:
        return False
    pods = observation.get("pods", [])
    if len(pods) != EXPECTED_REPLICAS:
        return False
    return all(
        _valid_healthy_pod(pod, observation.get("image", ""))
        and pod["progress"]["cache_entries"] >= CACHE_CAPACITY
        and pod["progress"]["records_processed"] > 0
        and pod["progress"]["reconciliations_completed"] > 0
        for pod in pods
    )


def run_oc(args: Sequence[str], timeout: float = DEFAULT_COMMAND_TIMEOUT) -> str:
    if not math.isfinite(timeout) or timeout <= 0:
        raise VerificationError("oc command timeout must be positive and finite")
    completed = subprocess.run(
        ["oc", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise OcCommandError(args, completed.returncode, completed.stderr)
    return completed.stdout


def run_oc_json(
    args: Sequence[str], timeout: float = DEFAULT_COMMAND_TIMEOUT
) -> Mapping[str, Any]:
    output = run_oc(args, timeout)
    try:
        value = json.loads(output)
    except json.JSONDecodeError as error:
        raise VerificationError(f"oc returned malformed JSON for {' '.join(args)}") from error
    if not isinstance(value, dict):
        raise VerificationError(f"oc returned a non-object for {' '.join(args)}")
    return value


def read_workload(
    expected_image: str, command_timeout: float = DEFAULT_COMMAND_TIMEOUT
) -> WorkloadSnapshot:
    deployment = run_oc_json(
        ["get", "deployment", DEPLOYMENT, "-n", NAMESPACE, "-o", "json"],
        command_timeout,
    )
    configured_image = image_for_template(
        deployment.get("spec", {}).get("template", {})
    )
    if configured_image != expected_image:
        raise VerificationError(
            "deployment template does not use the expected image digest"
        )
    replica_sets = run_oc_json(
        [
            "get",
            "replicasets",
            "-n",
            NAMESPACE,
            "-l",
            "app=report-generator",
            "-o",
            "json",
        ],
        command_timeout,
    ).get("items", [])
    pods = run_oc_json(
        [
            "get",
            "pods",
            "-n",
            NAMESPACE,
            "-l",
            "app=report-generator",
            "-o",
            "json",
        ],
        command_timeout,
    ).get("items", [])
    current_pods = select_current_pods(
        deployment, replica_sets, pods, expected_image
    )
    return WorkloadSnapshot(deployment=deployment, pods=current_pods)


def _desired_replicas(snapshot: WorkloadSnapshot) -> int:
    try:
        return int(snapshot.deployment.get("spec", {}).get("replicas", 0))
    except (TypeError, ValueError) as error:
        raise VerificationError("deployment has an invalid replica count") from error


def _pod_name(pod: Mapping[str, Any]) -> str:
    name = _metadata(pod).get("name")
    if not name:
        raise VerificationError("selected pod has no name")
    return str(name)


def _pod_by_name(snapshot: WorkloadSnapshot, name: str) -> Mapping[str, Any] | None:
    return next(
        (pod for pod in snapshot.pods if _metadata(pod).get("name") == name),
        None,
    )


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise VerificationError("fixture verification deadline expired")
    return min(DEFAULT_COMMAND_TIMEOUT, remaining)


def _latest_progress(logs: str) -> Mapping[str, Any] | None:
    samples = parse_progress_logs(logs)
    return samples[-1] if samples else None


def _healthy_observation(
    snapshot: WorkloadSnapshot,
    expected_image: str,
    deadline: float,
    baseline: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    if _desired_replicas(snapshot) != EXPECTED_REPLICAS:
        raise VerificationError("deployment must desire exactly two replicas")
    if len(snapshot.pods) != EXPECTED_REPLICAS:
        return None

    before_status = {}
    logs_by_name = {}
    for pod in snapshot.pods:
        name = _pod_name(pod)
        status = container_status(pod)
        if not status:
            raise VerificationError(f"container status is unavailable for pod {name}")
        if status["restart_count"] != 0 or status["last_reason"] is not None:
            raise VerificationError(f"reference pod {name} restarted during observation")
        before_status[name] = status
        logs_by_name[name] = run_oc(
            [
                "logs",
                f"pod/{name}",
                "-n",
                NAMESPACE,
                "-c",
                CONTAINER,
                "--tail=5000",
            ],
            _remaining(deadline),
        )

    after_snapshot = read_workload(expected_image, _remaining(deadline))
    if _desired_replicas(after_snapshot) != EXPECTED_REPLICAS:
        raise VerificationError("deployment replica target changed during observation")
    if len(after_snapshot.pods) != EXPECTED_REPLICAS:
        return None

    observations = []
    for pod in after_snapshot.pods:
        name = _pod_name(pod)
        status = container_status(pod)
        if not status:
            raise VerificationError(f"container status is unavailable for pod {name}")
        if before_status.get(name) != status:
            return None
        if baseline is not None:
            baseline_pod = next(
                item
                for item in baseline["pods"]
                if item["name"] == name
            )
            if (
                status["pod_uid"] != baseline_pod["uid"]
                or status["started_at"] != baseline_pod["started_at"]
            ):
                raise VerificationError(f"reference pod {name} was replaced")
        observations.append(
            {
                "name": name,
                "uid": status["pod_uid"],
                "image": image_for_container(pod),
                "restart_count": status["restart_count"],
                "last_reason": status["last_reason"],
                "started_at": status["started_at"],
                "state": status["state"],
                "deletion_timestamp": _metadata(pod).get("deletionTimestamp"),
                "progress": _latest_progress(logs_by_name[name]),
            }
        )

    return {
        "image": expected_image,
        "desired_replicas": EXPECTED_REPLICAS,
        "pods": sorted(observations, key=lambda item: item["name"]),
    }


def wait_for_startup(expected_image: str, deadline: float) -> Mapping[str, Any]:
    while time.monotonic() < deadline:
        snapshot = read_workload(expected_image, _remaining(deadline))
        observation = _healthy_observation(snapshot, expected_image, deadline)
        if observation and healthy_startup_ready(observation):
            return observation
        time.sleep(min(POLL_INTERVAL_SECONDS, _remaining(deadline)))
    raise VerificationError("healthy processing evidence did not appear before the deadline")


def _fault_observation(
    snapshot: WorkloadSnapshot, expected_image: str, deadline: float
) -> bool:
    for pod in snapshot.pods:
        before = container_status(pod)
        if not before or before["restart_count"] < 3 or before["last_reason"] != "OOMKilled":
            continue
        name = _pod_name(pod)
        try:
            logs = run_oc(
                [
                    "logs",
                    f"pod/{name}",
                    "-n",
                    NAMESPACE,
                    "-c",
                    CONTAINER,
                    "--previous",
                    "--tail=5000",
                ],
                _remaining(deadline),
            )
        except OcCommandError as error:
            if "not found" in error.stderr.lower() or "previous terminated" in error.stderr.lower():
                continue
            raise
        after_snapshot = read_workload(expected_image, _remaining(deadline))
        after_pod = _pod_by_name(after_snapshot, name)
        if after_pod is None:
            continue
        after = container_status(after_pod)
        if after and fault_observation_valid(before, after, parse_progress_logs(logs)):
            return True
    return False


def wait_for_fault(expected_image: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = read_workload(expected_image, _remaining(deadline))
        if _desired_replicas(snapshot) != EXPECTED_REPLICAS:
            raise VerificationError("fault fixture must retain a two-replica Deployment")
        if len(snapshot.pods) == EXPECTED_REPLICAS and _fault_observation(
            snapshot, expected_image, deadline
        ):
            print("Fault evidence verified: current pods show OOMKilled restarts and growth samples.")
            return
        time.sleep(min(POLL_INTERVAL_SECONDS, _remaining(deadline)))
    raise VerificationError("fault evidence was not complete before the deadline")


def wait_for_healthy(expected_image: str, duration: float, timeout: float) -> None:
    overall_deadline = time.monotonic() + timeout
    startup_observation = wait_for_startup(expected_image, overall_deadline)
    stability_deadline = time.monotonic() + duration
    if stability_deadline > overall_deadline:
        raise VerificationError(
            "insufficient time remains for the complete healthy observation window"
        )

    observations = [startup_observation]
    while time.monotonic() < stability_deadline:
        snapshot = read_workload(expected_image, _remaining(stability_deadline))
        observation = _healthy_observation(
            snapshot, expected_image, stability_deadline, startup_observation
        )
        if observation is None:
            raise VerificationError("healthy observation crossed a process lifetime boundary")
        if not all(pod.get("progress") for pod in observation["pods"]):
            raise VerificationError("healthy pods stopped emitting progress evidence")
        observations.append(observation)
        remaining = stability_deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(POLL_INTERVAL_SECONDS, remaining))

    if not healthy_observation_valid(observations, expected_image):
        raise VerificationError("healthy observation did not show stable bounded processing")
    if healthy_rss_growth_warning(observations):
        print("WARNING: healthy RSS samples show sustained growth; operator review is required.")
    print("Healthy evidence verified: both pods processed and reconciled records without restarts.")


def _positive_number(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{name} must be positive and finite") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(f"{name} must be positive and finite")
    return parsed


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    fault = subparsers.add_parser("fault")
    fault.add_argument("--image", required=True)
    fault.add_argument(
        "--timeout", type=lambda value: _positive_number(value, "timeout"), default=900
    )

    healthy = subparsers.add_parser("healthy")
    healthy.add_argument("--image", required=True)
    healthy.add_argument(
        "--duration", type=lambda value: _positive_number(value, "duration"), default=30
    )
    healthy.add_argument(
        "--timeout", type=lambda value: _positive_number(value, "timeout"), default=180
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.mode == "fault":
            wait_for_fault(args.image, args.timeout)
        else:
            wait_for_healthy(args.image, args.duration, args.timeout)
    except (OcCommandError, VerificationError, subprocess.TimeoutExpired) as error:
        print(f"Fixture verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
