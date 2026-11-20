"""Check Chat log snapshots, restart recovery, and log paths."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("capture_chat_logs", SCRIPTS / "capture-chat-logs.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SINCE = "2026-10-26T12:00:00Z"
T1 = "2026-10-26T12:00:01.123456789Z"
T2 = "2026-10-26T12:00:01.123456790Z"
T3 = "2026-10-26T12:00:02Z"


def pod(name="server-old", uid="old-uid", restarts=0):
    return {
        "metadata": {"name": name, "uid": uid},
        "status": {"containerStatuses": [
            {"name": "exporter", "restartCount": 0},
            {"name": MODULE.CONTAINER, "restartCount": restarts},
        ]},
    }


@pytest.fixture
def collector(monkeypatch, tmp_path):
    pods = [pod()]
    outputs = {}
    calls = []
    monkeypatch.setattr(MODULE, "read_pods", lambda: pods)

    def run(command, **kwargs):
        calls.append(command)
        assert "--tail=-1" in command
        assert "--timestamps=true" in command
        assert "--request-timeout=15s" in command
        assert "--follow" not in command
        assert command[command.index("-c") + 1] == MODULE.CONTAINER
        value = outputs.get((command[4], "--previous=true" in command), "")
        if isinstance(value, Exception):
            raise value
        if isinstance(value, subprocess.CompletedProcess):
            return value
        return subprocess.CompletedProcess(command, 0, value, "")

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    state = {"since": SINCE, "active": MODULE.log_targets(
        "scenarios/netobserv/dns_latency", ["model-a"], 1,
    )}
    return tmp_path, state, pods, outputs, calls


def contents(root):
    return (root / "logs/netobserv/dns_latency/model-a-run_1.log").read_text()


def test_timestamps_keep_nanoseconds():
    assert MODULE.timestamp_ns(T2) - MODULE.timestamp_ns(T1) == 1
    assert MODULE.timestamp_ns(T3) == MODULE.timestamp_ns("2026-10-26T12:00:02.000000000Z")


def test_names_include_group_agent_and_repeat():
    targets = MODULE.log_targets("scenarios/netobserv/dns_latency", ["model-a", "model-b"], 2)
    assert [item["path"] for item in targets] == [
        "logs/netobserv/dns_latency/model-a-run_1.log",
        "logs/netobserv/dns_latency/model-a-run_2.log",
        "logs/netobserv/dns_latency/model-b-run_1.log",
        "logs/netobserv/dns_latency/model-b-run_2.log",
    ]
    assert all(item["shared"] for item in targets)
    selected = MODULE.log_targets("scenarios/dns_latency", ["model-a", "model-b"], 2,
                                  agent="model-b", run_index=2)
    assert selected[0]["path"] == "logs/dns_latency/model-b-run_2.log"
    assert not selected[0]["shared"]
    with pytest.raises(ValueError):
        MODULE.log_targets("scenarios/../outside", ["model-a"], 1)


def test_repeated_snapshots_keep_real_duplicates_and_new_boundary_lines(collector):
    root, state, _, outputs, calls = collector
    outputs[("server-old", False)] = f"{T1} repeated\n{T1} repeated\n"
    assert MODULE.capture(root, state, "first")
    assert MODULE.capture(root, state, "same")
    outputs[("server-old", False)] += f"{T1} repeated\n{T1} other\n{T2} next\n"
    assert MODULE.capture(root, state, "new")
    text = contents(root)
    assert text.count("] repeated\n") == 3
    assert text.count("] other\n") == 1
    assert text.count("] next\n") == 1
    assert f"--since-time={T1}" in calls[-1]


def test_previous_instance_reuses_cursor_after_restart(collector):
    root, state, pods, outputs, _ = collector
    outputs[("server-old", False)] = f"{T1} before crash\n"
    assert MODULE.capture(root, state, "before")
    pods[0] = pod(restarts=1)
    outputs[("server-old", True)] = f"{T1} before crash\n{T2} crash detail\n"
    outputs[("server-old", False)] = f"{T3} restarted\n"
    assert MODULE.capture(root, state, "after")
    assert MODULE.capture(root, state, "again")
    text = contents(root)
    assert text.count("] before crash\n") == 1
    assert text.count("] crash detail\n") == 1
    assert text.count("] restarted\n") == 1
    assert "restart=0] crash detail" in text
    assert "restart=1] restarted" in text


def test_multiple_pods_and_replacement_keep_separate_cursors(collector):
    root, state, pods, outputs, _ = collector
    pods.append(pod("server-new", "new-uid"))
    for name in ("server-old", "server-new"):
        outputs[(name, False)] = f"{T1} same message\n"
    assert MODULE.capture(root, state, "rollout")
    pods.pop(0)
    assert MODULE.capture(root, state, "new-pod")
    assert contents(root).count("] same message\n") == 2
    assert "pod=server-old" in contents(root)
    assert "pod=server-new" in contents(root)


def test_partial_failure_is_saved_and_can_be_retried(collector):
    root, state, _, outputs, _ = collector
    outputs[("server-old", False)] = subprocess.CompletedProcess(
        [], 1, f"{T1} partial evidence\n", "connection lost",
    )
    assert not MODULE.capture(root, state, "failed")
    outputs[("server-old", False)] = f"{T1} partial evidence\n{T2} remaining evidence\n"
    assert MODULE.capture(root, state, "retry")
    assert contents(root).count("] partial evidence\n") == 1
    assert contents(root).count("] remaining evidence\n") == 1


def test_timeout_keeps_complete_lines(collector):
    root, state, _, outputs, _ = collector
    outputs[("server-old", False)] = subprocess.TimeoutExpired(
        "oc", 25, output=f"{T1} complete\n{T2} incom".encode(),
    )
    assert not MODULE.capture(root, state, "timeout")
    assert "] complete\n" in contents(root)
    assert "incom" not in contents(root)


def test_progress_output_keeps_carriage_returns_and_unicode_separators(collector):
    root, state, _, outputs, _ = collector
    outputs[("server-old", False)] = subprocess.CompletedProcess(
        [], 0, f"{T1} \rLoading weights: 0%\rLoading weights: 100%\u2028done\n".encode(), b"",
    )
    assert MODULE.capture(root, state, "startup")
    saved = (root / "logs/netobserv/dns_latency/model-a-run_1.log").read_bytes().decode()
    assert "\rLoading weights: 0%\rLoading weights: 100%\u2028done" in saved
    assert MODULE.capture(root, state, "again")
    assert contents(root).count("Loading weights: 100%") == 1


def test_multiple_restarts_report_missing_history(collector, capsys):
    root, state, pods, outputs, _ = collector
    assert MODULE.capture(root, state, "baseline")
    pods[0] = pod(restarts=3)
    outputs[("server-old", True)] = f"{T1} previous\n"
    outputs[("server-old", False)] = f"{T2} current\n"
    assert not MODULE.capture(root, state, "three-crashes")
    assert "restarted 3 times between captures" in capsys.readouterr().err
    assert "restart=2] previous" in contents(root)
    assert "restart=3] current" in contents(root)


def test_shared_window_is_explicit_in_each_named_file(collector):
    root, state, _, outputs, _ = collector
    state["active"] = MODULE.log_targets("scenarios/group/case", ["model-a", "model-b"], 2)
    outputs[("server-old", False)] = f"{T1} shared evidence\n"
    assert MODULE.capture(root, state, "parallel")
    files = list((root / "logs/group/case").glob("*.log"))
    assert len(files) == 4
    for path in files:
        text = path.read_text()
        assert "Shared scenario window" in text
        assert text.count("] shared evidence\n") == 1


def test_cli_routes_setup_evaluation_and_cleanup_and_persists_cursors(collector, monkeypatch):
    root, _, _, outputs, _ = collector

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["capture-chat-logs.py", str(root),
                                         "--since-time", SINCE, *args])
        return MODULE.main()

    outputs[("server-old", False)] = f"{T1} setup\n"
    assert invoke("--begin", "scenarios/netobserv/dns_latency", "--agents", "model-a") == 0
    outputs[("server-old", False)] += f"{T2} investigation\n"
    assert invoke("--end") == 0
    outputs[("server-old", False)] += f"{T3} cleanup\n"
    assert invoke() == 0
    assert invoke() == 0
    assert "] investigation\n" in contents(root)
    assert "] setup\n" not in contents(root)
    assert "] cleanup\n" not in contents(root)
    setup = (root / "logs/lightspeed-app-server-setup.log").read_text()
    assert setup.count("] setup\n") == setup.count("] cleanup\n") == 1
    assert json.loads((root / MODULE.STATE_FILE).read_text())["active"] == []


def test_cli_remembers_active_run_when_capture_fails(collector, monkeypatch):
    root, _, _, outputs, _ = collector
    monkeypatch.setattr(sys, "argv", ["capture", str(root), "--since-time", SINCE,
                                     "--begin", "scenarios/case", "--agents", "model-a"])
    assert MODULE.main() == 0
    outputs[("server-old", False)] = subprocess.CompletedProcess([], 1, "", "failed")
    monkeypatch.setattr(sys, "argv", ["capture", str(root), "--since-time", SINCE, "--end"])
    assert MODULE.main() == 1
    assert json.loads((root / MODULE.STATE_FILE).read_text())["active"]


def test_pod_read_failure_reports_server_reason(collector, monkeypatch, capsys):
    root, state, _, _, _ = collector

    def fail():
        raise subprocess.CalledProcessError(1, ["oc", "get", "pods"], stderr="Forbidden")

    monkeypatch.setattr(MODULE, "read_pods", fail)
    assert not MODULE.capture(root, state, "failed-list")
    assert "Forbidden" in capsys.readouterr().err
    assert "cursors" not in state
