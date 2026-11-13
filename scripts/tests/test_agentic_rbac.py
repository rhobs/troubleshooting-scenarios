"""Check Agentic RBAC setup, reruns, and missing permissions without a cluster."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "agentic-rbac.py"
SPEC = importlib.util.spec_from_file_location("agentic_rbac", SCRIPT)
rbac = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rbac)
REQUIREMENTS = [
    ("lightspeed-agent", "cluster-reader"),
    ("lightspeed-agent", "cluster-monitoring-view"),
    ("test-controller", "cluster-admin"),
]


@pytest.fixture
def cluster(monkeypatch):
    bindings = {}
    calls = []

    def oc(*args, resource=None):
        calls.append(args)
        if args[0] == "apply":
            bindings[resource["metadata"]["name"]] = copy.deepcopy(resource)
            return "configured"
        if args[:2] == ("auth", "can-i"):
            return "yes"
        if args[:2] == ("get", "deployment"):
            if args[2] == rbac.DEPLOYMENTS[0]:
                return ""
            return json.dumps({"spec": {"template": {"spec": {
                "serviceAccountName": "test-controller",
            }}}})
        raise AssertionError(args)

    monkeypatch.setattr(rbac, "oc", oc)
    return bindings, calls


def test_setup_can_run_twice_and_keeps_sandbox_subjects(cluster):
    bindings, calls = cluster
    rbac.setup([], REQUIREMENTS)
    assert len(bindings) == 3
    reader = bindings["troubleshooting-scenarios-agentic-cluster-reader"]
    reader["subjects"].append(rbac.subject("analysis-sandbox"))
    before = copy.deepcopy(bindings)
    rbac.setup(list(bindings.values()), REQUIREMENTS)
    assert bindings == before
    rbac.check(list(bindings.values()), REQUIREMENTS)
    assert any(call[:4] == ("auth", "can-i", "escalate", "clusterroles.rbac.authorization.k8s.io")
               for call in calls)
    assert any(call[:4] == ("auth", "can-i", "get", "pods") and "--subresource=log" in call
               for call in calls)


@pytest.mark.parametrize("role", ["cluster-reader", "cluster-monitoring-view", "cluster-admin"])
@pytest.mark.parametrize("fault", ["missing", "wrong-subject", "wrong-role"])
def test_check_rejects_incomplete_bindings(cluster, role, fault):
    bindings, _ = cluster
    rbac.setup([], REQUIREMENTS)
    binding = bindings[f"troubleshooting-scenarios-agentic-{role}"]
    if fault == "missing":
        del bindings[binding["metadata"]["name"]]
    elif fault == "wrong-subject":
        binding["subjects"][0]["namespace"] = "other-namespace"
    else:
        binding["roleRef"]["name"] = "view"
    with pytest.raises(ValueError, match=role):
        rbac.check(list(bindings.values()), REQUIREMENTS)


@pytest.mark.parametrize("fault", ["owner", "role"])
def test_setup_does_not_replace_foreign_bindings(cluster, fault):
    bindings, _ = cluster
    rbac.setup([], REQUIREMENTS)
    reader = bindings["troubleshooting-scenarios-agentic-cluster-reader"]
    if fault == "owner":
        reader["metadata"]["labels"] = {}
    else:
        reader["roleRef"]["name"] = "view"
    before = copy.deepcopy(bindings)
    with pytest.raises(ValueError, match="different owner or role"):
        rbac.setup(list(bindings.values()), REQUIREMENTS)
    assert bindings == before


def test_controller_account_uses_quickstart_deployment(cluster):
    assert rbac.controller_account() == "test-controller"


def test_check_rejects_denied_permission(cluster, monkeypatch):
    bindings, _ = cluster
    rbac.setup([], REQUIREMENTS)
    monkeypatch.setattr(rbac, "oc", lambda *args: "no")
    with pytest.raises(ValueError, match="cannot list pods"):
        rbac.check(list(bindings.values()), REQUIREMENTS)


def test_check_rejects_denied_monitoring_access(cluster, monkeypatch):
    bindings, _ = cluster
    rbac.setup([], REQUIREMENTS)
    monkeypatch.setattr(rbac, "oc", lambda *args: "no" if "--subresource=api" in args else "yes")
    with pytest.raises(ValueError, match="monitoring API"):
        rbac.check(list(bindings.values()), REQUIREMENTS)


def test_permission_denial_reports_the_account_and_operation(cluster, monkeypatch):
    bindings, _ = cluster
    rbac.setup([], REQUIREMENTS)

    def denied(*args):
        raise subprocess.CalledProcessError(1, ["oc", *args], output="no\n", stderr="")

    monkeypatch.setattr(rbac, "oc", denied)
    with pytest.raises(ValueError, match="lightspeed-agent cannot list pods"):
        rbac.check(list(bindings.values()), REQUIREMENTS)


def test_cleanup_removes_only_managed_cluster_bindings(tmp_path):
    binary = tmp_path / "oc"
    binary.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$OC_LOG"\n')
    binary.chmod(0o755)
    log = tmp_path / "oc.log"
    result = subprocess.run(
        ["bash", str(SCRIPT.with_name("cleanup-ols.sh"))],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "OC_LOG": str(log)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    deletes = [line for line in log.read_text().splitlines() if "clusterrolebinding" in line]
    assert deletes == ["delete clusterrolebinding -l troubleshooting-scenarios/rbac=agentic --ignore-not-found"]
