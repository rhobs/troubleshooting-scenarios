"""Check OLS setup and failure handling without a cluster."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("service", ["agentic", "classic"])
def test_scenario_metrics_are_declared_in_system_config(service):
    config = yaml.safe_load((ROOT / f"evals/system-ols-{service}.yaml").read_text())
    known_metrics = config["metrics_metadata"]["turn_level"]
    for path in (ROOT / "evals/scenarios").rglob(f"evals-ols-{service}.yaml"):
        if "_disabled" in path.parts:
            continue
        for conversation in yaml.safe_load(path.read_text()) or []:
            for turn in conversation["turns"]:
                unknown = set(turn.get("turn_metrics", [])) - known_metrics.keys()
                assert not unknown, f"{path}: unknown turn metrics {sorted(unknown)}"


def executable(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


@pytest.fixture
def workspace(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    # Wrapper behavior is tested separately with the framework driver.
    (scripts / "agentic-eval.py").write_text(
        "import os, sys\nos.execv(sys.argv[2], sys.argv[2:])\n"
    )
    for name in (
        "eval-ols-agentic.sh", "ci-ols-agentic-evals.sh", "sync-agent-crs.py",
        "setup-ols-agentic.sh", "install-ols-operator.sh",
        "show-eval-summary.py", "show-eval-summary.sh",
        "resolve-setup-mode.sh",
        "eval-report.sh", "report_progress.py",
        "capture-config-crs.py",
        "capture-classic-logs.py",
    ):
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    executable(scripts / "preflight.sh", "#!/bin/bash\nexit 0\n")
    # Most workflow tests use a small watcher with no cluster access.
    (scripts / "sandbox_logs.py").write_text(
        "from pathlib import Path\nimport signal\nimport sys\n"
        "def capture_logs(directory, on_ready=None, crs_directory=None):\n"
        "    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "    Path(directory).mkdir(parents=True, exist_ok=True)\n"
        "    if on_ready is not None: on_ready()\n"
        "    signal.pause()\n"
        "    return 0\n"
    )
    evals = tmp_path / "evals"
    evals.mkdir()
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    shutil.copy(ROOT / "evals/system-ols-agentic.yaml", evals / "system-ols-agentic.yaml")
    executable(
        tmp_path / "venv/bin/python3",
        f'#!/bin/bash\nexec "{sys.executable}" "$@"\n',
    )
    return tmp_path


@pytest.fixture
def classic_workspace(workspace):
    shutil.copy(ROOT / "scripts/eval-ols-classic.sh", workspace / "scripts/eval-ols-classic.sh")
    executable(workspace / "bin/curl", "#!/bin/bash\nexit 0\n")
    executable(
        workspace / "bin/oc",
        '#!/bin/bash\nif [ "$1" = whoami ]; then echo test-token; fi\n',
    )
    (workspace / "evals/system-ols-classic.yaml").write_text(yaml.safe_dump({
        "agents": {
            "default": {"agent": ["test-agent"], "repeat": 2},
            "test-agent": {"description": "test|model"},
        },
    }))
    (workspace / "scripts/generate-report-classic.py").write_text(
        'import os, sys\n'
        'with open(os.environ["EVENT_LOG"], "a") as f:\n'
        '    f.write("report\\n")\n'
        'with open(sys.argv[-1], "w") as f:\n'
        '    f.write("report\\n")\n'
    )
    return workspace


@pytest.fixture
def namespace_workspace(classic_workspace):
    root = classic_workspace
    for name in ("scenario-namespace.sh", "check-prerequisites.sh"):
        shutil.copy(ROOT / "scripts" / name, root / "scripts" / name)
    executable(root / "scripts/enable-uwm.sh", "#!/bin/bash\nexit 0\n")
    executable(root / "scripts/run-agentic-evals.sh", "#!/bin/bash\nexit 0\n")
    shutil.copy(
        root / "scripts/generate-report-classic.py",
        root / "scripts/generate-report-agentic.py",
    )
    for name in ("_disabled/restarting_pod_alert", "batch_submission_timeouts"):
        shutil.copytree(ROOT / "evals/scenarios" / name, root / "evals/scenarios" / name)
    # Stop setup after namespace creation, without builds or a cluster.
    executable(root / "bin/podman", "#!/bin/bash\nexit 23\n")
    executable(root / "bin/curl", "#!/bin/bash\necho 401\n")
    executable(root / "bin/python3", "#!/bin/bash\nexit 0\n")
    executable(root / "bin/oc", f"#!{sys.executable}\n" + '''
import os
from pathlib import Path
import sys
import yaml

args = sys.argv[1:]
state = Path(os.environ["NAMESPACE_STATE"])
with open(os.environ["OC_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
if args[:1] == ["whoami"]:
    print("test-token")
elif args[:2] == ["config", "current-context"]:
    print("test-context")
elif args[:2] == ["get", "namespace"]:
    if os.environ.get("NAMESPACE_GET_FAIL"):
        sys.exit(19)
    if state.exists():
        if "jsonpath={.metadata.uid}" in args:
            print(state.read_text(), end="")
        elif "jsonpath={.status.phase}" in args:
            print("Active")
    elif "--ignore-not-found" not in args:
        print("Error from server (NotFound)", file=sys.stderr)
        sys.exit(1)
elif args[:1] == ["create"]:
    assert yaml.safe_load(Path(args[args.index("-f") + 1]).read_text())["kind"] == "Namespace"
    if state.exists() or os.environ.get("NAMESPACE_CREATE_FAIL"):
        print("Error from server (AlreadyExists)", file=sys.stderr)
        sys.exit(33)
    state.write_text("created-uid")
    print("created-uid", end="")
elif args[:2] == ["delete", "namespace"]:
    state.unlink(missing_ok=True)
elif args[:2] == ["registry", "login"]:
    Path(next(arg[5:] for arg in args if arg.startswith("--to="))).write_text("{}")
''')
    return root


@pytest.mark.parametrize("service", ["agentic", "classic"])
@pytest.mark.parametrize("setup_mode", ["scenario", "run"])
@pytest.mark.parametrize("scenario_name,namespace", [
    ("_disabled/restarting_pod_alert", "data-processing"),
    ("batch_submission_timeouts", "data-pipeline"),
])
@pytest.mark.parametrize("existing", [True, False])
def test_failed_setup_only_cleans_its_namespace(
    namespace_workspace, service, setup_mode, scenario_name, namespace, existing
):
    root = namespace_workspace
    state = root / "namespace"
    if existing:
        state.write_text("existing-uid")
    # An earlier standalone setup must not give this run permission to delete.
    previous_state = root / "evals/results/.scenario-state"
    previous_state.mkdir(parents=True)
    (previous_state / f"{namespace}.uid").write_text("existing-uid")
    config = root / f"evals/system-ols-{service}.yaml"
    config.write_text(yaml.safe_dump({
        "agents": {"default": {"agent": ["test-agent"], "repeat": 2}},
    }))
    result = subprocess.run(
        ["bash", str(root / f"scripts/eval-ols-{service}.sh"),
         "--system-config", config.name, "--setup-mode", setup_mode,
         "--scenarios", f"scenarios/{scenario_name}"],
        cwd=root / "evals",
        env={**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
             "NAMESPACE_STATE": str(state), "OC_LOG": str(root / "oc.log"),
             "EVENT_LOG": str(root / "events")},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    calls = (root / "oc.log").read_text()
    if existing:
        assert state.read_text() == "existing-uid"
        assert "delete namespace" not in calls
    else:
        assert not state.exists(), result.stdout + result.stderr
        assert calls.count(f"delete namespace {namespace}") == (2 if setup_mode == "run" else 1)
    assert not list((root / "evals/results").glob("*/.scenario-state.*"))


@pytest.mark.parametrize("scenario_name,namespace", [
    ("_disabled/restarting_pod_alert", "data-processing"),
    ("batch_submission_timeouts", "data-pipeline"),
])
@pytest.mark.parametrize("namespace_uid,read_error", [
    ("created-uid", False), ("replacement-uid", False), (None, False),
    ("created-uid", True),
])
def test_standalone_cleanup_checks_namespace_identity(
    namespace_workspace, scenario_name, namespace, namespace_uid, read_error
):
    root = namespace_workspace
    state = root / "namespace"
    env = {**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
           "NAMESPACE_STATE": str(state), "OC_LOG": str(root / "oc.log")}
    scenario = root / "evals/scenarios" / scenario_name
    create = subprocess.run(
        ["bash", "-c", 'source "$1"; scenario_create_namespace "$2" "$3" oc',
         "bash", str(root / "scripts/scenario-namespace.sh"), namespace,
         str(scenario / "fixtures/namespace.yaml")],
        env=env, capture_output=True, text=True,
    )
    assert create.returncode == 0, create.stdout + create.stderr
    if namespace_uid is None:
        state.unlink()
    else:
        state.write_text(namespace_uid)
    if read_error:
        env["NAMESPACE_GET_FAIL"] = "1"
    cleanup = subprocess.run(
        ["bash", str(scenario / "cleanup.sh")], env=env,
        capture_output=True, text=True, timeout=10,
    )
    assert cleanup.returncode == (2 if read_error else 0), cleanup.stdout + cleanup.stderr
    should_delete = namespace_uid == "created-uid" and not read_error
    assert (f"delete namespace {namespace}" in (root / "oc.log").read_text()) == should_delete
    if namespace_uid and not should_delete:
        assert state.read_text() == namespace_uid
    else:
        assert not state.exists()
        assert not (root / f"evals/results/.scenario-state/{namespace}.uid").exists()


def test_failed_namespace_create_does_not_record_ownership(namespace_workspace):
    root = namespace_workspace
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; scenario_create_namespace data-processing "$2" oc',
         "bash", str(root / "scripts/scenario-namespace.sh"),
         str(root / "evals/scenarios/_disabled/restarting_pod_alert/fixtures/namespace.yaml")],
        env={**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
             "NAMESPACE_STATE": str(root / "namespace"), "OC_LOG": str(root / "oc.log"),
             "NAMESPACE_CREATE_FAIL": "1"},
        capture_output=True, text=True,
    )
    assert result.returncode == 33, result.stdout + result.stderr
    assert not list((root / "evals/results/.scenario-state").iterdir())


@pytest.mark.parametrize("single_agent", [True, False])
@pytest.mark.parametrize("eval_status,output_kind", [
    (0, "results"), (42, "results"), (42, "logs"), (42, "empty"), (0, "empty"),
])
def test_evaluator_saves_output_and_returns_its_status(workspace, single_agent, eval_status, output_kind):
    root = workspace
    shutil.copy(ROOT / "scripts/run-agentic-evals.sh", root / "scripts/run-agentic-evals.sh")
    executable(root / "venv/bin/lightspeed-eval", f"#!{sys.executable}\n" + '''
import os
from pathlib import Path
import sys

args = sys.argv[1:]
output = Path(args[args.index("--output-dir") + 1])
Path(os.environ["TEMP_OUTPUT_PATH"]).write_text(str(output))
kind = os.environ["OUTPUT_KIND"]
if kind != "empty":
    (output / "startup.log").write_text("startup evidence")
if kind == "results":
    run = output / "eval_123/test-agent/run_1"
    run.mkdir(parents=True)
    (run / "result.json").write_text("partial result")
    (run / "eval.log").write_text("run evidence")
    (output / "eval_123/eval_report.json").write_text("partial report")
sys.exit(int(os.environ["EVAL_STATUS"]))
''')
    output = root / "output"
    # Copying a new scenario must keep output already saved for another one.
    destination = output / "test-agent" / ("run_3" if single_agent else "run_1")
    destination.mkdir(parents=True)
    (destination / "earlier.json").write_text("earlier result")
    result = subprocess.run(
        ["bash", str(root / "scripts/run-agentic-evals.sh"),
         "--system-config", str(root / "evals/system-ols-agentic.yaml"),
         "--evals", "evals.yaml", "--eval-dir", str(output),
         *(["--agent", "test-agent", "--run-index", "3"] if single_agent else [])],
        env={**os.environ, "EVAL_OPENAI_API_KEY": "test-key", "EVAL_STATUS": str(eval_status),
             "OUTPUT_KIND": output_kind, "TEMP_OUTPUT_PATH": str(root / "temp-output")},
        capture_output=True, text=True,
    )
    assert result.returncode == eval_status, result.stdout + result.stderr
    assert (destination / "earlier.json").read_text() == "earlier result"
    if output_kind == "results":
        assert (destination / "result.json").read_text() == "partial result"
        assert (destination / "eval.log").read_text() == "run evidence"
        assert (output / "eval_report.json").read_text() == "partial report"
    if eval_status:
        saved = list((output / "failed-evals").iterdir())
        assert len(saved) == 1
        if output_kind != "empty":
            assert (saved[0] / "startup.log").read_text() == "startup evidence"
    else:
        assert not (output / "failed-evals").exists()
    assert not Path((root / "temp-output").read_text()).exists()


@pytest.mark.parametrize("blocked_path", ["failed-evals", "test-agent"])
def test_evaluator_copy_failure_keeps_original_status_and_output(workspace, blocked_path):
    root = workspace
    shutil.copy(ROOT / "scripts/run-agentic-evals.sh", root / "scripts/run-agentic-evals.sh")
    executable(root / "venv/bin/lightspeed-eval", '''#!/bin/bash
while [ "$1" != --output-dir ]; do shift; done
output="$2"
echo "$output" > "$TEMP_OUTPUT_PATH"
mkdir -p "$output/eval_123/test-agent/run_1"
echo evidence > "$output/eval_123/test-agent/run_1/eval.log"
exit 42
''')
    output = root / "output"
    output.mkdir()
    (output / blocked_path).write_text("cannot copy here")
    result = subprocess.run(
        ["bash", str(root / "scripts/run-agentic-evals.sh"),
         "--system-config", str(root / "evals/system-ols-agentic.yaml"),
         "--evals", "evals.yaml", "--eval-dir", str(output)],
        env={**os.environ, "EVAL_OPENAI_API_KEY": "test-key",
             "TEMP_OUTPUT_PATH": str(root / "temp-output")},
        capture_output=True, text=True,
    )
    assert result.returncode == 42, result.stdout + result.stderr
    temporary_output = Path((root / "temp-output").read_text().strip())
    if blocked_path == "failed-evals":
        try:
            assert (temporary_output / "eval_123/test-agent/run_1/eval.log").read_text() == "evidence\n"
            assert f"files remain in {temporary_output}" in result.stderr
        finally:
            shutil.rmtree(temporary_output, ignore_errors=True)
    else:
        saved = list((output / "failed-evals").glob("*/eval_123/test-agent/run_1/eval.log"))
        assert len(saved) == 1
        assert saved[0].read_text() == "evidence\n"
        assert not temporary_output.exists()


@pytest.mark.parametrize("mode", ["agentic", "classic"])
def test_preflight_checks_the_selected_service(tmp_path, mode):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(ROOT / "scripts/preflight.sh", scripts / "preflight.sh")
    executable(
        tmp_path / "bin/oc",
        '#!/bin/bash\n'
        'echo "$*" >> "$PREFLIGHT_LOG"\n'
        'case "$1" in\n'
        '  whoami) echo test-user ;;\n'
        '  api-resources)\n'
        '    case "$2" in\n'
        '      --api-group=agentic.openshift.io) echo "agents agentic.openshift.io/v1alpha1" ;;\n'
        '      --api-group=ols.openshift.io) echo "olsconfigs ols.openshift.io/v1alpha1" ;;\n'
        '    esac ;;\n'
        '  get)\n'
        '    if [[ "$*" == *jsonpath* ]]; then echo True; else echo deployment.apps/lightspeed-app-server; fi ;;\n'
        'esac\n',
    )
    executable(
        tmp_path / "venv/bin/python3",
        '#!/bin/bash\necho "$*" >> "$PREFLIGHT_LOG"\n',
    )
    executable(tmp_path / "venv/bin/lightspeed-eval", "#!/bin/bash\n")
    log = tmp_path / "preflight.log"
    args = ["--require-ols"] if mode == "classic" else [
        "--require-agentic", "--system-config", "system-ols-agentic.yaml",
    ]
    result = subprocess.run(
        ["bash", str(scripts / "preflight.sh"), *args],
        env={
            **os.environ,
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
            "EVAL_OPENAI_API_KEY": "test-key",
            "PREFLIGHT_LOG": str(log),
        },
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for message in ("oc available", "logged in as test-user", "evaluation tools available",
                    "EVAL_OPENAI_API_KEY set", "Preflight complete"):
        assert message in result.stdout
    calls = log.read_text()
    if mode == "agentic":
        assert "--api-group=agentic.openshift.io" in calls
        assert "sync-agent-crs.py --check system-ols-agentic.yaml" in calls
        assert "Agent CRs match" in result.stdout
        assert "--api-group=ols.openshift.io" not in calls
    else:
        assert "--api-group=ols.openshift.io" in calls
        assert "OpenShift Lightspeed is available" in result.stdout
        assert "--api-group=agentic.openshift.io" not in calls
        assert "sync-agent-crs.py" not in calls


@pytest.mark.parametrize("mode", ["agentic", "classic"])
@pytest.mark.parametrize("preview", ["0", "1"])
@pytest.mark.parametrize("filters", [[], ["SCENARIO=", "TAG="], ["SCENARIO= ", "TAG= "]])
def test_eval_requires_a_filter_before_running(workspace, mode, preview, filters):
    log = workspace / "events"
    executable(
        workspace / "scripts/preflight.sh",
        '#!/bin/bash\necho preflight >> "$EVENT_LOG"\nexit 1\n',
    )
    result = subprocess.run(
        ["make", f"eval-ols-{mode}", f"PREVIEW={preview}", *filters],
        cwd=workspace,
        env={**os.environ, "SCENARIO": "", "TAG": "", "EVENT_LOG": str(log)},
        capture_output=True, text=True,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "set at least one filter: SCENARIO=... or TAG=..." in result.stderr
    assert "Preview only:" not in result.stdout
    assert not log.exists()
    assert not (workspace / "evals/results").exists()


@pytest.mark.parametrize("mode", ["agentic", "classic"])
def test_eval_accepts_a_tag_filter(request, mode):
    workspace = request.getfixturevalue("classic_workspace" if mode == "classic" else "workspace")
    name = "crashlooping_pod_alert"
    scenario = workspace / "evals/scenarios" / name
    scenario.mkdir(parents=True)
    filename = f"evals-ols-{mode}.yaml"
    shutil.copy(ROOT / "evals/scenarios" / name / filename, scenario / filename)
    result = subprocess.run(
        ["make", f"eval-ols-{mode}", "TAG=investigation", "PREVIEW=1"],
        cwd=workspace,
        env={**os.environ, "SCENARIO": ""},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"scenarios:  1\n  {name}" in result.stdout


@pytest.mark.parametrize("mode", ["agentic", "classic"])
@pytest.mark.parametrize("setup_mode,remediation,effective_mode", [
    ("run", False, "run"),
    ("auto", False, "scenario"),
    ("auto", True, "run"),
    ("scenario", True, "scenario"),
    ("skip", True, "skip"),
])
def test_preview_summary_matches_real_run(request, mode, setup_mode, remediation, effective_mode):
    root = request.getfixturevalue("classic_workspace" if mode == "classic" else "workspace")
    config_path = root / "evals" / f"system-ols-{mode}.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["agents"]["default"]["parallel"] = True
    config_path.write_text(yaml.safe_dump(config))
    scenario_name = "crashlooping_pod_alert"
    scenario = root / "evals/scenarios" / scenario_name
    scenario.mkdir(parents=True)
    (scenario / f"evals-ols-{mode}.yaml").write_text(
        "- conversation_group_id: example\n  tag:\n    - remediation\n"
        if remediation else "[]\n"
    )
    executable(root / "scripts/run-agentic-evals.sh", "#!/bin/bash\nexit 0\n")

    if mode == "agentic":
        (root / "scripts/generate-report-agentic.py").write_text(
            'import sys\nwith open(sys.argv[-1], "w") as f: f.write("report\\n")\n'
        )

    env = {
        **os.environ,
        "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
        "EVENT_LOG": str(root / "events"),
    }
    preview = subprocess.run(
        ["make", f"eval-ols-{mode}", f"SCENARIO={scenario_name}",
         f"SETUP_MODE={setup_mode}", "PREVIEW=1"],
        cwd=root, env=env, capture_output=True, text=True,
    )
    runner = subprocess.run(
        ["bash", str(root / "scripts" / f"eval-ols-{mode}.sh"),
         "--system-config", f"system-ols-{mode}.yaml", "--setup-mode", setup_mode,
         "--scenarios", f"scenarios/{scenario_name}"],
        cwd=root / "evals", env=env, capture_output=True, text=True,
    )
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert runner.returncode == 0, runner.stdout + runner.stderr

    def summary(output):
        lines = output.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("setup_mode: "))
        return "\n".join(line for line in lines[start:] if line and not line.startswith("==>"))

    assert summary(preview.stdout) == summary(runner.stdout)
    assert f"setup_mode: {effective_mode}" in preview.stdout
    assert f"parallel:   {str(effective_mode != 'run').lower()}" in preview.stdout
    assert "scenarios:  1\n  crashlooping_pod_alert" in preview.stdout
    snapshots = list((root / "evals/results").glob(f"*/system-ols-{mode}.yaml"))
    assert len(snapshots) == 1
    assert snapshots[0].read_text() == config_path.read_text()
    session = snapshots[0].parent
    assert (session / "logs").is_dir()
    assert (session / "capture-logs.log").is_file()
    assert not list(session.glob(".capture-logs-ready.*"))


@pytest.mark.parametrize("mode", ["agentic", "classic"])
@pytest.mark.parametrize("olsconfig_error", [False, True])
def test_eval_saves_config_crs(request, mode, olsconfig_error):
    root = request.getfixturevalue("classic_workspace" if mode == "classic" else "workspace")
    resources = {
        "olsconfigs.ols.openshift.io": [{
            "apiVersion": "ols.openshift.io/v1alpha1", "kind": "OLSConfig",
            "metadata": {"name": "cluster", "resourceVersion": "4"},
            "spec": {"ols": {"defaultModel": "model"}},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }],
        "llmproviders.agentic.openshift.io": [{
            "apiVersion": "agentic.openshift.io/v1alpha1", "kind": "LLMProvider",
            "metadata": {"name": "provider", "namespace": "openshift-lightspeed"},
            "spec": {"type": "OpenAI", "openAI": {"credentialsSecret": {"name": "creds"}}},
        }],
        "agents.agentic.openshift.io": [{
            "apiVersion": "agentic.openshift.io/v1alpha1", "kind": "Agent",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {"model": "model", "llmProvider": {"name": "provider"}},
        } for namespace, name in (
            ("openshift-lightspeed", "model"), ("other", "model"),
            ("a-b", "c"), ("a", "b-c"),
        )],
    }
    (root / "resources.json").write_text(json.dumps(resources))
    executable(root / "bin/oc", f"#!{sys.executable}\n" + '''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args == ["whoami", "-t"]:
    print("test-token")
    sys.exit(0)
with open(os.environ["OC_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
if args[:2] == ["get", "pods"]:
    print('{"items": []}')
    sys.exit(0)
assert args[0] == "get"
assert "--all-namespaces" in args
if args[1] == "olsconfigs.ols.openshift.io" and os.environ["CONFIG_ERROR"] == "yes":
    print("OLSConfig read failed", file=sys.stderr)
    sys.exit(1)
resources = json.loads(Path(os.environ["CONFIG_RESOURCES"]).read_text())
print(json.dumps({"items": resources[args[1]]}))
''')
    scenario = root / "evals/scenarios/example"
    scenario.mkdir(parents=True)
    (scenario / f"evals-ols-{mode}.yaml").write_text("[]\n")
    executable(root / "scripts/run-agentic-evals.sh", "#!/bin/bash\nexit 0\n")
    (root / f"scripts/generate-report-{mode}.py").write_text(
        'import sys\nfrom pathlib import Path\nPath(sys.argv[-1]).write_text("report\\n")\n'
    )
    result = subprocess.run(
        ["bash", str(root / f"scripts/eval-ols-{mode}.sh"),
         "--system-config", f"system-ols-{mode}.yaml", "--setup-mode", "skip",
         "--scenarios", "scenarios/example"],
        cwd=root / "evals", capture_output=True, text=True, timeout=30,
        env={**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
             "EVENT_LOG": str(root / "events"), "OC_LOG": str(root / "oc.log"),
             "CONFIG_RESOURCES": str(root / "resources.json"),
             "CONFIG_ERROR": "yes" if olsconfig_error else "no"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    session = next((root / "evals/results").iterdir())
    expected = resources if mode == "agentic" else dict(list(resources.items())[:1])
    saved = []
    for resource_type, items in expected.items():
        if olsconfig_error and resource_type == "olsconfigs.ols.openshift.io":
            continue
        saved.extend(items)
    actual = [yaml.safe_load(path.read_text()) for path in (session / "crs").glob("*.yaml")]
    assert sorted(actual, key=str) == sorted(saved, key=str)
    commands = [line for line in (root / "oc.log").read_text().splitlines()
                if "--all-namespaces" in line]
    assert len(commands) == len(expected)
    assert all(command.split()[1] in expected for command in commands)
    log = (session / "capture-config-crs.log").read_text()
    if olsconfig_error:
        assert "OLSConfig read failed" in log
        assert "configuration CR capture failed" in result.stderr
    else:
        assert "Saved OLSConfig" in log


@pytest.mark.parametrize("mode", ["agentic", "classic"])
@pytest.mark.parametrize("setup_mode", ["auto", "run", "scenario", "skip"])
def test_eval_uses_saved_definitions(request, mode, setup_mode):
    root = request.getfixturevalue("classic_workspace" if mode == "classic" else "workspace")
    filename = f"evals-ols-{mode}.yaml"
    names = ["first", "group/first"]
    originals = {}
    for name in names:
        scenario = root / "evals/scenarios" / name
        scenario.mkdir(parents=True)
        content = f"- conversation_group_id: {name.replace('/', '_')}\n"
        if name == "group/first":
            content += "  tag:\n    - remediation\n"
        (scenario / filename).write_text(content)
        originals[name] = content
        (scenario / "fixtures").mkdir()
        (scenario / "fixtures/manifest.yaml").write_text("kind: Pod\n")
        (scenario / "notes.sh").write_text("#!/bin/bash\n")
    # Change the source files during the first evaluation. All runs must use
    # the copies saved before the session started.
    evaluator = root / "evaluator.py"
    evaluator.write_text(
        "from pathlib import Path\nimport sys\n"
        "args = sys.argv[1:]\n"
        "session = Path(args[args.index('--eval-dir') + 1])\n"
        "definition = Path(args[args.index('--evals') + 1])\n"
        "assert definition.is_relative_to(session / 'scenarios')\n"
        "assert definition.read_text() != 'changed\\n'\n"
        "with (session / 'used-definitions.txt').open('a') as log:\n"
        "    log.write(str(definition.relative_to(session)) + '\\n')\n"
        f"for source in Path('scenarios').rglob('{filename}'):\n"
        "    source.write_text('changed\\n')\n"
    )
    executable(
        root / "scripts/run-agentic-evals.sh",
        f'#!/bin/bash\nexec "{sys.executable}" "{evaluator}" "$@"\n',
    )
    (root / f"scripts/generate-report-{mode}.py").write_text(
        'import sys\nfrom pathlib import Path\nPath(sys.argv[-1]).write_text("report\\n")\n'
    )
    result = subprocess.run(
        ["bash", str(root / f"scripts/eval-ols-{mode}.sh"),
         "--system-config", f"system-ols-{mode}.yaml", "--setup-mode", setup_mode,
         "--scenarios", *[f"scenarios/{name}" for name in names]],
        cwd=root / "evals",
        env={**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    session = next((root / "evals/results").iterdir())
    for name, content in originals.items():
        assert (session / "scenarios" / name / filename).read_text() == content
        assert (root / "evals/scenarios" / name / filename).read_text() == "changed\n"
    saved_files = {str(path.relative_to(session))
                   for path in (session / "scenarios").rglob("*") if path.is_file()}
    assert saved_files == {f"scenarios/{name}/{filename}" for name in names}
    used = (session / "used-definitions.txt").read_text().splitlines()
    assert set(used) == {f"scenarios/{name}/{filename}" for name in names}
    config = yaml.safe_load((session / f"system-ols-{mode}.yaml").read_text())
    defaults = config["agents"]["default"]
    repeats = len(defaults["agent"]) * defaults["repeat"] if setup_mode in ("auto", "run") else 1
    assert len(used) == len(names) * repeats


@pytest.mark.parametrize("setup_mode", ["run", "scenario", "skip"])
@pytest.mark.parametrize("parallel", [True, False])
def test_summary_shows_effective_parallel_setting(tmp_path, setup_mode, parallel):
    config = tmp_path / "system.yaml"
    config.write_text(yaml.safe_dump({"agents": {"default": {"parallel": parallel}}}))
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/show-eval-summary.py"),
         "--system-config", str(config), "--setup-mode", setup_mode, "--scenarios"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    expected = parallel and setup_mode != "run"
    assert f"parallel:   {str(expected).lower()}" in result.stdout


@pytest.mark.parametrize("mode", ["agentic", "classic"])
def test_preview_works_without_python_yaml(request, mode):
    root = request.getfixturevalue("classic_workspace" if mode == "classic" else "workspace")
    executable(root / "bin/python3", "#!/bin/bash\nexit 1\n")
    result = subprocess.run(
        ["make", f"eval-ols-{mode}", "SCENARIO=crashlooping_pod_alert", "PREVIEW=1",
         "NOTE=Preview memo"],
        cwd=root,
        env={**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "setup_mode: scenario" in result.stdout
    assert "repeats:    (Python 3 and PyYAML needed for details)" in result.stdout
    assert "agents:     (Python 3 and PyYAML needed for details)" in result.stdout
    assert "scenarios:  1\n  crashlooping_pod_alert" in result.stdout
    assert "note:       Preview memo" in result.stdout


@pytest.mark.parametrize("mode", ["run", "scenario"])
@pytest.mark.parametrize(
    "setup_status,eval_status,cleanup_status,expected_status,events",
    [
        (23, 0, 0, 23, ["setup", "cleanup", "report"]),
        (0, 42, 0, 42, ["setup", "eval", "cleanup", "report"]),
        (0, 42, 9, 42, ["setup", "eval", "cleanup", "report"]),
        (0, 0, 9, 0, ["setup", "eval", "cleanup", "report"]),
        (0, 0, 0, 0, ["setup", "eval", "cleanup", "report"]),
    ],
)
def test_scenario_cleanup(
    workspace, mode, setup_status, eval_status, cleanup_status, expected_status, events
):
    (workspace / "evals/system-ols-agentic.yaml").write_text(yaml.safe_dump({
        "agents": {
            "default": {"repeat": 1},
            "openai-gpt-5-6-luna": {"description": "test|model"},
        }
    }))
    scenario = workspace / "evals/scenarios/sample"
    for name, status in (("setup", setup_status), ("cleanup", cleanup_status)):
        executable(
            scenario / f"{name}.sh",
            f'#!/bin/bash\necho {name} >> "$EVENT_LOG"\nexit {status}\n',
        )
    (scenario / "evals-ols-agentic.yaml").write_text("[]\n")
    executable(
        workspace / "scripts/run-agentic-evals.sh",
        f'#!/bin/bash\necho eval >> "$EVENT_LOG"\nexit {eval_status}\n',
    )
    (workspace / "scripts/generate-report-agentic.py").write_text(
        'import os\nwith open(os.environ["EVENT_LOG"], "a") as f:\n'
        '    f.write("report\\n")\n'
    )
    log = workspace / "events"
    result = subprocess.run(
        [
            "bash", str(workspace / "scripts/eval-ols-agentic.sh"),
            "--system-config", "system-ols-agentic.yaml",
            "--setup-mode", mode, "--agents", "openai-gpt-5-6-luna",
            "--scenarios", "scenarios/sample",
        ],
        cwd=workspace / "evals",
        env={**os.environ, "EVENT_LOG": str(log)},
        capture_output=True, text=True,
    )
    assert result.returncode == expected_status, result.stdout + result.stderr
    recorded = log.read_text().splitlines()
    assert [event for event in recorded if event != "report"] == events[:-1]
    assert recorded[0] == recorded[-1] == "report"
    # Initial report, one finished scenario, and final report.
    assert recorded.count("report") == 3
    assert recorded[recorded.index("cleanup") - 1] == "report"


@pytest.mark.parametrize("mode", ["run", "scenario"])
@pytest.mark.parametrize("failure_step,expected_status", [("setup", 23), ("eval", 42)])
def test_failed_scenario_allows_later_scenarios_and_report(
    workspace, mode, failure_step, expected_status
):
    (workspace / "evals/system-ols-agentic.yaml").write_text(yaml.safe_dump({
        "agents": {
            "default": {"repeat": 1},
            "test-agent": {"description": "Test agent"},
        }
    }))
    for name in ("first", "second"):
        scenario = workspace / "evals/scenarios" / name
        setup_status = 23 if name == "first" and failure_step == "setup" else 0
        executable(
            scenario / "setup.sh",
            f'#!/bin/bash\necho setup:{name} >> "$EVENT_LOG"\nexit {setup_status}\n',
        )
        executable(
            scenario / "cleanup.sh",
            f'#!/bin/bash\necho cleanup:{name} >> "$EVENT_LOG"\n',
        )
        (scenario / "evals-ols-agentic.yaml").write_text("[]\n")

    executable(
        workspace / "scripts/run-agentic-evals.sh",
        '#!/bin/bash\n'
        'scenario="$(basename "$(dirname "$4")")"\n'
        'echo "eval:$scenario" >> "$EVENT_LOG"\n'
        'if [ "$scenario" = first ] && [ "$FAILURE_STEP" = eval ]; then exit 42; fi\n',
    )
    (workspace / "scripts/generate-report-agentic.py").write_text(
        'import os, sys\n'
        'with open(os.environ["EVENT_LOG"], "a") as f:\n'
        '    f.write("report\\n")\n'
        'with open(sys.argv[-1], "w") as f:\n'
        '    f.write("report\\n")\n'
    )
    log = workspace / "events"
    result = subprocess.run(
        [
            "bash", str(workspace / "scripts/eval-ols-agentic.sh"),
            "--system-config", "system-ols-agentic.yaml",
            "--setup-mode", mode, "--agents", "test-agent",
            "--tags", "alert",
            "--scenarios", "scenarios/first", "scenarios/second",
        ],
        cwd=workspace / "evals",
        env={**os.environ, "EVENT_LOG": str(log), "FAILURE_STEP": failure_step},
        capture_output=True, text=True,
    )
    assert result.returncode == expected_status, result.stdout + result.stderr
    expected_events = ["setup:first"]
    if failure_step == "eval":
        expected_events.append("eval:first")
    expected_events += [
        "cleanup:first", "setup:second", "eval:second", "cleanup:second", "report",
    ]
    recorded = log.read_text().splitlines()
    assert [event for event in recorded if event != "report"] == expected_events[:-1]
    assert recorded[0] == recorded[-1] == "report"
    # Initial report, two finished scenarios, and final report.
    assert recorded.count("report") == 4
    assert list((workspace / "evals/results").glob("*/report.md"))


@pytest.mark.parametrize("failure_step,expected_status", [("setup", 23), ("eval", 42)])
def test_classic_failed_scenario_allows_later_scenarios_and_report(
    classic_workspace, failure_step, expected_status
):
    for name in ("first", "second"):
        scenario = classic_workspace / "evals/scenarios" / name
        setup_status = 23 if name == "first" and failure_step == "setup" else 0
        executable(
            scenario / "setup.sh",
            f'#!/bin/bash\necho setup:{name} >> "$EVENT_LOG"\nexit {setup_status}\n',
        )
        executable(
            scenario / "cleanup.sh",
            f'#!/bin/bash\necho cleanup:{name} >> "$EVENT_LOG"\n',
        )
        (scenario / "evals-ols-classic.yaml").write_text("[]\n")

    executable(
        classic_workspace / "scripts/run-agentic-evals.sh",
        '#!/bin/bash\n'
        'scenario="$(basename "$(dirname "$4")")"\n'
        'echo "eval:$scenario" >> "$EVENT_LOG"\n'
        'if [ "$scenario" = first ] && [ "$FAILURE_STEP" = eval ]; then exit 42; fi\n',
    )
    log = classic_workspace / "events"
    result = subprocess.run(
        [
            "bash", str(classic_workspace / "scripts/eval-ols-classic.sh"),
            "--system-config", "system-ols-classic.yaml",
            "--tags", "alert",
            "--scenarios", "scenarios/first", "scenarios/second",
        ],
        cwd=classic_workspace / "evals",
        env={
            **os.environ,
            "PATH": f"{classic_workspace / 'bin'}:{os.environ['PATH']}",
            "EVENT_LOG": str(log),
            "FAILURE_STEP": failure_step,
        },
        capture_output=True, text=True,
    )
    assert result.returncode == expected_status, result.stdout + result.stderr
    assert "setup_mode: scenario" in result.stdout
    assert "repeats:    2" in result.stdout
    assert "agents:     1\n  test|model" in result.stdout
    assert "scenarios:  2" in result.stdout
    expected_events = ["setup:first"]
    if failure_step == "eval":
        expected_events.append("eval:first")
    expected_events += [
        "cleanup:first", "setup:second", "eval:second", "cleanup:second", "report",
    ]
    recorded = log.read_text().splitlines()
    assert [event for event in recorded if event != "report"] == expected_events[:-1]
    assert recorded[0] == recorded[-1] == "report"
    # Initial report, two finished scenarios, and final report.
    assert recorded.count("report") == 4
    assert list((classic_workspace / "evals/results").glob("*/report.md"))


@pytest.mark.parametrize("setup_mode", ["run", "auto"])
def test_classic_run_mode_sets_up_each_agent_repeat(classic_workspace, setup_mode):
    (classic_workspace / "evals/system-ols-classic.yaml").write_text(yaml.safe_dump({
        "agents": {
            "default": {"agent": ["first", "second"], "repeat": 2},
            "first": {"description": "test|first"},
            "second": {"description": "test|second"},
        },
    }))
    group = classic_workspace / "evals/scenarios/group"
    executable(group / "setup.sh", '#!/bin/bash\necho group-setup >> "$EVENT_LOG"\n')
    executable(group / "cleanup.sh", '#!/bin/bash\necho group-cleanup >> "$EVENT_LOG"\n')
    scenario = group / "first"
    executable(scenario / "setup.sh", '#!/bin/bash\necho setup >> "$EVENT_LOG"\n')
    executable(scenario / "cleanup.sh", '#!/bin/bash\necho cleanup >> "$EVENT_LOG"\n')
    (scenario / "evals-ols-classic.yaml").write_text(
        "- conversation_group_id: example\n  tag:\n    - remediation\n"
    )
    executable(
        classic_workspace / "scripts/run-agentic-evals.sh",
        '#!/bin/bash\n'
        'while [ $# -gt 0 ]; do\n'
        '  case "$1" in\n'
        '    --agent) agent="$2"; shift 2 ;;\n'
        '    --run-index) run="$2"; shift 2 ;;\n'
        '    *) shift ;;\n'
        '  esac\n'
        'done\n'
        'echo "eval:$agent:$run" >> "$EVENT_LOG"\n'
        'if [ "$agent" = first ] && [ "$run" = 1 ]; then exit 42; fi\n',
    )
    log = classic_workspace / "events"
    result = subprocess.run(
        [
            "bash", str(classic_workspace / "scripts/eval-ols-classic.sh"),
            "--system-config", "system-ols-classic.yaml",
            *(["--setup-mode", setup_mode] if setup_mode != "auto" else []),
            "--scenarios", "scenarios/group/first",
        ],
        cwd=classic_workspace / "evals",
        env={
            **os.environ,
            "PATH": f"{classic_workspace / 'bin'}:{os.environ['PATH']}",
            "EVENT_LOG": str(log),
        },
        capture_output=True, text=True,
    )
    assert result.returncode == 42, result.stdout + result.stderr
    assert "setup_mode: run" in result.stdout
    assert "repeats:    2" in result.stdout
    assert "agents:     2" in result.stdout
    assert "run 1/4" in result.stdout
    assert "run 4/4" in result.stdout
    recorded = log.read_text().splitlines()
    assert [event for event in recorded if event != "report"] == [
        "group-setup",
        "setup", "eval:first:1", "cleanup",
        "setup", "eval:first:2", "cleanup",
        "setup", "eval:second:1", "cleanup",
        "setup", "eval:second:2", "cleanup",
        "group-cleanup",
    ]
    assert recorded[0] == recorded[-1] == "report"
    # Initial report, four finished runs, and final report.
    assert recorded.count("report") == 6
    assert list((classic_workspace / "evals/results").glob("*/report.md"))


def test_classic_failed_group_setup_skips_group_and_reports_other_scenarios(
    classic_workspace,
):
    group = classic_workspace / "evals/scenarios/group"
    executable(
        group / "setup.sh",
        '#!/bin/bash\necho group-setup >> "$EVENT_LOG"\nexit 31\n',
    )
    executable(
        group / "cleanup.sh",
        '#!/bin/bash\necho group-cleanup >> "$EVENT_LOG"\n',
    )
    for name in ("group/first", "group/second", "other/third"):
        scenario = classic_workspace / "evals/scenarios" / name
        executable(
            scenario / "setup.sh",
            f'#!/bin/bash\necho setup:{name} >> "$EVENT_LOG"\n',
        )
        executable(
            scenario / "cleanup.sh",
            f'#!/bin/bash\necho cleanup:{name} >> "$EVENT_LOG"\n',
        )
        (scenario / "evals-ols-classic.yaml").write_text("[]\n")

    executable(
        classic_workspace / "scripts/run-agentic-evals.sh",
        '#!/bin/bash\necho eval >> "$EVENT_LOG"\n',
    )
    log = classic_workspace / "events"
    result = subprocess.run(
        [
            "bash", str(classic_workspace / "scripts/eval-ols-classic.sh"),
            "--system-config", "system-ols-classic.yaml",
            "--scenarios", "scenarios/group/first", "scenarios/group/second",
            "scenarios/other/third",
        ],
        cwd=classic_workspace / "evals",
        env={
            **os.environ,
            "PATH": f"{classic_workspace / 'bin'}:{os.environ['PATH']}",
            "EVENT_LOG": str(log),
        },
        capture_output=True, text=True,
    )
    assert result.returncode == 31, result.stdout + result.stderr
    recorded = log.read_text().splitlines()
    assert [event for event in recorded if event != "report"] == [
        "group-setup", "setup:other/third", "eval", "cleanup:other/third",
        "group-cleanup",
    ]
    assert recorded[0] == recorded[-1] == "report"
    # Initial report, two skipped scenarios, one finished scenario, and final report.
    assert recorded.count("report") == 5
    assert "Skipping scenarios/group/second" in result.stderr
    assert list((classic_workspace / "evals/results").glob("*/report.md"))


@pytest.fixture(params=["agentic", "classic"])
def live_report_workspace(request, classic_workspace):
    """Use the real reports with a small evaluator that needs no cluster."""
    root = classic_workspace
    service = request.param
    for name in ("generate-report-agentic.py", "generate-report-classic.py", "report_common.py", "agentic_crs.py"):
        shutil.copy(ROOT / "scripts" / name, root / "scripts" / name)
    (root / f"evals/system-ols-{service}.yaml").write_text(yaml.safe_dump({
        "agents": {"default": {"agent": ["test-agent"], "repeat": 2}},
    }))
    for name in ("first", "second", "third"):
        scenario = root / "evals/scenarios" / name
        scenario.mkdir(parents=True)
        (scenario / f"evals-ols-{service}.yaml").write_text(
            f"- conversation_group_id: {name}\n"
        )
    evaluator = root / "evaluator.py"
    evaluator.write_text('''
import json
import os
from pathlib import Path
import signal
import sys

args = sys.argv[1:]
session = Path(args[args.index("--eval-dir") + 1])
scenario = Path(args[args.index("--evals") + 1]).parent.name
progress = json.loads((session / "progress.json").read_text())
assert any(item["state"] == "running" for item in progress["items"])
report = session / "report.md"
assert report.is_file(), "Report must exist before evaluation starts"
agent = args[args.index("--agent") + 1] if "--agent" in args else "test-agent"
index = args[args.index("--run-index") + 1] if "--run-index" in args else "1"
snapshot = Path(os.environ["SNAPSHOT_DIR"], f"{scenario}-{index}.md")
if not snapshot.exists():
    snapshot.write_text(report.read_text())
if scenario == "second" and os.environ.get("INTERRUPT"):
    os.kill(os.getppid(), int(os.environ["INTERRUPT"]))
    sys.exit(0)
# The fixture config requests two repeats when no single run is selected.
indices = [index] if "--run-index" in args else ["1", "2"]
for index in indices:
    output = session / agent / f"run_{index}"
    output.mkdir(parents=True, exist_ok=True)
    summary = output / f"{scenario}_summary.json"
    if scenario == "second" and os.environ.get("BROKEN_RESULT"):
        summary.write_text("{")
    else:
        summary.write_text(json.dumps({"results": [{
            "conversation_group_id": scenario,
            "metric_identifier": os.environ["METRIC"],
            "result": "PASS" if scenario != "second" else "FAIL",
            "score": 1.0 if scenario != "second" else 0.2,
        }]}))
if scenario == "second":
    sys.exit(int(os.environ.get("EVAL_STATUS", "0")))
''')
    executable(
        root / "scripts/run-agentic-evals.sh",
        f'#!/bin/bash\nexec "{sys.executable}" "{evaluator}" "$@"\n',
    )
    snapshots = root / "snapshots"
    snapshots.mkdir()
    env = {
        **os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
        "SNAPSHOT_DIR": str(snapshots),
        "METRIC": "custom:answer_correctness" if service == "classic" else
        "custom:openshift_agentic_run_evaluation_correctness",
    }
    return root, service, env


def run_live_report(workspace, mode="skip", **extra_env):
    root, service, env = workspace
    result = subprocess.run(
        ["bash", str(root / f"scripts/eval-ols-{service}.sh"),
         "--system-config", f"system-ols-{service}.yaml", "--setup-mode", mode,
         "--scenarios", "scenarios/first", "scenarios/second", "scenarios/third"],
        cwd=root / "evals", env={**env, **extra_env}, capture_output=True, text=True,
        timeout=30,
    )
    session = next((root / "evals/results").iterdir())
    return result, session


@pytest.mark.parametrize("mode,agents", [
    ("skip", ["test-agent"]),
    ("scenario", ["test-agent"]),
    ("run", ["test-agent"]),
    ("run", ["test-agent", "other-agent"]),
])
def test_live_report_contains_partial_results_and_normal_final_report(
    live_report_workspace, mode, agents,
):
    root, service, _ = live_report_workspace
    config = root / f"evals/system-ols-{service}.yaml"
    config.write_text(yaml.safe_dump({
        "agents": {"default": {"agent": agents, "repeat": 2}},
    }))
    for name in ("first", "second", "third"):
        executable(
            root / "evals/scenarios" / name / "cleanup.sh",
            f'''#!/bin/bash
session="${{SCENARIO_STATE_DIR%/.scenario-state.*}}"
cp "$session/report.md" "$SNAPSHOT_DIR/cleanup-{name}.md"
echo "cleanup:{name}"
''',
        )
    result, session = run_live_report(live_report_workspace, mode)
    assert result.returncode == 0, result.stdout + result.stderr
    tables = result.stdout.split("| Scenario")
    if mode == "run":
        total_runs = 3 * len(agents) * 2
        assert len(tables) == total_runs + 2  # Each run, plus the final report.
        for index in range(total_runs):
            assert f"Progress: run {index + 1}/{total_runs} |" in tables[index]
    else:
        assert len(tables) == 5  # Each scenario, plus the final report.
        assert "Scenario 1/3" in tables[0]
        assert "Scenario 2/3" in tables[1]
        assert "Scenario 3/3" in tables[2]
    completed_updates = 3 * len(agents) * 2 if mode == "run" else 3
    # Initial report, completed runs, and final report; no writes at run start.
    assert result.stdout.count("Report written to ") == completed_updates + 2
    before_second = (root / "snapshots/second-1.md").read_text()
    assert "Partial results: scenario 1/3." in before_second
    assert "| Pending |" not in before_second
    assert "## Progress" not in before_second
    assert "[🟢" in before_second
    if mode != "skip":
        assert (root / "snapshots/cleanup-first.md").read_text() == before_second
        cleanup_parts = result.stdout.split("cleanup:")
        for before_cleanup in cleanup_parts[:-1]:
            assert before_cleanup.count("| Scenario") == 1
    report = (session / "report.md").read_text()
    assert "Partial results:" not in report
    assert "## Progress" not in report
    assert "[🔴" in report  # A low score is separate from an execution error.
    assert f"3 scenarios, {len(agents)} agent" in report
    assert "2 repeats" in report
    progress = json.loads((session / "progress.json").read_text())
    assert progress["state"] == "completed"
    assert all(item["state"] == "completed" for item in progress["items"])
    assert not list(session.glob(".report.md.*"))


@pytest.mark.parametrize("note", [
    "",
    "   ",
    "Budget $5; $HOME; ${HOME}; $(HOME); $$",
    "Make expression: $(shell touch memo-ran)",
    'Testing alerts without the skill.\nOwner\'s memo: "baseline"; `touch memo-ran`; $(touch memo-ran)',
])
def test_make_eval_note_survives_report_updates_and_regeneration(live_report_workspace, note):
    root, service, env = live_report_workspace
    (root / "evals/scenarios/first").rename(root / "evals/scenarios/crashlooping_pod_alert")
    result = subprocess.run(
        ["make", f"eval-ols-{service}", "SCENARIO=crashlooping_pod_alert",
         "SETUP_MODE=skip", f"NOTE={note}"],
        cwd=root, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    session = next((root / "evals/results").iterdir())
    progress = json.loads((session / "progress.json").read_text())
    assert progress.get("note", "") == note.strip()
    if note.strip():
        assert f"note:       {note.strip()}" in result.stdout
    else:
        assert "note:       " not in result.stdout
    initial = (root / "snapshots/crashlooping_pod_alert-1.md").read_text()
    final = (session / "report.md").read_text()
    if note.strip():
        for report in (initial, final):
            for line in note.strip().splitlines():
                assert report.count(line) == 1
            assert "> Note: _" in report
            first_table = next(line for line in report.splitlines() if line.startswith("|"))
            assert report.index(note.strip().splitlines()[0]) < report.index(first_table)
    else:
        assert "note" not in progress
    regenerated = subprocess.run(
        [sys.executable, str(root / f"scripts/generate-report-{service}.py"),
         str(session), "--output", str(session / "rebuilt.md")],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert regenerated.returncode == 0, regenerated.stdout + regenerated.stderr
    assert (session / "rebuilt.md").read_text() == final
    assert not list(root.rglob("memo-ran"))


def test_live_report_records_technical_errors_and_continues(live_report_workspace):
    result, session = run_live_report(live_report_workspace, EVAL_STATUS="42")
    assert result.returncode == 42, result.stdout + result.stderr
    report = (session / "report.md").read_text()
    assert "Partial results:" not in report
    assert "## Progress" not in report
    progress = json.loads((session / "progress.json").read_text())
    assert progress["state"] == "completed"
    assert [item["state"] for item in progress["items"]] == ["completed", "error", "completed"]
    assert progress["items"][1]["detail"] == "Evaluation failed (exit 42)"
    note = "- `second`: Evaluation failed (exit 42)"
    assert report.index(note) < report.index("## Correctness")


@pytest.mark.parametrize("eval_status", ["0", "42"])
def test_broken_results_keep_the_last_report(live_report_workspace, eval_status):
    root, _, _ = live_report_workspace
    result, session = run_live_report(
        live_report_workspace, BROKEN_RESULT="1", EVAL_STATUS=eval_status,
    )
    assert result.returncode == (int(eval_status) or 1), result.stdout + result.stderr
    previous = (root / "snapshots/second-1.md").read_text()
    assert (root / "snapshots/third-1.md").read_text() == previous
    assert (session / "report.md").read_text() == previous
    assert "report update failed; keeping the last report" in result.stderr
    assert json.loads((session / "progress.json").read_text())["state"] == "completed"


@pytest.mark.parametrize("signal_number,exit_code", [(2, 130), (15, 143)])
def test_interrupted_run_keeps_results_and_updates_report(
    live_report_workspace, signal_number, exit_code,
):
    root, _, _ = live_report_workspace
    result, session = run_live_report(live_report_workspace, INTERRUPT=str(signal_number))
    assert result.returncode == exit_code, result.stdout + result.stderr
    report = (session / "report.md").read_text()
    assert "Partial results: scenario 1/3." in report
    assert "## Progress" not in report
    progress = json.loads((session / "progress.json").read_text())
    assert progress["state"] == "interrupted"
    assert [item["state"] for item in progress["items"]] == ["completed", "interrupted", "pending"]
    assert "[🟢" in report
    assert not (root / "snapshots/third-1.md").exists()


@pytest.mark.parametrize("service,existing_config", [
    ("classic", False), ("classic", True), ("agentic", False), ("agentic", True),
])
@pytest.mark.parametrize("skip_install", ["0", "1"])
@pytest.mark.parametrize("server_state", ["missing", "pending", "ready"])
@pytest.mark.parametrize("rollout_status", [0, 1])
def test_setup_can_skip_operator_install(
    workspace, service, existing_config, skip_install, server_state, rollout_status,
):
    root = workspace
    for name in ("setup-ols-classic.sh", "build-ols-classic-config.py"):
        shutil.copy(ROOT / "scripts" / name, root / "scripts" / name)
    executable(root / "scripts/setup-venv.sh", "#!/bin/bash\nexit 0\n")
    config_path = root / "system.yaml"
    config_path.write_text(yaml.safe_dump({
        "agents": {
            "enabled": True,
            "default": {"agent": ["selected"]},
            "selected": {"provider": "openai", "model": "test-model",
                         "description": "openai|test-model", "agent_ref": "selected"},
        },
        "judge_panel": {"judges": ["judge"]},
        "llm_pool": {"models": {"judge": {"provider": "openai", "model": "judge-model"}}},
    }))
    executable(root / "bin/oc", f"#!{sys.executable}\n" + r'''
import json
import os
from pathlib import Path
import sys
import yaml

root = Path(os.environ["CLASSIC_SETUP_ROOT"])
args = sys.argv[1:]
with (root / "oc.log").open("a") as log:
    log.write(json.dumps(args) + "\n")
if args[0] == "apply":
    resource = yaml.safe_load(sys.stdin)
    with (root / "resources.jsonl").open("a") as log:
        log.write(json.dumps(resource) + "\n")
    if resource["kind"] == "OLSConfig":
        (root / "configured").touch()
elif args[:2] == ["create", "secret"]:
    print(yaml.safe_dump({"kind": "Secret", "metadata": {"name": args[3]}}))
elif args[:2] == ["get", "deployment"]:
    if args[2] == "lightspeed-operator-controller-manager":
        print("deployment.apps/lightspeed-operator-controller-manager")
        sys.exit(0)
    sys.exit(0 if (root / "configured").exists() or os.environ["SERVER_STATE"] != "missing" else 1)
elif args[:2] == ["get", "olsconfig"]:
    if os.environ["EXISTING_CONFIG"] == "1":
        print("olsconfig.ols.openshift.io/cluster")
elif args[:2] == ["patch", "olsconfig"]:
    assert args[2] == "cluster" and "--type=merge" in args
    patch = json.loads(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--patch=")))
    assert set(patch) == {"spec"}
    assert set(patch["spec"]) == {"llm", "ols"}
    assert set(patch["spec"]["llm"]) == {"providers"}
    assert set(patch["spec"]["ols"]) == {"defaultModel", "defaultProvider"}
    with (root / "resources.jsonl").open("a") as log:
        log.write(json.dumps({"kind": "OLSConfig", **patch}) + "\n")
    (root / "configured").touch()
elif args[:2] == ["rollout", "status"]:
    if "--timeout=10s" in args:
        sys.exit(0 if os.environ["SERVER_STATE"] == "ready" else 1)
    if args[2] != "deployment/lightspeed-operator-controller-manager":
        assert (root / "configured").exists() or os.environ["EXISTING_CONFIG"] == "1"
        sys.exit(int(os.environ["ROLLOUT_STATUS"]))
elif args[:2] == ["get", "subscription"]:
    print("test-csv")
elif args[:2] == ["get", "crd"]:
    sys.exit(0 if (root / "configured").exists() or os.environ["EXISTING_CONFIG"] == "1" else 1)
elif args[0] == "wait" and any(arg.startswith("crd/") for arg in args):
    assert (root / "configured").exists() or os.environ["EXISTING_CONFIG"] == "1"
    assert len([arg for arg in args if arg.startswith("crd/")]) == 1
elif args[0] == "explain":
    pass
elif args[0] != "wait":
    sys.exit(9)
''')
    result = subprocess.run(
        ["make", f"setup-ols-{service}", f"SKIP_OLS_INSTALL={skip_install}",
         f"SYSTEM_CONFIG_{service.upper()}={config_path}"],
        cwd=root, capture_output=True, text=True, timeout=15,
        env={**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
             "CLASSIC_SETUP_ROOT": str(root), "SERVER_STATE": server_state,
             "EXISTING_CONFIG": "1" if existing_config else "0",
             "ROLLOUT_STATUS": str(rollout_status), "EVAL_OPENAI_API_KEY": "test-key",
             "EVAL_VERTEX_CREDENTIALS": "", "EVAL_VERTEX_PROJECT_ID": ""},
    )
    assert (result.returncode == 0) == (rollout_status == 0), result.stdout + result.stderr
    resources_path = root / "resources.jsonl"
    resource_lines = resources_path.read_text().splitlines() if resources_path.exists() else []
    resources = [json.loads(line) for line in resource_lines]
    kinds = [resource["kind"] for resource in resources]
    expected = ["Secret", "OLSConfig"] if service == "classic" else [
        *([] if existing_config else ["OLSConfig"]),
        *(["Secret", "LLMProvider", "Agent"] if rollout_status == 0 else []),
    ]
    if skip_install == "0" and server_state != "ready":
        expected = ["Namespace", "OperatorGroup", "Subscription", *expected]
    assert kinds == expected
    commands = [json.loads(line) for line in (root / "oc.log").read_text().splitlines()]
    assert any(command[0] == "wait" and "subscription/lightspeed-operator" in command
               for command in commands) == ("Subscription" in kinds)
    if service == "classic":
        assert commands[-1][:2] == ["rollout", "status"]
        assert any(command[:2] == ["patch", "olsconfig"] for command in commands) == existing_config
        config = next(resource for resource in resources if resource["kind"] == "OLSConfig")
        assert config["spec"]["ols"] == {"defaultProvider": "openai", "defaultModel": "test-model"}
        assert config["spec"]["llm"]["providers"][0]["credentialsSecretRef"]["name"] == "creds-classic-openai"
    else:
        if existing_config:
            assert "OLSConfig" not in kinds
            assert "keeping Classic providers and other settings" in result.stdout
        else:
            config = next(resource for resource in resources if resource["kind"] == "OLSConfig")
            assert config["spec"]["llm"]["providers"] == []
            assert config["spec"]["agenticOLS"]["sandboxMode"] == "bare-pod"
        assert any(command[:3] == ["rollout", "status", "deployment/lightspeed-agentic-operator-controller-manager"]
                   for command in commands)
        crd_waits = [command for command in commands
                     if command[0] == "wait" and any(arg.startswith("crd/") for arg in command)]
        assert len(crd_waits) == 4
        for index, crd in enumerate(("agents", "llmproviders")):
            assert "--for=create" in crd_waits[index * 2]
            assert "--for=condition=Established" in crd_waits[index * 2 + 1]
            assert f"crd/{crd}.agentic.openshift.io" in crd_waits[index * 2]
            assert f"crd/{crd}.agentic.openshift.io" in crd_waits[index * 2 + 1]
    assert ("SKIP_OLS_INSTALL=1" in result.stdout) == (skip_install == "1")
    assert not any(command[0] == "delete" for command in commands)


@pytest.mark.parametrize("failure", [None, "discovery", "operator", "handoff"])
def test_agentic_setup_reuses_quickstart(workspace, failure):
    config_path = workspace / "system.yaml"
    config_path.write_text(yaml.safe_dump({
        "agents": {
            "enabled": True,
            "default": {"agent": ["selected"]},
            "selected": {"description": "openai|test-model", "agent_ref": "selected"},
        },
        "judge_panel": {"judges": ["judge"]},
        "llm_pool": {"models": {"judge": {"provider": "openai", "model": "judge-model"}}},
    }))
    executable(workspace / "scripts/setup-venv.sh", "#!/bin/bash\nexit 0\n")
    executable(workspace / "bin/oc", f"#!{sys.executable}\n" + r'''
import json
import os
from pathlib import Path
import sys
import yaml

args = sys.argv[1:]
failure = os.environ["SETUP_FAILURE"]
with Path(os.environ["OC_LOG"]).open("a") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["get", "deployment"]:
    if args[2] == "lightspeed-app-server":
        sys.exit(1)
    assert args[2] == "lightspeed-operator-controller-manager" and "--ignore-not-found" in args
    sys.exit(1 if failure == "discovery" else 0)
elif args[:2] == ["get", "crd"]:
    pass
elif args[:2] == ["rollout", "status"]:
    assert args[2] == "deployment/lightspeed-agentic-operator"
    sys.exit(1 if failure == "operator" else 0)
elif args[0] == "wait":
    if "configmap/lightspeed-agentic-configuration" in args:
        sys.exit(1 if failure == "handoff" else 0)
    else:
        assert len([arg for arg in args if arg.startswith("crd/")]) == 1
elif args[:2] == ["create", "secret"]:
    print(yaml.safe_dump({"kind": "Secret", "metadata": {"name": args[3]}}))
elif args[0] == "apply":
    resource = yaml.safe_load(sys.stdin)
    assert resource["kind"] in ("Secret", "LLMProvider", "Agent")
    with Path(os.environ["CR_LOG"]).open("a") as log:
        log.write(json.dumps(resource) + "\n")
else:
    sys.exit(9)
''')
    resources_path = workspace / "resources.jsonl"
    result = subprocess.run(
        ["make", "setup-ols-agentic", "SKIP_OLS_INSTALL=1",
         f"SYSTEM_CONFIG_AGENTIC={config_path}"],
        cwd=workspace, capture_output=True, text=True, timeout=15,
        env={**os.environ, "PATH": f"{workspace / 'bin'}:{os.environ['PATH']}",
             "EVAL_OPENAI_API_KEY": "test-key", "SETUP_FAILURE": failure or "",
             "CR_LOG": str(resources_path), "OC_LOG": str(workspace / "oc.log")},
    )
    assert (result.returncode == 0) == (failure is None), result.stdout + result.stderr
    if failure is None:
        resources = [json.loads(line) for line in resources_path.read_text().splitlines()]
        assert [resource["kind"] for resource in resources] == ["Secret", "LLMProvider", "Agent"]
        assert "existing Agentic quickstart" in result.stdout
    else:
        assert not resources_path.exists()
    commands = [json.loads(line) for line in (workspace / "oc.log").read_text().splitlines()]
    assert not any(command[0] == "delete" or "olsconfig" in command for command in commands)


@pytest.mark.parametrize("failure", ["crd-create", "crd-established", "schema", "operator", "config-read", "handoff"])
def test_agentic_setup_stops_when_ols_is_not_ready(workspace, failure):
    config_path = workspace / "system.yaml"
    config_path.write_text(yaml.safe_dump({
        "agents": {
            "enabled": True,
            "default": {"agent": ["selected"]},
            "selected": {"description": "openai|test-model", "agent_ref": "selected"},
        },
        "judge_panel": {"judges": ["judge"]},
        "llm_pool": {"models": {"judge": {"provider": "openai", "model": "judge-model"}}},
    }))
    executable(workspace / "scripts/setup-venv.sh", "#!/bin/bash\nexit 0\n")
    executable(workspace / "bin/oc", f"#!{sys.executable}\n" + r'''
import json
import os
from pathlib import Path
import sys
import yaml

args = sys.argv[1:]
failure = os.environ["SETUP_FAILURE"]
if args[:3] == ["get", "deployment", "lightspeed-operator-controller-manager"]:
    print("deployment.apps/lightspeed-operator-controller-manager")
if args[0] == "wait" and "crd/agents.agentic.openshift.io" in args and (
    (failure == "crd-create" and "--for=create" in args)
    or (failure == "crd-established" and "--for=condition=Established" in args)
):
    sys.exit(1)
if args[0] == "explain" and failure == "schema":
    sys.exit(1)
if args[:3] == ["rollout", "status", "deployment/lightspeed-operator-controller-manager"] and failure == "operator":
    sys.exit(1)
if args[:2] == ["get", "olsconfig"] and failure == "config-read":
    print("Error from server (Forbidden)", file=sys.stderr)
    sys.exit(1)
if args[0] == "wait" and "configmap/lightspeed-agentic-configuration" in args and failure == "handoff":
    sys.exit(1)
if args[0] == "apply":
    resource = yaml.safe_load(sys.stdin)
    with Path(os.environ["CR_LOG"]).open("a") as log:
        log.write(json.dumps(resource) + "\n")
''')
    resources_path = workspace / "resources.jsonl"
    result = subprocess.run(
        ["make", "setup-ols-agentic", "SKIP_OLS_INSTALL=1",
         f"SYSTEM_CONFIG_AGENTIC={config_path}"],
        cwd=workspace, capture_output=True, text=True, timeout=15,
        env={**os.environ, "PATH": f"{workspace / 'bin'}:{os.environ['PATH']}",
             "EVAL_OPENAI_API_KEY": "test-key", "SETUP_FAILURE": failure,
             "CR_LOG": str(resources_path)},
    )
    assert result.returncode != 0
    if failure in ("crd-create", "crd-established", "handoff"):
        resources = [json.loads(line) for line in resources_path.read_text().splitlines()]
        assert [resource["kind"] for resource in resources] == ["OLSConfig"]
    else:
        assert not resources_path.exists()
        if failure != "operator":
            assert ("Forbidden" if failure == "config-read" else "ERROR:") in result.stderr


@pytest.mark.parametrize("variant", ["classic", "agentic"])
def test_setup_dependencies(variant):
    result = subprocess.run(
        ["make", "--dry-run", f"setup-ols-{variant}"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert result.stdout.count("setup-venv.sh") == 1
    assert ("sync-agent-crs.py" in result.stdout) == (variant == "agentic")
    assert ("setup-ols-classic.sh" in result.stdout) == (variant == "classic")


@pytest.mark.parametrize("agent", [None, "invalid"])
@pytest.mark.parametrize("active_subset", [False, True])
def test_ci_agent_provisioning(workspace, agent, active_subset):
    config_path = workspace / "evals/system-ols-agentic.yaml"
    system_config = yaml.safe_load(config_path.read_text())
    if active_subset:
        system_config["agents"]["default"]["agent"] = ["openai-gpt-6-luna"]
    else:
        system_config["agents"]["default"]["agent"] = [
            name for name, config in system_config["agents"].items()
            if isinstance(config, dict) and "agent_ref" in config
        ]
    config_path.write_text(yaml.safe_dump(system_config))
    bin_dir = workspace / "bin"
    executable(
        bin_dir / "oc",
        f"#!{sys.executable}\n"
        "import os, sys, yaml, json\n"
        "if sys.argv[1] == 'apply':\n"
        "    state_path = os.environ['CR_STATE']\n"
        "    try:\n"
        "        with open(state_path) as f: resources = json.load(f)\n"
        "    except FileNotFoundError:\n"
        "        resources = []\n"
        "    with open(os.environ['CR_LOG'], 'a') as f:\n"
        "        for doc in yaml.safe_load_all(sys.stdin):\n"
        "            if doc:\n"
        "                f.write(json.dumps(doc) + '\\n')\n"
        "                resources = [r for r in resources if not (\n"
        "                    r.get('kind') == doc.get('kind') and\n"
        "                    r.get('metadata', {}).get('name') == doc.get('metadata', {}).get('name') and\n"
        "                    r.get('metadata', {}).get('namespace') == doc.get('metadata', {}).get('namespace')\n"
        "                )]\n"
        "                resources.append(doc)\n"
        "    with open(state_path, 'w') as f: json.dump(resources, f)\n"
        "elif sys.argv[1] == 'get':\n"
        "    try:\n"
        "        with open(os.environ['CR_STATE']) as f: resources = json.load(f)\n"
        "    except FileNotFoundError:\n"
        "        resources = []\n"
        "    print(json.dumps({'items': [r for r in resources if r.get('kind') == 'Agent']}))\n",
    )
    executable(
        workspace / "scripts/setup-venv.sh", "#!/bin/bash\nexit 0\n"
    )
    executable(
        bin_dir / "make",
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$MAKE_LOG"\n'
        'if [ "$1" = setup-ols-agentic ]; then\n'
        f'  exec "{shutil.which("make")}" "$@"\n'
        'fi\n',
    )
    credentials = workspace / "credentials.json"
    credentials.write_text('{"project_id": "test-project"}')
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "EVAL_OPENAI_API_KEY": "test-key",
        "EVAL_VERTEX_CREDENTIALS": str(credentials),
        "EVAL_VERTEX_PROJECT_ID": "test-project",
        "ARTIFACT_DIR": str(workspace / "artifacts"),
        "SYSTEM_CONFIG": str(config_path),
        "MAKE_LOG": str(workspace / "make.log"),
        "CR_LOG": str(workspace / "cr.log"),
        "CR_STATE": str(workspace / "cr-state.json"),
    }
    env.pop("AGENT", None)
    if agent is not None:
        env["AGENT"] = agent
    result = subprocess.run(
        ["bash", str(workspace / "scripts/ci-ols-agentic-evals.sh")],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    resources = [json.loads(line) for line in (workspace / "cr.log").read_text().splitlines()]
    providers = [r for r in resources if r["kind"] == "LLMProvider"]
    expected_providers = ["openai"] if active_subset else [
        "openai", "vertex-google", "vertex-anthropic",
    ]
    assert [r["metadata"]["name"] for r in providers] == expected_providers
    for resource in providers[1:]:
        vertex = resource["spec"]["googleCloudVertex"]
        assert vertex["region"] == "global"
        assert vertex["projectID"] == "test-project"
    agents = [r for r in resources if r["kind"] == "Agent"]
    defaults = system_config["agents"]["default"]["agent"]
    assert {r["metadata"]["name"] for r in agents} == {
        system_config["agents"][name]["agent_ref"] for name in defaults
    }
    for name in defaults:
        config = system_config["agents"][name]
        provider, model = config["description"].split("|", 1)
        agent_cr = next(
            r for r in agents if r["metadata"]["name"] == config["agent_ref"]
        )
        assert agent_cr["spec"]["llmProvider"]["name"] == provider
        assert agent_cr["spec"]["model"] == model
    commands = (workspace / "make.log").read_text().splitlines()
    assert commands == [
        "setup-ols-agentic", "eval-ols-agentic TAG=core", "cleanup-ols-agentic",
    ]


@pytest.mark.parametrize("provider", ["openai", "vertex-google", "vertex-anthropic"])
@pytest.mark.parametrize("judge_provider", ["openai", "google", "anthropic"])
@pytest.mark.parametrize("credentials_present", [False, True])
def test_agentic_setup_uses_selected_config(workspace, provider, judge_provider, credentials_present):
    config_path = workspace / "custom-system.yaml"
    config_path.write_text(yaml.safe_dump({
        "judge_panel": {"judges": ["judge"]},
        "llm_pool": {"models": {
            "judge": {"provider": judge_provider, "model": "judge-model"},
            "unused": {"provider": "google", "model": "unused-model"},
        }},
        "agents": {
            "enabled": True,
            "default": {"agent": ["selected"]},
            "selected": {"description": f"{provider}|test-model", "agent_ref": "selected"},
        },
    }))
    executable(workspace / "scripts/setup-venv.sh", "#!/bin/bash\nexit 0\n")
    executable(workspace / "bin/oc", f"#!{sys.executable}\n" + '''
import json
import os
import sys
import yaml

with open(os.environ["OC_LOG"], "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1] == "apply":
    with open(os.environ["CR_LOG"], "a") as log:
        for resource in yaml.safe_load_all(sys.stdin):
            if resource:
                log.write(json.dumps(resource) + "\\n")
''')
    credentials = workspace / "credentials.json"
    credentials.write_text("{}")
    env = {
        **os.environ,
        "PATH": f"{workspace / 'bin'}:{os.environ['PATH']}",
        "EVAL_OPENAI_API_KEY": "test-key",
        "SKIP_OLS_INSTALL": "1",
        "EVAL_VERTEX_CREDENTIALS": str(credentials) if credentials_present else "",
        "EVAL_VERTEX_PROJECT_ID": "test-project" if credentials_present else "",
        "OC_LOG": str(workspace / "oc.log"),
        "CR_LOG": str(workspace / "cr.log"),
    }
    result = subprocess.run(
        ["make", "setup-ols-agentic", f"SYSTEM_CONFIG_AGENTIC={config_path}"],
        cwd=workspace, env=env, capture_output=True, text=True,
    )
    judge_cr_provider = {"google": "vertex-google", "anthropic": "vertex-anthropic"}.get(
        judge_provider, judge_provider,
    )
    expected_providers = list(dict.fromkeys([judge_cr_provider, provider]))
    if any(name != "openai" for name in expected_providers) and not credentials_present:
        assert result.returncode != 0
        assert "EVAL_VERTEX_CREDENTIALS" in result.stderr
        assert not (workspace / "oc.log").exists()
        return
    assert result.returncode == 0, result.stdout + result.stderr
    resources = [json.loads(line) for line in (workspace / "cr.log").read_text().splitlines()]
    assert [r["metadata"]["name"] for r in resources if r["kind"] == "LLMProvider"] == expected_providers
    assert [r["metadata"]["name"] for r in resources if r["kind"] == "Agent"] == ["selected"]


def install_classic_log_server(root):
    """Give the Classic runner a small app-server log source."""
    executable(root / "bin/oc", f"#!{sys.executable}\n" + r'''
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["SNAPSHOT_DIR"]).parent
args = sys.argv[1:]
if args[0] == "whoami":
    print("test-token")
elif args[:2] == ["get", "pods"]:
    name = (root / "server-name").read_text().strip() if (root / "server-name").exists() else "server-old"
    print(json.dumps({"items": [{"metadata": {"name": name, "uid": name + "-uid"},
          "status": {"containerStatuses": [{"name": "lightspeed-service-api", "restartCount": 0}]}}]}))
elif args[0] == "get":
    print('{"items": []}')
elif args[0] == "logs":
    name = args[args.index("-n") + 2]
    with (root / "events").open("a") as output:
        output.write("capture:" + name + "\n")
    if os.environ.get("LOG_CAPTURE_FAIL"):
        print("app-server logs forbidden", file=sys.stderr)
        sys.exit(13)
    path = root / (name + ".log")
    if path.exists():
        print(path.read_text(), end="")
''')
    evaluator = root / "evaluator.py"
    text = evaluator.read_text()
    marker = 'index = args[args.index("--run-index") + 1] if "--run-index" in args else "1"'
    text = text.replace(marker, marker + '''
from datetime import datetime, timezone
root = Path(os.environ["SNAPSHOT_DIR"]).parent
name = (root / "server-name").read_text().strip() if (root / "server-name").exists() else "server-old"
with (root / (name + ".log")).open("a") as output:
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    output.write(f"{stamp} eval:{scenario}:{agent}:run_{index}\\n")
''')
    evaluator.write_text(text)


@pytest.mark.parametrize("live_report_workspace", ["classic"], indirect=True)
@pytest.mark.parametrize("extra_env,exit_code", [
    ({}, 0), ({"EVAL_STATUS": "42"}, 42),
    ({"INTERRUPT": "2"}, 130), ({"INTERRUPT": "15"}, 143),
])
@pytest.mark.parametrize("capture_failure", [False, True])
def test_classic_logs_saved_on_success_failure_and_interrupt(
    live_report_workspace, extra_env, exit_code, capture_failure,
):
    root, _, _ = live_report_workspace
    install_classic_log_server(root)
    result, session = run_live_report(
        live_report_workspace, **extra_env,
        LOG_CAPTURE_FAIL="1" if capture_failure else "",
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert (session / "capture-logs.log").exists()
    assert (session / "report.md").exists()
    for repeat in (1, 2):
        first = (session / f"logs/first/test-agent-run_{repeat}.log").read_text()
        second = (session / f"logs/second/test-agent-run_{repeat}.log").read_text()
        assert "Shared scenario window" in first
        if capture_failure:
            assert "eval:" not in first
            assert "app-server log capture failed" in result.stderr
            assert "app-server logs forbidden" in (session / "capture-logs.log").read_text()
        else:
            assert first.count("] eval:first:test-agent:run_1\n") == 1
            assert "] eval:second:" not in first
            assert second.count("] eval:second:test-agent:run_1\n") == 1
            assert "] eval:first:" not in second


@pytest.mark.parametrize("live_report_workspace", ["classic"], indirect=True)
def test_classic_run_mode_names_each_agent_repeat(live_report_workspace):
    root, _, _ = live_report_workspace
    install_classic_log_server(root)
    config = root / "evals/system-ols-classic.yaml"
    config.write_text(yaml.safe_dump({
        "agents": {"default": {"agent": ["test-agent", "other-agent"], "repeat": 2}},
    }))
    result, session = run_live_report(live_report_workspace, mode="run")
    assert result.returncode == 0, result.stdout + result.stderr
    for scenario in ("first", "second", "third"):
        for agent in ("test-agent", "other-agent"):
            for repeat in (1, 2):
                path = session / f"logs/{scenario}/{agent}-run_{repeat}.log"
                text = path.read_text()
                assert "Shared scenario window" not in text
                assert text.count("] eval:") == 1
                assert f"] eval:{scenario}:{agent}:run_{repeat}\n" in text


@pytest.mark.parametrize("live_report_workspace", ["classic"], indirect=True)
def test_classic_captures_before_group_rollouts(live_report_workspace):
    root, _, env = live_report_workspace
    install_classic_log_server(root)
    group = root / "evals/scenarios/group"
    group.mkdir()
    for name in ("first", "second"):
        shutil.move(root / "evals/scenarios" / name, group / name)
    executable(group / "setup.sh", '''#!/bin/bash
echo group-setup >> "$EVENT_LOG"
echo server-new > "$TEST_ROOT/server-name"
''')
    executable(group / "cleanup.sh", '''#!/bin/bash
echo group-cleanup >> "$EVENT_LOG"
rm "$TEST_ROOT/server-new.log"
echo server-after-cleanup > "$TEST_ROOT/server-name"
''')
    result = subprocess.run(
        ["bash", str(root / "scripts/eval-ols-classic.sh"),
         "--system-config", "system-ols-classic.yaml", "--setup-mode", "scenario",
         "--scenarios", "scenarios/group/first", "scenarios/group/second"],
        cwd=root / "evals", capture_output=True, text=True, timeout=30,
        env={**env, "TEST_ROOT": str(root), "EVENT_LOG": str(root / "events")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    session = next((root / "evals/results").iterdir())
    events = (root / "events").read_text().splitlines()
    assert events.index("capture:server-old") < events.index("group-setup")
    assert events[events.index("group-cleanup") - 1] == "capture:server-new"
    assert events.index("capture:server-after-cleanup") > events.index("group-cleanup")
    for scenario in ("first", "second"):
        text = (session / f"logs/group/{scenario}/test-agent-run_1.log").read_text()
        assert text.count(f"] eval:{scenario}:test-agent:run_1\n") == 1
