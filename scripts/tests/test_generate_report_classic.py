"""Tests for generate-report-classic.py."""

import json
import textwrap
from pathlib import Path

import pytest
import yaml

import importlib.util

spec = importlib.util.spec_from_file_location(
    "generate_report_classic",
    Path(__file__).resolve().parent.parent / "generate-report-classic.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _make_summary_json(results: list[dict], config: dict | None = None) -> dict:
    return {
        "timestamp": "2026-09-04T10:00:00+00:00",
        "total_evaluations": len(results),
        "summary_stats": {},
        "configuration": config or {"llm": {"provider": "openai", "model": "gpt-4o-mini"}},
        "results": results,
    }


def _make_result(
    conversation_id: str,
    result: str = "PASS",
    score: float = 1.0,
    reason: str = "Good",
    agent_latency: float = 15.0,
    api_input_tokens: int = 40000,
    api_output_tokens: int = 800,
) -> dict:
    return {
        "conversation_group_id": conversation_id,
        "tag": [conversation_id],
        "turn_id": "turn_1",
        "metric_identifier": "custom:answer_correctness",
        "result": result,
        "score": score,
        "threshold": None,
        "execution_time": agent_latency + 5.0,
        "evaluation_latency": 5.0,
        "judge_llm_input_tokens": 900,
        "judge_llm_output_tokens": 400,
        "judge_scores": [{"reason": reason}],
        "time_to_first_token": None,
        "streaming_duration": None,
        "agent_latency": agent_latency,
        "tokens_per_second": None,
    }


def _make_amended_yaml(entries: list[dict]) -> list[dict]:
    result = []
    for e in entries:
        turn = {
            "query": e.get("query", "What is wrong?"),
            "response": e.get("response", "The pod has 3 replicas."),
            "api_input_tokens": e.get("api_input_tokens", 40000),
            "api_output_tokens": e.get("api_output_tokens", 800),
            "agent_latency": e.get("agent_latency", 15.0),
        }
        entry = {
            "conversation_group_id": e["conversation_id"],
            "tag": e.get("tags", [e["conversation_id"]]),
            "turns": [turn],
        }
        if "description" in e:
            entry["description"] = e["description"]
        result.append(entry)
    return result


def _write_run(
    run_dir: Path,
    results: list[dict],
    amended_entries: list[dict],
    timestamp: str = "20260904_100000",
    config: dict | None = None,
):
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = _make_summary_json(results, config)
    (run_dir / f"evaluation_{timestamp}_summary.json").write_text(json.dumps(summary))
    amended = _make_amended_yaml(amended_entries)
    (run_dir / f"evals-ols-classic_amended_{timestamp}.yaml").write_text(yaml.dump(amended))


class TestDiscoverAgents:
    def test_discovers_agents_from_directories(self, tmp_path):
        (tmp_path / "gpt-5.4" / "run_1").mkdir(parents=True)
        (tmp_path / "gpt-5.2" / "run_1").mkdir(parents=True)
        agents = mod.discover_agents(tmp_path)
        assert set(agents) == {"gpt-5.4", "gpt-5.2"}

    def test_ignores_non_agent_files(self, tmp_path):
        (tmp_path / "gpt-5.4" / "run_1").mkdir(parents=True)
        (tmp_path / "eval_report.json").write_text("{}")
        agents = mod.discover_agents(tmp_path)
        assert agents == ["gpt-5.4"]

    def test_returns_sorted_agents(self, tmp_path):
        for name in ["opus", "gpt", "gemini"]:
            (tmp_path / name / "run_1").mkdir(parents=True)
        agents = mod.discover_agents(tmp_path)
        assert agents == ["gemini", "gpt", "opus"]

    def test_empty_directory(self, tmp_path):
        agents = mod.discover_agents(tmp_path)
        assert agents == []


class TestFindRunDirs:
    def test_finds_run_dirs_sorted(self, tmp_path):
        agent_dir = tmp_path / "agent1"
        for i in [3, 1, 2]:
            (agent_dir / f"run_{i}").mkdir(parents=True)
        dirs = mod.find_run_dirs(tmp_path, "agent1")
        assert [d.name for d in dirs] == ["run_1", "run_2", "run_3"]

    def test_missing_agent_returns_empty(self, tmp_path):
        assert mod.find_run_dirs(tmp_path, "nonexistent") == []


class TestLoadRunSummary:
    def test_reads_all_summary_jsons(self, tmp_path):
        run_dir = tmp_path / "run_1"
        run_dir.mkdir()
        r1 = [_make_result("scenario_a", score=0.9)]
        r2 = [_make_result("scenario_b", score=0.8)]
        (run_dir / "evaluation_20260904_100000_summary.json").write_text(
            json.dumps(_make_summary_json(r1))
        )
        (run_dir / "evaluation_20260904_100100_summary.json").write_text(
            json.dumps(_make_summary_json(r2))
        )
        results = mod.load_run_summary(run_dir)
        assert len(results) == 2
        cids = {r["conversation_group_id"] for r in results}
        assert cids == {"scenario_a", "scenario_b"}

    def test_no_summary_files(self, tmp_path):
        run_dir = tmp_path / "run_1"
        run_dir.mkdir()
        assert mod.load_run_summary(run_dir) is None


class TestGenerateReport:
    def test_single_agent_single_run(self, tmp_path):
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("unbalanced_replicas")],
            amended_entries=[{"conversation_id": "unbalanced_replicas"}],
        )
        report = mod.generate_report(tmp_path)
        assert "# Evaluation Summary" in report
        assert "gpt-5.4" in report
        assert "unbalanced_replicas" in report

    def test_multi_agent_multi_run(self, tmp_path):
        for agent in ["gpt-5.4", "gpt-5.2"]:
            for run in [1, 2]:
                _write_run(
                    tmp_path / agent / f"run_{run}",
                    results=[_make_result("unbalanced_replicas", score=0.9 if run == 1 else 0.5)],
                    amended_entries=[{"conversation_id": "unbalanced_replicas"}],
                    timestamp=f"20260904_10000{run}",
                )
        report = mod.generate_report(tmp_path)
        assert "2 agents" in report
        assert "2 repeat" in report
        assert "gpt-5.4" in report
        assert "gpt-5.2" in report

    def test_multiple_scenarios_across_invocations(self, tmp_path):
        run_dir = tmp_path / "gpt-5.4" / "run_1"
        _write_run(
            run_dir,
            results=[_make_result("scenario_a", score=1.0)],
            amended_entries=[{"conversation_id": "scenario_a"}],
            timestamp="20260904_100000",
        )
        r2 = [_make_result("scenario_b", score=0.8)]
        (run_dir / "evaluation_20260904_100100_summary.json").write_text(
            json.dumps(_make_summary_json(r2))
        )
        amended_b = _make_amended_yaml([{"conversation_id": "scenario_b"}])
        (run_dir / "evals-ols-classic_amended_20260904_100100.yaml").write_text(yaml.dump(amended_b))

        report = mod.generate_report(tmp_path)
        assert "scenario_a" in report
        assert "scenario_b" in report
        assert "2 scenario" in report

    def test_overall_score_row(self, tmp_path):
        for run in [1, 2]:
            _write_run(
                tmp_path / "gpt-5.4" / f"run_{run}",
                results=[
                    _make_result("s1", result="PASS"),
                    _make_result("s2", result="PASS" if run == 1 else "FAIL"),
                ],
                amended_entries=[
                    {"conversation_id": "s1"},
                    {"conversation_id": "s2"},
                ],
                timestamp=f"20260904_10000{run}",
            )
        report = mod.generate_report(tmp_path)
        assert "**Pass rate**" in report
        assert "75% (3/4)" in report

    def test_timestamp_in_header(self, tmp_path):
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1")],
            amended_entries=[{"conversation_id": "s1"}],
        )
        report = mod.generate_report(tmp_path)
        assert "2026-09-04 10:00:00 UTC" in report

    def test_scenario_description(self, tmp_path):
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1")],
            amended_entries=[{
                "conversation_id": "s1",
                "description": "Two namespaces with different pod counts.",
            }],
        )
        report = mod.generate_report(tmp_path)
        assert "Two namespaces with different pod counts." in report

    def test_scenarios_heading(self, tmp_path):
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1")],
            amended_entries=[{"conversation_id": "s1"}],
        )
        report = mod.generate_report(tmp_path)
        assert "# Scenarios" in report

    def test_handles_null_judge_scores(self, tmp_path):
        result = _make_result("s1")
        result["judge_scores"] = None
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[result],
            amended_entries=[{"conversation_id": "s1"}],
        )
        report = mod.generate_report(tmp_path)
        assert "# Evaluation Summary" in report
        assert "s1" in report

    def test_score_cell_links_to_agent_section(self, tmp_path):
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1")],
            amended_entries=[{"conversation_id": "s1"}],
        )
        report = mod.generate_report(tmp_path)
        assert "(#gpt-5.4--s1)" in report

    def test_agent_section_has_anchor(self, tmp_path):
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1")],
            amended_entries=[{"conversation_id": "s1"}],
        )
        report = mod.generate_report(tmp_path)
        assert '<a id="gpt-5.4--s1"></a>' in report

    def test_best_overall_score_is_bold(self, tmp_path):
        for run in [1, 2]:
            _write_run(
                tmp_path / "gpt-5.4" / f"run_{run}",
                results=[_make_result("s1", result="PASS")],
                amended_entries=[{"conversation_id": "s1"}],
                timestamp=f"20260904_10000{run}",
            )
            _write_run(
                tmp_path / "gemini" / f"run_{run}",
                results=[_make_result("s1", result="PASS" if run == 1 else "FAIL")],
                amended_entries=[{"conversation_id": "s1"}],
                timestamp=f"20260904_10000{run}",
            )
        report = mod.generate_report(tmp_path)
        assert "**✅ 100% (2/2)**" in report
        assert "50% (1/2)" in report
        assert "**50% (1/2)**" not in report

    def test_tied_best_overall_scores_both_bold(self, tmp_path):
        for agent in ["gpt-5.4", "gemini"]:
            _write_run(
                tmp_path / agent / "run_1",
                results=[_make_result("s1", result="PASS")],
                amended_entries=[{"conversation_id": "s1"}],
            )
        report = mod.generate_report(tmp_path)
        assert report.count("**✅ 100% (1/1)**") == 2

    def test_judge_in_header(self, tmp_path):
        config = {
            "llm_pool": {"models": {"judge": {"model": "gpt-5.4"}}},
            "judge_panel": {"judges": ["judge"]},
        }
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1")],
            amended_entries=[{"conversation_id": "s1"}],
            config=config,
        )
        report = mod.generate_report(tmp_path)
        assert "Judge: gpt-5.4" in report

    def test_no_judge_by_default(self, tmp_path):
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1")],
            amended_entries=[{"conversation_id": "s1"}],
        )
        report = mod.generate_report(tmp_path)
        assert "Judge" not in report

    def test_duration_from_agent_latency(self, tmp_path):
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1", agent_latency=25.5)],
            amended_entries=[{"conversation_id": "s1", "agent_latency": 25.5}],
        )
        report = mod.generate_report(tmp_path)
        assert "26s" in report

    def test_tokens_in_scenario_details(self, tmp_path):
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1", api_input_tokens=40000, api_output_tokens=800)],
            amended_entries=[{
                "conversation_id": "s1",
                "api_input_tokens": 40000,
                "api_output_tokens": 800,
            }],
        )
        report = mod.generate_report(tmp_path)
        assert "**Tokens**: 40,800" in report

    def test_tokens_from_results(self, tmp_path):
        _write_run(
            tmp_path / "agent" / "run_1",
            results=[_make_result("s1", api_input_tokens=50000, api_output_tokens=1000)],
            amended_entries=[{
                "conversation_id": "s1",
                "api_input_tokens": 50000,
                "api_output_tokens": 1000,
            }],
        )
        report = mod.generate_report(tmp_path)
        assert "| Avg tokens | 51K |" in report

    def test_avg_tokens_divides_by_evaluations_not_scenarios(self, tmp_path):
        for run in [1, 2]:
            _write_run(
                tmp_path / "agent" / f"run_{run}",
                results=[_make_result("s1", api_input_tokens=60, api_output_tokens=40)],
                amended_entries=[{
                    "conversation_id": "s1",
                    "api_input_tokens": 60,
                    "api_output_tokens": 40,
                }],
                timestamp=f"20260904_10000{run}",
            )
        report = mod.generate_report(tmp_path)
        assert "| Avg tokens | 100 |" in report
        assert "| **Average** | 100 |" in report

    def test_tokens_compact_millions(self, tmp_path):
        _write_run(
            tmp_path / "agent" / "run_1",
            results=[_make_result("s1", api_input_tokens=1200000, api_output_tokens=50000)],
            amended_entries=[{
                "conversation_id": "s1",
                "api_input_tokens": 1200000,
                "api_output_tokens": 50000,
            }],
        )
        report = mod.generate_report(tmp_path)
        assert "| Avg tokens | 1.2M |" in report
        # Detail section keeps exact number
        assert "**Tokens**: 1,250,000" in report

    def test_no_completed_metric(self, tmp_path):
        """Classic evals only have answer_correctness, no status metric."""
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1")],
            amended_entries=[{"conversation_id": "s1"}],
        )
        report = mod.generate_report(tmp_path)
        assert "Completed" not in report
        assert "openshift_agentic_run_status" not in report

    def test_response_not_stripped(self, tmp_path):
        """Classic responses are shown in full, no section stripping."""
        response_text = "## Evidence\n\nThe pods are running.\n\n## Root cause\n\nConfig mismatch."
        _write_run(
            tmp_path / "gpt-5.4" / "run_1",
            results=[_make_result("s1")],
            amended_entries=[{
                "conversation_id": "s1",
                "response": response_text,
            }],
        )
        report = mod.generate_report(tmp_path)
        assert "## Evidence" in report
        assert "## Root cause" in report


