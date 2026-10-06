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
    for name in (
        "eval-ols-agentic.sh", "ci-ols-agentic-evals.sh", "sync-agent-crs.py",
        "setup-ols-agentic.sh",
        "show-eval-summary.py", "show-eval-summary.sh",
        "eval-report.sh", "report_progress.py",
    ):
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    executable(scripts / "preflight.sh", "#!/bin/bash\nexit 0\n")
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
def test_preview_summary_matches_real_run(request, mode):
    root = request.getfixturevalue("classic_workspace" if mode == "classic" else "workspace")
    config_path = root / "evals" / f"system-ols-{mode}.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["agents"]["default"]["parallel"] = True
    config_path.write_text(yaml.safe_dump(config))
    scenario_name = "crashlooping_pod_alert"
    scenario = root / "evals/scenarios" / scenario_name
    scenario.mkdir(parents=True)
    (scenario / f"evals-ols-{mode}.yaml").write_text("[]\n")
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
         "SETUP_MODE=run", "PREVIEW=1"],
        cwd=root, env=env, capture_output=True, text=True,
    )
    runner = subprocess.run(
        ["bash", str(root / "scripts" / f"eval-ols-{mode}.sh"),
         "--system-config", f"system-ols-{mode}.yaml", "--setup-mode", "run",
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
    assert "setup_mode: run" in preview.stdout
    assert "parallel:   false" in preview.stdout
    assert "scenarios:  1\n  crashlooping_pod_alert" in preview.stdout
    snapshots = list((root / "evals/results").glob(f"*/system-ols-{mode}.yaml"))
    assert len(snapshots) == 1
    assert snapshots[0].read_text() == config_path.read_text()


@pytest.mark.parametrize("mode", ["agentic", "classic"])
@pytest.mark.parametrize("setup_mode", ["run", "scenario", "skip"])
def test_eval_uses_saved_definitions(request, mode, setup_mode):
    root = request.getfixturevalue("classic_workspace" if mode == "classic" else "workspace")
    filename = f"evals-ols-{mode}.yaml"
    names = ["first", "group/first"]
    originals = {}
    for name in names:
        scenario = root / "evals/scenarios" / name
        scenario.mkdir(parents=True)
        content = f"- conversation_group_id: {name.replace('/', '_')}\n"
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
    repeats = len(defaults["agent"]) * defaults["repeat"] if setup_mode == "run" else 1
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
        ["make", f"eval-ols-{mode}", "SCENARIO=crashlooping_pod_alert", "PREVIEW=1"],
        cwd=root,
        env={**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "setup_mode: scenario" in result.stdout
    assert "repeats:    (Python 3 and PyYAML needed for details)" in result.stdout
    assert "agents:     (Python 3 and PyYAML needed for details)" in result.stdout
    assert "scenarios:  1\n  crashlooping_pod_alert" in result.stdout


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
    assert recorded.count("report") == 4


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
    assert recorded.count("report") == 6
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
    assert recorded.count("report") == 6
    assert list((classic_workspace / "evals/results").glob("*/report.md"))


def test_classic_run_mode_sets_up_each_agent_repeat(classic_workspace):
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
    (scenario / "evals-ols-classic.yaml").write_text("[]\n")
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
            "--setup-mode", "run",
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
    assert recorded.count("report") == 10
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
    assert recorded.count("report") == 6
    assert "Skipping scenarios/group/second" in result.stderr
    assert list((classic_workspace / "evals/results").glob("*/report.md"))


@pytest.fixture(params=["agentic", "classic"])
def live_report_workspace(request, classic_workspace):
    """Use the real reports with a small evaluator that needs no cluster."""
    root = classic_workspace
    service = request.param
    for name in ("generate-report-agentic.py", "generate-report-classic.py", "report_common.py"):
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
report = session / "report.md"
assert report.is_file(), "Report must exist before evaluation starts"
agent = args[args.index("--agent") + 1] if "--agent" in args else "test-agent"
index = args[args.index("--run-index") + 1] if "--run-index" in args else "1"
Path(os.environ["SNAPSHOT_DIR"], f"{scenario}-{index}.md").write_text(report.read_text())
if scenario == "second" and os.environ.get("INTERRUPT"):
    os.kill(os.getppid(), int(os.environ["INTERRUPT"]))
    sys.exit(0)
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


@pytest.mark.parametrize("mode", ["skip", "scenario", "run"])
def test_live_report_contains_partial_results_and_normal_final_report(live_report_workspace, mode):
    root, _, _ = live_report_workspace
    result, session = run_live_report(live_report_workspace, mode)
    assert result.returncode == 0, result.stdout + result.stderr
    tables = result.stdout.split("| Scenario")
    assert len(tables) == 5  # One table per scenario, plus the final report.
    if mode == "run":
        assert "Progress: run 2/6" in tables[0]
        assert "Progress: run 3/6" in tables[1]
        assert "Progress: run 4/6" in tables[1]
        assert "Progress: run 5/6" in tables[2]
        assert "Progress: run 6/6" in tables[2]
    else:
        assert "Scenario 1/3" in tables[0]
        assert "Scenario 2/3" in tables[1]
        assert "Scenario 3/3" in tables[2]
    before_second = (root / "snapshots/second-1.md").read_text()
    assert "Partial results: scenario 1/3." in before_second
    assert "| Pending |" not in before_second
    assert "## Progress" not in before_second
    assert "[🟢" in before_second
    report = (session / "report.md").read_text()
    assert "Partial results:" not in report
    assert "## Progress" not in report
    assert "[🔴" in report  # A low score is separate from an execution error.
    repeats = 2 if mode == "run" else 1
    assert f"3 scenarios, 1 agent, {repeats} repeat" in report
    progress = json.loads((session / "progress.json").read_text())
    assert progress["state"] == "completed"
    assert all(item["state"] == "completed" for item in progress["items"])
    assert not list(session.glob(".report.md.*"))


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
        system_config["agents"]["default"]["agent"] = (
            system_config["agents"]["default"]["agent"][:1]
        )
        config_path.write_text(yaml.safe_dump(system_config))
    bin_dir = workspace / "bin"
    executable(
        bin_dir / "git",
        '#!/bin/bash\nmkdir -p "${@: -1}/hack/quickstart"\n'
        'touch "${@: -1}/hack/quickstart/install.sh"\n',
    )
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
    assert [r["metadata"]["name"] for r in providers] == [
        "openai", "vertex-google", "vertex-anthropic",
    ]
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
