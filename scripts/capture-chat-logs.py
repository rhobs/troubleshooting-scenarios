#!/usr/bin/env python3
"""Download Chat app-server logs at evaluation checkpoints."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from report_progress import write_atomic


NAMESPACE = "openshift-lightspeed"
CONTAINER = "lightspeed-service-api"
SELECTOR = "app.kubernetes.io/name=lightspeed-service-api"
STATE_FILE = ".chat-log-state.json"


def timestamp_ns(value):
    """Compare Kubernetes timestamps without losing nanoseconds."""
    match = re.fullmatch(r"(.{19})(?:\.(\d{1,9}))?Z", value)
    if match is None:
        raise ValueError("Invalid Kubernetes log timestamp")
    seconds = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return int(seconds.timestamp()) * 1_000_000_000 + int((match[2] or "0").ljust(9, "0"))


def safe_name(value):
    """Keep log paths inside the session directory."""
    if value in ("", ".", ".."):
        raise ValueError("Invalid log path component")
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)


def log_targets(scenario, agents, repeat, agent=None, run_index=None):
    """Name one file for each selected scenario, agent, and repeat."""
    parts = scenario.removeprefix("scenarios/").split("/")
    directory = Path("logs", *(safe_name(part) for part in parts))
    selected_agents = [agent] if agent else agents
    indices = [run_index] if run_index else range(1, repeat + 1)
    targets = []
    for name in selected_agents:
        for index in indices:
            targets.append({
                "path": str(directory / f"{safe_name(name)}-run_{index}.log"),
                "label": f"scenario={scenario} agent={name} repeat={index}",
            })
    if not targets:
        raise ValueError("No agents selected for log capture")
    shared = len(targets) > 1
    for target in targets:
        target["shared"] = shared
    return targets


def read_pods():
    result = subprocess.run(
        ["oc", "get", "pods", "-n", NAMESPACE, "-l", SELECTOR, "-o", "json",
         "--request-timeout=10s"],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    pods = json.loads(result.stdout)["items"]
    if not pods:
        raise ValueError("No Lightspeed app-server pods found")
    return pods


def new_records(output, cursor, pod_name, restart):
    """Keep new lines, including repeated lines at the same timestamp."""
    records = []
    boundary = cursor["ns"]
    seen = Counter()
    updated = dict(cursor)
    for line in output.split("\n"):
        if not line:
            continue
        timestamp, separator, message = line.partition(" ")
        if not separator:
            raise ValueError("Log output has no timestamp")
        current = timestamp_ns(timestamp)
        if current < boundary:
            continue
        digest = hashlib.sha256(message.encode()).hexdigest()
        if current == boundary:
            seen[digest] += 1
            if seen[digest] <= cursor["seen"].get(digest, 0):
                continue
        if current > updated["ns"]:
            updated = {"ns": current, "time": timestamp, "seen": {}}
        updated["seen"] = dict(updated["seen"])
        updated["seen"][digest] = updated["seen"].get(digest, 0) + 1
        records.append((current, f"{timestamp} [pod={pod_name} container={CONTAINER} "
                        f"restart={restart}] {message}\n"))
    return records, updated


def append_records(directory, targets, records, checkpoint):
    for target in targets:
        path = directory / target["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        exists = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8") as output:
            if not exists:
                output.write(f"# Lightspeed app-server logs: {target['label']}\n")
                if target.get("shared"):
                    output.write("# Shared scenario window: includes all selected agents and repeats.\n")
            if records:
                output.write(f"# Checkpoint: {checkpoint}\n")
                for _, line in sorted(records, key=lambda record: record[0]):
                    output.write(line)


def capture(directory, state, checkpoint):
    """Collect current and previous container instances without following logs."""
    targets = state.get("active") or [{
        "path": "logs/lightspeed-app-server-setup.log", "label": "session setup and cleanup",
    }]
    records = []
    failed = False
    cursors = dict(state.get("cursors", {}))
    restarts = dict(state.get("restarts", {}))
    try:
        pods = read_pods()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        print(f"WARNING: Cannot list app-server pods: {detail}", file=sys.stderr)
        return False
    for pod in pods:
        name = pod["metadata"]["name"]
        uid = pod["metadata"]["uid"]
        statuses = pod.get("status", {}).get("containerStatuses", [])
        status = next((item for item in statuses if item["name"] == CONTAINER), None)
        if status is None:
            print(f"WARNING: App-server container status unavailable: {name}", file=sys.stderr)
            failed = True
            continue
        count = status.get("restartCount", 0)
        if uid in restarts and count > restarts[uid] + 1:
            print(f"WARNING: {name} restarted {count - restarts[uid]} times between captures; "
                  "older container logs may be lost.", file=sys.stderr)
            failed = True
        restarts[uid] = count
        instances = [(count - 1, True), (count, False)] if count else [(count, False)]
        for restart, previous in instances:
            key = f"{uid}/{restart}"
            cursor = cursors.get(key, {
                "time": state["since"], "ns": timestamp_ns(state["since"]), "seen": {},
            })
            command = ["oc", "logs", "-n", NAMESPACE, name, "-c", CONTAINER,
                       "--timestamps=true", "--tail=-1", f"--since-time={cursor['time']}",
                       "--request-timeout=15s"]
            if previous:
                command.append("--previous=true")
            try:
                try:
                    result = subprocess.run(command, capture_output=True, timeout=25)
                except subprocess.TimeoutExpired as error:
                    partial = error.stdout or b""
                    if isinstance(partial, bytes):
                        partial = partial.decode("utf-8", errors="replace")
                    partial = partial[:partial.rfind("\n") + 1]
                    result = subprocess.CompletedProcess(command, 1, partial, "Log download timed out")
                output = result.stdout
                detail = result.stderr
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="replace")
                if isinstance(detail, bytes):
                    detail = detail.decode("utf-8", errors="replace")
                if detail.strip():
                    print(f"{name} restart={restart}: {detail.strip()}", file=sys.stderr)
                added, updated = new_records(output, cursor, name, restart)
                records.extend(added)
                cursors[key] = updated
                if result.returncode:
                    print(f"WARNING: Log download failed: {name} restart={restart} "
                          f"(exit {result.returncode})", file=sys.stderr)
                    failed = True
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print(f"WARNING: Cannot collect {name} restart={restart}: {error}", file=sys.stderr)
                failed = True
    append_records(directory, targets, records, checkpoint)
    state["cursors"] = cursors
    state["restarts"] = restarts
    print(f"Checkpoint {checkpoint}: saved {len(records)} lines to "
          f"{', '.join(target['path'] for target in targets)}", file=sys.stderr)
    return not failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--since-time", required=True)
    parser.add_argument("--checkpoint", default="session")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--begin", metavar="SCENARIO")
    action.add_argument("--end", action="store_true")
    parser.add_argument("--agents", nargs="+", default=[])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--agent")
    parser.add_argument("--run-index", type=int)
    args = parser.parse_args()
    try:
        args.directory.mkdir(parents=True, exist_ok=True)
        path = args.directory / STATE_FILE
        state = json.loads(path.read_text()) if path.exists() else {"since": args.since_time}
        timestamp_ns(state["since"])
        success = capture(args.directory, state, args.checkpoint)
        if args.begin:
            state["active"] = log_targets(
                args.begin, args.agents, args.repeat, args.agent, args.run_index,
            )
            append_records(args.directory, state["active"], [], args.checkpoint)
        elif args.end and success:
            state["active"] = []
        write_atomic(path, json.dumps(state, indent=2) + "\n")
        return 0 if success else 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"WARNING: App-server log capture failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