class TestPrintCorrectnessTable:
    def test_basic_output(self, tmp_path, capsys):
        for agent, result in [("agentA", "PASS"), ("agentB", "FAIL")]:
            _write_run(
                tmp_path / agent / "run_1",
                results=[_make_result("s1", result=result)],
                amended_entries=[{"conversation_id": "s1"}],
            )
        agent_runs = {
            a: [mod.load_run_summary(tmp_path / a / "run_1")]
            for a in ["agentA", "agentB"]
        }
        conversations = mod.collect_conversations(agent_runs)
        mod.print_correctness_table(conversations, ["agentA", "agentB"], agent_runs)
        out = capsys.readouterr().out
        assert "s1" in out
        assert "1/1" in out
        assert "Pass rate" in out

    def test_multi_run_counts(self, tmp_path, capsys):
        _write_run(
            tmp_path / "a" / "run_1",
            results=[_make_result("s1", result="PASS")],
            amended_entries=[{"conversation_id": "s1"}],
        )
        _write_run(
            tmp_path / "a" / "run_2",
            results=[_make_result("s1", result="FAIL", score=0.2)],
            amended_entries=[{"conversation_id": "s1"}],
            timestamp="20260904_100001",
        )
        agent_runs = {"a": [
            mod.load_run_summary(tmp_path / "a" / "run_1"),
            mod.load_run_summary(tmp_path / "a" / "run_2"),
        ]}
        conversations = mod.collect_conversations(agent_runs)
        mod.print_correctness_table(conversations, ["a"], agent_runs)
        out = capsys.readouterr().out
        assert "1/2" in out
