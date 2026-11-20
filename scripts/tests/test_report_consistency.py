"""Check the shared scoring rules in both report generators."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture(params=["chat", "agentic"])
def report_module(request):
    path = Path(__file__).resolve().parent.parent / f"generate-report-{request.param}.py"
    spec = importlib.util.spec_from_file_location(f"report_{request.param}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metric(module, result, score, cid="scenario"):
    return {
        "conversation_group_id": cid,
        "metric_identifier": module.CORRECTNESS_METRIC,
        "result": result,
        "score": score,
    }


def test_errors_and_missing_runs_keep_the_planned_denominator(report_module):
    mod = report_module
    runs = [
        [metric(mod, "PASS", 0.8), metric(mod, "ERROR", None, "other")],
        [metric(mod, "ERROR", None)],
        None,
    ]
    assert mod.overall_score(runs, ["scenario"]) == (1, 3)
    assert mod.scenario_mean_score(runs, "scenario") == pytest.approx(0.8)
    assert mod.mean_score(runs, ["scenario"]) == pytest.approx(0.8)
    assert mod.score_cell(runs, "scenario", "agent") == "[⚠️ 1/3](#agent--scenario) (0.80)"


def test_all_errors_have_no_score(report_module):
    mod = report_module
    runs = [[metric(mod, "ERROR", 0.9)], [metric(mod, "ERROR", None)]]
    assert mod.overall_score(runs, ["scenario"]) == (0, 2)
    assert mod.mean_score(runs, ["scenario"]) is None
    assert mod.score_cell(runs, "scenario", "agent") == "[⚠️ 0/2](#agent--scenario)"


def test_missing_results_are_unavailable(report_module):
    mod = report_module
    runs = [None, []]
    assert mod.overall_score(runs, ["scenario"]) == (0, 2)
    assert mod.mean_score(runs, ["scenario"]) is None
    assert mod.score_cell(runs, "scenario", "agent") == "[⚠️ 0/2](#agent--scenario)"


def test_failed_completion_overrides_passing_correctness(report_module):
    mod = report_module
    status = metric(mod, "FAIL", 0.0)
    status["metric_identifier"] = "custom:openshift_agentic_run_status"
    runs = [[metric(mod, "PASS", 1.0), status]]
    assert mod.overall_score(runs, ["scenario"]) == (0, 1)
    assert mod.mean_score(runs, ["scenario"]) == 1.0


def test_model_order_follows_config(report_module, tmp_path):
    for name in ("alpha", "beta", "gamma", "extra"):
        (tmp_path / name / "run_1").mkdir(parents=True)
    config = tmp_path / "system.yaml"
    config.write_text("agents:\n  default:\n    agent: [gamma, missing, beta, gamma]\n")
    assert report_module.discover_agents(tmp_path, config) == [
        "gamma", "beta", "alpha", "extra",
    ]


def test_model_order_without_config_is_alphabetical(report_module, tmp_path):
    for name in ("beta", "alpha"):
        (tmp_path / name / "run_1").mkdir(parents=True)
    assert report_module.discover_agents(tmp_path, tmp_path / "missing.yaml") == [
        "alpha", "beta",
    ]


@pytest.mark.parametrize("timestamp", ["2026-10-27T10:00:00", ""])
def test_timestamp_lookup_checks_later_summaries(report_module, tmp_path, timestamp):
    run = tmp_path / "agent" / "run_1"
    run.mkdir(parents=True)
    (run / "a_summary.json").write_text("{}")
    (run / "b_summary.json").write_text(json.dumps({"timestamp": timestamp}))
    expected = "2026-10-27 10:00:00 UTC" if timestamp else ""
    assert report_module.extract_report_timestamp(tmp_path, ["agent"]) == expected


def test_score_medals_use_displayed_precision(report_module):
    mod = report_module
    runs = {
        name: [[metric(mod, "PASS", score)]]
        for name, score in (("first", 0.993), ("tied", 0.992), ("lower", 0.984))
    }
    names = list(runs)
    summary = mod.generate_summary_table(["scenario"], names, runs)
    average = next(line for line in summary.splitlines() if line.startswith("| **Avg score** |"))
    assert average == "| **Avg score** | **0.99 (1/1)** 🥇 | **0.99 (1/1)** 🥇 | 0.98 (1/1) |"
    scenario = next(line for line in summary.splitlines() if line.startswith("| [scenario]"))
    assert scenario.count("🥇") == 2
    overview = mod.generate_overview_table(["scenario"], names, runs, {name: [] for name in names})
    assert "| Avg score | **0.99 (1/1)** 🥇 | **0.99 (1/1)** 🥇 | 0.98 (1/1) |" in overview


@pytest.mark.parametrize("note,expected", [
    ("test logs", "> Note: _test logs_"),
    ("first line\nlast line", "> Note: _first line\n> last line_"),
    ("first line\n\nlast line", "> Note: _first line_\n> \n> _last line_"),
    ("first line\n \t\n\nlast line", "> Note: _first line_\n> \n> _last line_"),
])
def test_report_formats_note_as_italic_block_quote(report_module, tmp_path, note, expected):
    (tmp_path / "progress.json").write_text(json.dumps({
        "state": "completed", "scenarios": [], "items": [], "note": note,
    }))
    report = report_module.generate_report(tmp_path)
    assert report.count(expected) == 1
    assert report.index(expected) < report.index("| Avg duration")


def test_report_includes_saved_yaml_and_header_link(report_module, tmp_path):
    kind = Path(report_module.__file__).stem.removeprefix("generate-report-")
    content = "# Saved config, including a ``` fence\nagents:\n  default:\n    repeat: 7\n"
    (tmp_path / f"system-ols-{kind}.yaml").write_text(content)
    report = report_module.generate_report(tmp_path)
    assert "[System config](#system-config)" in report.splitlines()[2]
    assert '<a id="system-config"></a>' in report
    assert "````yaml\n" + content + "````" in report
    assert report.index("## Appendix: System config") > report.index("# Scenarios")


def test_report_does_not_use_current_yaml_for_old_sessions(report_module, tmp_path):
    report = report_module.generate_report(tmp_path)
    assert "The original YAML was not saved for this session." in report
    assert "```yaml" not in report


def test_failed_report_replace_keeps_previous_file(report_module, tmp_path, monkeypatch):
    output = tmp_path / "report.md"
    output.write_text("Previous report\n")

    def fail_replace(self, target):
        raise OSError("Cannot replace report")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="Cannot replace report"):
        report_module.write_atomic(output, "New report\n")
    assert output.read_text() == "Previous report\n"
    assert not list(tmp_path.glob(".report.md.*"))


def test_scenario_names_use_directory_paths(report_module, tmp_path):
    filename = "evals-ols-chat.yaml"
    for directory, cid in (
        ("kiali-ossm/check_mesh_status", "check_mesh_status"),
        ("crashlooping_pod_alert", "crashlooping_pod"),
        ("first", "shared_id"),
        ("second", "shared_id"),
    ):
        path = tmp_path / directory / filename
        path.parent.mkdir(parents=True)
        path.write_text(f"- conversation_group_id: {cid}\n")
    (tmp_path / "first/evals-ols-agentic.yaml").write_text(
        "- conversation_group_id: check_mesh_status\n"
    )

    assert report_module.load_scenario_names(filename, tmp_path) == {
        "check_mesh_status": "kiali-ossm/check_mesh_status",
        "crashlooping_pod": "crashlooping_pod_alert",
    }


def test_directory_labels_keep_scores_and_links(
    report_module, tmp_path, monkeypatch, capsys,
):
    mod = report_module
    names = {"mesh_check": "kiali-ossm/check_mesh_status"}
    monkeypatch.setattr(mod, "load_scenario_names", lambda filename: names)
    results = [metric(mod, "PASS", 0.9, "mesh_check"), metric(mod, "FAIL", 0.2, "old_id")]
    for run in (1, 2):
        run_dir = tmp_path / f"agent/run_{run}"
        run_dir.mkdir(parents=True)
        (run_dir / "evaluation_summary.json").write_text(json.dumps({"results": results}))

    report = mod.generate_report(tmp_path)

    assert report.count("| [kiali-ossm/check_mesh_status](#mesh_check) |") == (4 if hasattr(mod, "generate_phase_breakdown_table") else 3)
    assert '<a id="mesh_check"></a>\n\n## kiali-ossm/check_mesh_status' in report
    assert '<a id="agent--mesh_check"></a>' in report
    assert "[🟢 2/2](#agent--mesh_check) (0.90)" in report
    assert "50% (2/4)" in report
    assert report.count("| [old_id](#old_id) |") == (4 if hasattr(mod, "generate_phase_breakdown_table") else 3)
    assert "## old_id\n" in report

    mod.print_correctness_table(
        ["mesh_check", "old_id"], ["agent"], {"agent": [results]}, scenario_names=names,
    )
    output = capsys.readouterr().out
    assert "kiali-ossm/check_mesh_status" in output
    assert "old_id" in output
    assert "50% (" in output
    # The longer directory label must fit in the CLI table.
    rows = [line for line in output.splitlines() if line.startswith("|")]
    assert len({line.index("|", 1) for line in rows}) == 1

    if hasattr(mod, "generate_phase_breakdown_table"):
        phases = mod.generate_phase_breakdown_table(
            ["mesh_check"], ["agent"], {"agent": [[]]}, scenario_names=names,
        )
        assert "| [kiali-ossm/check_mesh_status](#mesh_check) |" in phases


@pytest.mark.parametrize("state", ["running", "interrupted", "failed", "completed"])
def test_progress_includes_planned_scenarios_and_partial_results_line(report_module, tmp_path, state):
    progress = {
        "state": state,
        "scenarios": ["first", "second", "third"],
        "items": [
            {"scenario": "first", "state": "completed"},
            {"scenario": "first", "state": "error"},
            {"scenario": "second", "state": "completed"},
            {"scenario": "second", "state": "completed"},
            {"scenario": "third", "state": "completed"},
            {"scenario": "third", "state": "interrupted"},
        ],
    }
    (tmp_path / "progress.json").write_text(json.dumps(progress))
    report = report_module.generate_report(tmp_path)
    line = "Partial results: scenario 2/3."
    assert "3 scenarios" in report
    for name in progress["scenarios"]:
        assert f"| [{name}](#{name}) |" in report
    assert report.count(line) == (0 if state == "completed" else 1)


@pytest.mark.parametrize("results,expected,color", [
    (["ERROR"], "0/1", "YELLOW"),
    (["PASS", "ERROR"], "1/2", "YELLOW"),
    (["FAIL", "ERROR"], "0/2", "YELLOW"),
    (["PASS", "FAIL"], "1/2", None),
    (["PASS", "FAIL", "FAIL"], "1/3", None),
    (["PASS", "FAIL", "ERROR"], "1/3", "YELLOW"),
    (["PASS", "ERROR", "ERROR"], "1/3", "YELLOW"),
    (["PASS"], "1/1", "GREEN"),
    (["FAIL"], "0/1", "RED"),
])
@pytest.mark.parametrize("is_tty", [True, False])
def test_cli_cell_colors_match_markdown(
    report_module, capsys, monkeypatch, results, expected, color, is_tty,
):
    mod = report_module
    monkeypatch.setattr(mod.sys.stdout, "isatty", lambda: is_tty)
    runs = [[metric(mod, result, 1.0 if result == "PASS" else 0.0)] for result in results]
    mod.print_correctness_table(["scenario"], ["agent"], {"agent": runs})
    output = capsys.readouterr().out
    average = next(line for line in output.splitlines() if line.startswith("| Avg score"))
    if all(result == "ERROR" for result in results):
        assert f"N/A (0/{len(results)})" in average
        assert "\033[" not in average
    row = next(line for line in output.splitlines() if line.startswith("| scenario"))
    if is_tty and color:
        assert getattr(mod, color) + expected + mod.RESET in row
    else:
        marker = "*" if color == "YELLOW" and not is_tty else ""
        assert row.split("|")[2].strip() == expected + marker
        assert "\033[" not in row
    if not is_tty:
        assert "\033[" not in output
        rows = [line for line in output.splitlines() if line.startswith("|")]
        assert len({len(line) for line in rows}) == 1
    assert ("⚠️" in mod.score_cell(runs, "scenario", "agent")) == (color == "YELLOW")


@pytest.mark.parametrize("is_tty", [True, False])
def test_cli_failed_completion_is_marked_and_counts_as_failed(
    report_module, capsys, monkeypatch, is_tty,
):
    mod = report_module
    monkeypatch.setattr(mod.sys.stdout, "isatty", lambda: is_tty)
    runs = [[metric(mod, "PASS", 1.0), {
        "conversation_group_id": "scenario",
        "metric_identifier": "custom:openshift_agentic_run_status",
        "result": "FAIL",
    }]]
    mod.print_correctness_table(["scenario"], ["agent"], {"agent": runs})
    row = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("| scenario"))
    if is_tty:
        assert mod.YELLOW + "0/1" + mod.RESET in row
    else:
        assert row.split("|")[2].strip() == "0/1*"
        assert "\033[" not in row
    assert "⚠️" in mod.score_cell(runs, "scenario", "agent")


@pytest.mark.parametrize("states,failed", [
    (["error", "error"], True),
    (["skipped", "skipped"], True),
    (["error", "completed"], False),
    (["error", "pending"], False),
    (["interrupted", "interrupted"], False),
])
def test_fully_failed_scenarios_appear_before_correctness(report_module, tmp_path, states, failed):
    normal = report_module.generate_report(tmp_path)
    progress = {
        "state": "completed",
        "items": [{
            "scenario": "scenarios/restarting_pod_alert", "state": state,
            "detail": "Setup failed (exit 1)",
        } for state in states],
    }
    (tmp_path / "progress.json").write_text(json.dumps(progress))
    report = report_module.generate_report(tmp_path)
    note = "**Scenarios that failed completely:**\n\n- `restarting_pod_alert`: Setup failed (exit 1)"
    if failed:
        assert report.count(note) == 1
        assert report.index(note) < report.index("## Time" if hasattr(report_module, "scored_conversations") else "## Correctness")
        assert report.replace(note + "\n\n", "") == normal
    else:
        assert report == normal


def test_report_agent_order_uses_saved_session_config(report_module, tmp_path):
    kind = Path(report_module.__file__).stem.removeprefix("generate-report-")
    (tmp_path / f"system-ols-{kind}.yaml").write_text(
        "agents:\n  default:\n    agent: [zed, alpha]\n"
    )
    for agent in ("alpha", "zed"):
        (tmp_path / agent / "run_1").mkdir(parents=True)
    report = report_module.generate_report(tmp_path)
    assert "| | zed | alpha |" in report


@pytest.mark.parametrize("is_tty", [True, False])
@pytest.mark.parametrize("passed,total", [(0, 3), (1, 3), (3, 3)])
def test_summary_colors_only_in_a_terminal(monkeypatch, capsys, is_tty, passed, total):
    path = Path(__file__).resolve().parent.parent / "summarize-agentic-evals.py"
    spec = importlib.util.spec_from_file_location("summarize_agentic_evals", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.sys.stdout, "isatty", lambda: is_tty)
    mod.print_table(["scenario"], ["Correctness"], [{"Correctness": (passed, total)}])
    output = capsys.readouterr().out
    assert f"{passed}/{total}" in output
    assert ("\033[" in output) == (is_tty and passed in (0, total))


def planned_session(mod, root, state="completed"):
    """Two scenarios and three repeats, including an agent with no results."""
    kind = Path(mod.__file__).stem.removeprefix("generate-report-")
    filename = f"evals-ols-{kind}.yaml"
    for name, cid in (("healthy", "healthy_id"), ("setup_error", "setup_id")):
        path = root / "scenarios" / name / filename
        path.parent.mkdir(parents=True)
        path.write_text(f"- conversation_group_id: {cid}\n")
    (root / f"system-ols-{kind}.yaml").write_text(
        "agents:\n  default:\n    agent: [empty, agent]\n    repeat: 3\n"
    )
    progress = {
        "state": state, "repeat": 3, "agents": ["empty", "agent"],
        "scenarios": ["scenarios/healthy", "scenarios/setup_error"],
        "items": [
            {"scenario": "scenarios/healthy", "state": "completed"},
            {"scenario": "scenarios/setup_error", "state": "error",
             "detail": "Setup failed (exit 1)"},
        ],
    }
    (root / "progress.json").write_text(json.dumps(progress))
    for index, result, score in ((1, "PASS", 0.9), (3, "FAIL", 0.3)):
        path = root / "agent" / f"run_{index}" / "result_summary.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"results": [metric(mod, result, score, "healthy_id")]}))
    return filename, progress


def test_saved_plan_includes_setup_errors_missing_runs_and_empty_agents(report_module, tmp_path, capsys):
    mod = report_module
    filename, _ = planned_session(mod, tmp_path)
    report = mod.generate_report(tmp_path)
    assert "2 scenarios, 2 agents, 3 repeats" in report
    assert "| | empty | agent |" in report
    for label in ("PASS", "FAIL", "ERROR", "Avg score"):
        assert f"| {label} |" in report
        assert f"| **{label}** |" in report
    agentic = hasattr(mod, "scored_conversations")
    denominator = 3 if agentic else 6
    errors = "33% (1/3)" if agentic else "67% (4/6)"
    failed = "33% (1/3)" if agentic else "17% (1/6)"
    assert f"| ERROR | 100% ({denominator}/{denominator}) | {errors} |" in report
    assert f"| FAIL | 0% (0/{denominator}) | {failed} |" in report
    assert f"| Avg score | N/A (0/{denominator}) | **0.60 (2/{denominator})** 🥇 |" in report
    if agentic:
        phases = report.split("## Phase completion")[1].split("## Time")[0]
        assert "| [setup_error](#setup_id) | [A N/A](#empty--setup_id) |" in phases
    else:
        assert "| [setup_error](#setup_id) | [⚠️ 0/3](#empty--setup_id) |" in report
    assert '<a id="empty--setup_id"></a>' in report
    assert "## Tokens" in report
    assert "## Cost" not in report

    names = ["empty", "agent"]
    runs = {a: [mod.load_run_summary(rd) for rd in mod.find_run_dirs(tmp_path, a)] for a in names}
    amended = {a: [[] for _ in runs[a]] for a in names}
    conversations, scenario_names, repeat = mod.prepare_planned_runs(
        tmp_path, filename, names, runs, amended,
    )
    assert repeat == 3
    assert runs["agent"][1] is None
    assert runs["agent"][2][0]["result"] == "FAIL"
    mod.print_correctness_table(conversations, names, runs, amended, scenario_names)
    output = capsys.readouterr().out
    assert "17% (1/6)" in output
    assert "67% (4/6)" in output
    assert "setup_error" in output
    assert "0.60 (2/6)" in output


@pytest.mark.parametrize("state,expected_errors,expected_pending", [
    ("running", 0, 3), ("completed", 3, 0), ("interrupted", 3, 0),
])
def test_missing_planned_runs_follow_session_state(
    report_module, tmp_path, state, expected_errors, expected_pending,
):
    mod = report_module
    filename, progress = planned_session(mod, tmp_path, state)
    progress["items"][0]["state"] = "running"
    (tmp_path / "progress.json").write_text(json.dumps(progress))
    runs = {"empty": []}
    amended = {"empty": []}
    mod.prepare_planned_runs(tmp_path, filename, ["empty"], runs, amended)
    stats = mod.report_stats(runs["empty"], ["healthy_id"], mod.get_performance_result)
    assert stats["total"] == expected_errors
    assert stats["ERROR"] == expected_errors
    assert stats["PENDING"] == expected_pending
    assert stats["mean"] is None


@pytest.mark.parametrize("is_tty", [True, False])
def test_cli_fail_and_error_rates_use_status_colors_when_nonzero(report_module, monkeypatch, capsys, is_tty):
    mod = report_module
    monkeypatch.setattr(mod.sys.stdout, "isatty", lambda: is_tty)
    runs = {
        "bad": [[metric(mod, "PASS", 1)], [metric(mod, "FAIL", 0.2)], None],
        "good": [[metric(mod, "PASS", 1)]] * 3,
    }
    mod.print_correctness_table(["scenario"], list(runs), runs)
    output = capsys.readouterr().out
    for label in ("FAIL", "ERROR"):
        color = mod.YELLOW if label == "ERROR" else mod.RED
        row = next(line for line in output.splitlines() if line.startswith(f"| {label}"))
        assert (color + "33% (1/3)" + mod.RESET in row) == is_tty
        assert color + "0% (0/3)" not in row
        assert "0% (0/3)" in row
        assert ("\033[" in row) == is_tty


def test_completion_status_is_not_a_quality_score(report_module):
    mod = report_module
    status = metric(mod, "PASS", 1.0)
    status["metric_identifier"] = "custom:openshift_agentic_run_status"
    assert mod.mean_score([[status]], ["scenario"]) is None


def test_real_zero_score_survives_a_technical_error(report_module):
    mod = report_module
    status = metric(mod, "FAIL", 0.0)
    status["metric_identifier"] = "custom:openshift_agentic_run_status"
    runs = [[metric(mod, "FAIL", 0.0), status], [metric(mod, "PASS", 1.0)]]
    stats = mod.report_stats(runs, ["scenario"], mod.get_performance_result)
    assert stats["PASS"] == 1
    assert stats["FAIL"] == 0
    assert stats["ERROR"] == 1
    assert stats["scored"] == 2
    assert stats["mean"] == 0.5


@pytest.mark.parametrize("state", ["running", "interrupted", "completed"])
def test_partial_tables_only_count_finished_runs(report_module, tmp_path, capsys, state):
    mod = report_module
    filename, progress = planned_session(mod, tmp_path, state)
    progress["items"] = [
        {"scenario": scenario, "agent": agent, "run_index": index,
         "state": "completed" if (scenario, agent, index) ==
         ("scenarios/healthy", "agent", 1) else "pending"}
        for scenario in progress["scenarios"]
        for agent in progress["agents"] for index in range(1, 4)
    ]
    (tmp_path / "progress.json").write_text(json.dumps(progress))
    (tmp_path / "agent" / "run_3" / "result_summary.json").unlink()
    report = mod.generate_report(tmp_path)
    assert "1 scenario, 2 agents, 3 repeats" in report
    assert "| PASS | N/A | **100% (1/1)** 🥇 |" in report
    assert "0.90 (1/1)" in report
    assert "[setup_error](#setup_id)" not in report
    names = ["empty", "agent"]
    runs = {a: [mod.load_run_summary(rd) for rd in mod.find_run_dirs(tmp_path, a)] for a in names}
    amended = {a: [[] for _ in runs[a]] for a in names}
    conversations, scenario_names, _ = mod.prepare_planned_runs(
        tmp_path, filename, names, runs, amended,
    )
    mod.print_correctness_table(conversations, names, runs, amended, scenario_names)
    output = capsys.readouterr().out
    assert "setup_error" not in output
    assert "100% (1/1)" in output
    assert "0.90 (1/1)" in output
