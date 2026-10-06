#!/usr/bin/env python3
"""Generate a Markdown report from NxM agentic evaluation output.

Reads the eval session directory produced by lightspeed-eval's
behavioral orchestrator and generates a comparative report across
agents and runs.

Usage:
    python3 generate-report-agentic.py EVAL_DIR [--output FILE] [--parallel-runs yes|no]

EVAL_DIR is the eval session directory
(e.g., eval_output/eval_20260829_210316/).
The judge model is extracted from the summary JSON configuration.
"""

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from report_common import (  # noqa: E402
    CORRECTNESS_LEGEND,
    correctness_icon,
    has_technical_failure,
    performance_result,
    anchor_id,
    collect_conversations,
    load_scenario_names,
    discover_agents,
    extract_judge_model,
    find_run_dirs,
    format_duration,
    format_report_metadata,
    format_timestamp,
    format_token_pair,
    mean_tokens,
    overall_score_cell,
    scenario_tokens,
    winner_cell,
    is_best_score,
    system_config_appendix,
)

from report_progress import format_failed_scenarios, format_progress, load_progress, write_atomic  # noqa: E402

METRIC_LABELS = {
    "custom:openshift_agentic_run_status": "Completed",
    "custom:openshift_agentic_run_evaluation_correctness": "Correctness",
}

CORRECTNESS_METRIC = "custom:openshift_agentic_run_evaluation_correctness"
STATUS_METRIC = "custom:openshift_agentic_run_status"
PHASE_CONDITIONS = (
    ("Analysis", "Analyzed"),
    ("Execution", "Executed"),
    ("Verification", "Verified"),
)


def metric_label(metric_id: str) -> str:
    return METRIC_LABELS.get(metric_id, metric_id.split(":")[-1])


def load_run_summary(run_dir: Path) -> list[dict] | None:
    """Load results from all summary JSONs in a run directory."""
    files = sorted(run_dir.glob("*_summary.json"))
    if not files:
        return None
    results = []
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        file_results = data.get("results", [])
        detailed = f.with_name(f.name.replace("_summary.json", "_detailed.csv"))
        if detailed.exists():
            with detailed.open(newline="") as fh:
                reasons = {
                    (row.get("conversation_group_id"), row.get("turn_id"),
                     row.get("metric_identifier")): row.get("reason", "")
                    for row in csv.DictReader(fh)
                }
            for result in file_results:
                key = (result.get("conversation_group_id"), result.get("turn_id"),
                       result.get("metric_identifier"))
                if not result.get("reason") and reasons.get(key):
                    result["reason"] = reasons[key]
        results.extend(file_results)
    return results


def append_outcome(response: str, details: list[str]) -> str:
    """Add saved details to Outcome without repeating existing messages."""
    missing = []
    for detail in details:
        if detail and detail not in response and detail not in missing:
            missing.append(detail)
    if not missing:
        return response
    addition = "\n\n".join(missing)
    outcome = re.search(r"^## Outcome\s*$", response, re.MULTILINE)
    if outcome:
        next_section = re.search(r"^## ", response[outcome.end():], re.MULTILINE)
        end = outcome.end() + next_section.start() if next_section else len(response)
        return response[:end].rstrip() + "\n\n" + addition + "\n\n" + response[end:]
    return (response.rstrip() + "\n\n## Outcome\n\n" + addition).lstrip()


def _format_diagnosis(run_results: dict) -> list[str]:
    """Read saved diagnosis details for a no-action response."""
    analysis_results = run_results.get("analysis")
    if not isinstance(analysis_results, list):
        return []
    for analysis in analysis_results:
        if not isinstance(analysis, dict):
            continue
        diagnosis = analysis.get("diagnosis")
        if not isinstance(diagnosis, dict):
            continue
        details = [diagnosis.get(key) for key in ("rootCause", "summary")]
        details = [detail for detail in details if isinstance(detail, str) and detail]
        if details:
            return details
    return []


def load_amended_entries(run_dir: Path) -> list[dict]:
    """Load conversation entries from all amended YAMLs in a run directory."""
    files = sorted(run_dir.glob("*amended*.yaml"))
    if not files:
        return []
    entries = []
    for path in files:
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, list):
            continue
        for entry in data:
            cid = entry.get("conversation_group_id", "")
            turns = entry.get("turns", [])
            tags = entry.get("tag", [])
            if not turns:
                continue
            turn = turns[0]
            duration = None
            run_results = turn.get("openshift_agentic_run_results")
            if not isinstance(run_results, dict):
                run_results = None
            analysis_results = run_results.get("analysis", []) if run_results else []
            if isinstance(analysis_results, list) and analysis_results and isinstance(analysis_results[0], dict):
                # Normalize conditions to empty list if null or not a list
                conditions = analysis_results[0].get("conditions")
                if not isinstance(conditions, list):
                    conditions = []

                # Validate each condition is a dict with required fields before accessing
                started = next(
                    (c.get("lastTransitionTime") for c in conditions
                     if isinstance(c, dict) and c.get("type") == "Started"),
                    None
                )
                completed = next(
                    (c.get("lastTransitionTime") for c in conditions
                     if isinstance(c, dict) and c.get("type") == "Completed"),
                    None
                )
                if started and completed:
                    s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    e = datetime.fromisoformat(completed.replace("Z", "+00:00"))
                    duration = (e - s).total_seconds()

            # Normalize agentic_run_status to dict (handle non-dict truthy values like lists)
            run_status = turn.get("openshift_agentic_run_status")
            if not isinstance(run_status, dict):
                run_status = {}

            token_usage = run_status.get("tokenUsage") or {}
            agent_input_tok = token_usage.get("inputTokens")
            agent_output_tok = token_usage.get("outputTokens")

            # Normalize conditions to list of dicts (prevents phase_status iteration errors)
            if "conditions" in run_status:
                conditions_raw = run_status["conditions"]
                if not isinstance(conditions_raw, list):
                    run_status["conditions"] = []
                else:
                    # Filter to only valid dict entries
                    run_status["conditions"] = [
                        c for c in conditions_raw if isinstance(c, dict)
                    ]

            response = turn.get("response") or ""
            if run_results and "no action required" in response.lower():
                response = append_outcome(response, _format_diagnosis(run_results))

            entries.append({
                "conversation_group_id": cid,
                "description": entry.get("description", ""),
                "query": turn.get("query", ""),
                "response": response,
                "tags": tags,
                "agentic_run_status": run_status,
                "analysis_duration": duration,
                "agent_input_tokens": agent_input_tok,
                "agent_output_tokens": agent_output_tok,
            })
    return entries


def get_score(results: list[dict], conversation_id: str, metric_id: str) -> float | None:
    for r in results:
        if r["conversation_group_id"] == conversation_id and r["metric_identifier"] == metric_id:
            return r.get("score")
    return None


def get_result(results: list[dict], conversation_id: str, metric_id: str) -> str | None:
    for r in results:
        if r["conversation_group_id"] == conversation_id and r["metric_identifier"] == metric_id:
            return r.get("result")
    return None


def get_judge_reason(results: list[dict], conversation_id: str, metric_id: str) -> str:
    for r in results:
        if r["conversation_group_id"] == conversation_id and r["metric_identifier"] == metric_id:
            for js in r.get("judge_scores") or []:
                reason = js.get("reason", "")
                if reason:
                    return reason
    return ""


def get_performance_result(
    results: list[dict], conversation_id: str
) -> tuple[str | None, float | None]:
    """Prefer correctness, with completion status as a fallback."""
    return performance_result(results, conversation_id, (CORRECTNESS_METRIC, STATUS_METRIC))


def strip_request_section(response: str) -> str:
    match = re.search(r'^## Analysis\b', response, re.MULTILINE)
    if match:
        return response[match.start():]
    return response


def score_cell(agent_runs: list, conversation_id: str, agent: str) -> str:
    """Build a summary table cell for one agent + one conversation.

    With 1 run: show the score directly.
    With N runs: show passed/total.
    Links to the first run section for that agent+scenario.
    """
    scores = []
    technical_failure = False
    for results in agent_runs:
        if results is None:
            continue
        if has_technical_failure(results, conversation_id):
            technical_failure = True
        result, score = get_performance_result(results, conversation_id)
        if result is not None:
            scores.append((result, score))

    if not scores:
        return "N/A"

    anchor = anchor_id(agent, conversation_id)
    passed = sum(1 for r, _ in scores if r == "PASS")
    total = len(scores)
    icon = correctness_icon(passed, total, technical_failure)

    if len(scores) == 1:
        result, score = scores[0]
        score_str = f"{score:.2f}" if score is not None else "N/A"
        return f"[{icon} {score_str}](#{anchor})"

    valid_scores = [s for _, s in scores if s is not None]
    avg = sum(valid_scores) / len(valid_scores) if valid_scores else None
    avg_str = f" ({avg:.2f})" if avg is not None else ""
    label = f"{icon} {passed}/{total}".strip()
    return f"[{label}](#{anchor}){avg_str}"


def overall_score(agent_runs: list, conversations: list[str]) -> tuple[int, int]:
    """Return (passed, total) across all runs and conversations."""
    passed = 0
    total = 0
    for results in agent_runs:
        if results is None:
            continue
        for cid in conversations:
            result, _ = get_performance_result(results, cid)
            if result is not None:
                total += 1
                if result == "PASS":
                    passed += 1
    return passed, total


def scenario_mean_score(agent_runs: list, conversation_id: str) -> float | None:
    """Mean score for one scenario, counting technical failures as zero."""
    scores = []
    for results in agent_runs:
        if results is None:
            continue
        _, s = get_performance_result(results, conversation_id)
        if s is not None:
            scores.append(s)
    return sum(scores) / len(scores) if scores else None


def mean_score(agent_runs: list, conversations: list[str]) -> float | None:
    """Mean score across runs and scenarios, counting technical failures as zero."""
    scores = []
    for results in agent_runs:
        if results is None:
            continue
        for cid in conversations:
            _, score = get_performance_result(results, cid)
            if score is not None:
                scores.append(score)
    if not scores:
        return None
    return sum(scores) / len(scores)


def mean_duration(agent_amended: list, conversations: list[str]) -> float | None:
    """Mean analysis duration (seconds) across all runs and conversations."""
    durations = []
    for entries in agent_amended:
        for entry in entries:
            if entry["conversation_group_id"] in conversations and entry.get("analysis_duration") is not None:
                durations.append(entry["analysis_duration"])
    if not durations:
        return None
    return sum(durations) / len(durations)


def scenario_duration(agent_amended: list, cid: str) -> float | None:
    """Mean analysis duration for a single scenario across runs."""
    durations = []
    for entries in agent_amended:
        for entry in entries:
            if entry["conversation_group_id"] == cid and entry.get("analysis_duration") is not None:
                durations.append(entry["analysis_duration"])
    if not durations:
        return None
    return sum(durations) / len(durations)


def bold_best(values: dict[str, str | None], best_val, cmp="max") -> dict[str, str]:
    """Bold the best value(s) in a dict of agent -> formatted string."""
    result = {}
    for a, text in values.items():
        if text is None:
            result[a] = "N/A"
        elif best_val is not None and text == best_val:
            result[a] = winner_cell(text, True)
        else:
            result[a] = text
    return result


def generate_overview_table(
    conversations: list[str],
    agent_names: list[str],
    agent_runs: dict[str, list],
    agent_amended: dict[str, list],
) -> str:
    header = "| | " + " | ".join(agent_names) + " |"
    separator = "|---|" + "|".join("---" for _ in agent_names) + "|"
    lines = [header, separator]

    # Pass rate %
    scores_map = {a: overall_score(agent_runs[a], conversations) for a in agent_names}
    pcts = {a: round(100 * p / t) if t > 0 else None for a, (p, t) in scores_map.items()}
    best_pct = max((v for v in pcts.values() if v is not None), default=None)
    cells = []
    for a in agent_names:
        if pcts[a] is None:
            cells.append("N/A")
        else:
            text = f"{pcts[a]}%"
            if pcts[a] == best_pct:
                text = winner_cell(text, True)
            cells.append(text)
    lines.append(f"| Pass rate | {' | '.join(cells)} |")

    # Mean score
    mean_scores = {a: mean_score(agent_runs[a], conversations) for a in agent_names}
    best_mean = max((s for s in mean_scores.values() if s is not None), default=None)
    cells = []
    for a in agent_names:
        s = mean_scores[a]
        if s is None:
            cells.append("N/A")
        else:
            text = f"{s:.2f}"
            if is_best_score(s, best_mean):
                text = winner_cell(text, True)
            cells.append(text)
    lines.append(f"| Avg score | {' | '.join(cells)} |")

    # Mean duration
    mean_durations = {a: mean_duration(agent_amended[a], conversations) for a in agent_names}
    best_dur = min((d for d in mean_durations.values() if d is not None), default=None)
    cells = []
    for a in agent_names:
        d = mean_durations[a]
        if d is None:
            cells.append("N/A")
        else:
            text = format_duration(d)
            if best_dur is not None and d == best_dur:
                text = winner_cell(text, True)
            cells.append(text)
    lines.append(f"| Avg duration | {' | '.join(cells)} |")

    # Avg tokens
    avg_tok = {a: mean_tokens(agent_amended[a], conversations) for a in agent_names}
    cells = [format_token_pair(*avg_tok[a]) for a in agent_names]
    lines.append(f"| Avg tokens | {' | '.join(cells)} |")

    return "\n".join(lines)


def duration_cell(agent_amended: list, cid: str, agent: str) -> str:
    d = scenario_duration(agent_amended, cid)
    if d is None:
        return "N/A"
    anchor = anchor_id(agent, cid)
    return f"[{format_duration(d)}](#{anchor})"


def remediation_conversations(
    conversations: list[str], agent_amended: dict[str, list]
) -> list[str]:
    """Return evaluated conversations tagged for remediation."""
    remediation = []
    for cid in conversations:
        for runs in agent_amended.values():
            if any(
                entry["conversation_group_id"] == cid
                and "remediation" in entry.get("tags", [])
                for entries in runs
                for entry in entries
            ):
                remediation.append(cid)
                break
    return remediation


def phase_status(entries: list[dict], conversation_id: str, condition_type: str) -> str:
    """Return Completed only when the AgenticRun phase condition is true."""
    for entry in entries:
        if entry["conversation_group_id"] != conversation_id:
            continue
        for condition in entry.get("agentic_run_status", {}).get("conditions", []):
            if condition.get("type") == condition_type:
                if str(condition.get("status", "")).lower() == "true":
                    return "Completed"
                if "timed out" in json.dumps(condition).lower():
                    return "TimedOut"
                return "Failed"
        return "Failed"
    return "Failed"


def phase_count(agent_amended: list, cid: str, condition_type: str) -> tuple[int, int]:
    """Return completed and total runs for one remediation phase."""
    statuses = [
        phase_status(entries, cid, condition_type)
        for entries in agent_amended
        if any(entry["conversation_group_id"] == cid for entry in entries)
    ]
    return sum(status == "Completed" for status in statuses), len(statuses)


def phase_rate_cell(completed: int, total: int, bold: bool = False) -> str:
    """Format a phase pass rate using the Correctness table convention."""
    if total == 0:
        return "N/A"
    pct = round(100 * completed / total)
    text = f"{pct}% ({completed}/{total})"
    return winner_cell(text, bold)


def phase_breakdown_cell(agent_amended: list, cid: str, agent: str) -> str:
    """Build one linked phase-summary cell for an agent and conversation."""
    phases = []
    for label, condition_type in PHASE_CONDITIONS:
        statuses = [
            phase_status(entries, cid, condition_type)
            for entries in agent_amended
            if any(entry["conversation_group_id"] == cid for entry in entries)
        ]
        completed = sum(status == "Completed" for status in statuses)
        total = len(statuses)
        text = f"{completed}/{total}"
        if total and completed == total:
            text = f"✅ {text}"
        elif "TimedOut" in statuses:
            text = f"⏳ {text}"
        elif completed == 0:
            text = f"❌ {text}"
        phases.append(f"{label[0]} {text}")
    return f"[{'<br>'.join(phases)}](#{anchor_id(agent, cid)})"


def generate_phase_breakdown_table(
    conversations: list[str], agent_names: list[str], agent_amended: dict[str, list],
    scenario_names: dict[str, str] | None = None,
) -> str:
    """Render per-phase outcomes for remediation scenarios."""
    scenario_names = scenario_names or {}
    header = "| Scenario | " + " | ".join(agent_names) + " |"
    separator = "|---|" + "|".join("---" for _ in agent_names) + "|"
    lines = [header, separator]
    for cid in conversations:
        anchor = cid.lower().replace(" ", "-")
        cells = [phase_breakdown_cell(agent_amended[agent], cid, agent) for agent in agent_names]
        lines.append(f"| [{scenario_names.get(cid, cid)}](#{anchor}) | {' | '.join(cells)} |")

    phase_totals = {
        agent: {
            condition_type: tuple(
                sum(values[index] for values in (
                    phase_count(agent_amended[agent], cid, condition_type)
                    for cid in conversations
                ))
                for index in (0, 1)
            )
            for _, condition_type in PHASE_CONDITIONS
        }
        for agent in agent_names
    }
    best_rates = {
        condition_type: max(
            (
                completed / total
                for completed, total in (
                    phase_totals[agent][condition_type] for agent in agent_names
                )
                if total > 0
            ),
            default=None,
        )
        for _, condition_type in PHASE_CONDITIONS
    }
    cells = []
    for agent in agent_names:
        rates = []
        for label, condition_type in PHASE_CONDITIONS:
            completed, total = phase_totals[agent][condition_type]
            rates.append(
                f"{label[0]} {phase_rate_cell(
                    completed,
                    total,
                    bold=total > 0 and completed / total == best_rates[condition_type],
                )}"
            )
        cells.append("<br>".join(rates))
    lines.append(f"| **Pass rate** | {' | '.join(cells)} |")
    return "\n".join(lines)


def generate_duration_table(
    conversations: list[str],
    agent_names: list[str],
    agent_amended: dict[str, list],
    scenario_names: dict[str, str] | None = None,
) -> str:
    scenario_names = scenario_names or {}
    header = "| Scenario | " + " | ".join(agent_names) + " |"
    separator = "|---|" + "|".join("---" for _ in agent_names) + "|"
    lines = [header, separator]
    for cid in conversations:
        durations = {a: scenario_duration(agent_amended[a], cid) for a in agent_names}
        best = min((d for d in durations.values() if d is not None), default=None)
        cells = []
        for a in agent_names:
            d = durations[a]
            if d is None:
                cells.append("N/A")
            else:
                anchor = anchor_id(a, cid)
                text = f"[{format_duration(d)}](#{anchor})"
                if best is not None and d == best:
                    text = winner_cell(text, True)
                cells.append(text)
        cid_anchor = cid.lower().replace(" ", "-")
        lines.append(f"| [{scenario_names.get(cid, cid)}](#{cid_anchor}) | {' | '.join(cells)} |")

    # Mean row
    mean_durations = {a: mean_duration(agent_amended[a], conversations) for a in agent_names}
    best_mean = min((d for d in mean_durations.values() if d is not None), default=None)
    cells = []
    for a in agent_names:
        d = mean_durations[a]
        if d is None:
            cells.append("N/A")
        else:
            text = format_duration(d)
            if best_mean is not None and d == best_mean:
                text = winner_cell(text, True)
            cells.append(text)
    lines.append(f"| **Average** | {' | '.join(cells)} |")

    return "\n".join(lines)


def tokens_cell(agent_amended: list, cid: str, agent: str) -> str:
    inp, out = scenario_tokens(agent_amended, cid)
    anchor = anchor_id(agent, cid)
    return f"[{format_token_pair(inp, out)}](#{anchor})"


def generate_tokens_table(
    conversations: list[str],
    agent_names: list[str],
    agent_amended: dict[str, list],
    scenario_names: dict[str, str] | None = None,
) -> str:
    scenario_names = scenario_names or {}
    header = "| Scenario | " + " | ".join(agent_names) + " |"
    separator = "|---|" + "|".join("---" for _ in agent_names) + "|"
    lines = [header, separator]
    for cid in conversations:
        cells = [tokens_cell(agent_amended[a], cid, a) for a in agent_names]
        cid_anchor = cid.lower().replace(" ", "-")
        lines.append(f"| [{scenario_names.get(cid, cid)}](#{cid_anchor}) | {' | '.join(cells)} |")

    # Mean row
    avg_tok = {a: mean_tokens(agent_amended[a], conversations) for a in agent_names}
    cells = [format_token_pair(*avg_tok[a]) for a in agent_names]
    lines.append(f"| **Average** | {' | '.join(cells)} |")

    return "\n".join(lines)


def generate_summary_table(
    conversations: list[str],
    agent_names: list[str],
    agent_runs: dict[str, list],
    scenario_names: dict[str, str] | None = None,
) -> str:
    scenario_names = scenario_names or {}
    header = "| Scenario | " + " | ".join(agent_names) + " |"
    separator = "|---|" + "|".join("---" for _ in agent_names) + "|"
    lines = [header, separator]
    for cid in conversations:
        anchor = cid.lower().replace(" ", "-")
        avg_scores = {a: scenario_mean_score(agent_runs[a], cid) for a in agent_names}
        best = max((s for s in avg_scores.values() if s is not None), default=None)
        cells = []
        for a in agent_names:
            cell = score_cell(agent_runs[a], cid, a)
            if is_best_score(avg_scores[a], best):
                cell = winner_cell(cell, True)
            cells.append(cell)
        lines.append(f"| [{scenario_names.get(cid, cid)}](#{anchor}) | {' | '.join(cells)} |")
    scores = {a: overall_score(agent_runs[a], conversations) for a in agent_names}
    best_pct = max(
        (p / t if t > 0 else -1 for p, t in scores.values()),
        default=-1,
    )
    overall = " | ".join(
        overall_score_cell(
            *scores[a],
            bold=(scores[a][1] > 0 and scores[a][0] / scores[a][1] == best_pct),
        )
        for a in agent_names
    )
    lines.append(f"| **Pass rate** | {overall} |")

    mean_scores = {a: mean_score(agent_runs[a], conversations) for a in agent_names}
    best_mean = max((s for s in mean_scores.values() if s is not None), default=None)
    avg_score_cells = []
    for agent in agent_names:
        score = mean_scores[agent]
        if score is None:
            avg_score_cells.append("N/A")
            continue
        cell = f"{score:.2f}"
        if is_best_score(score, best_mean):
            cell = winner_cell(cell, True)
        avg_score_cells.append(cell)
    lines.append(f"| **Avg score** | {' | '.join(avg_score_cells)} |")
    return "\n".join(lines)



def generate_scenario_details(
    conversations: list[str],
    agent_names: list[str],
    agent_runs: dict[str, list],
    agent_amended: dict[str, list],
    agent_run_dirs: dict[str, list[Path]],
    scenario_names: dict[str, str] | None = None,
) -> str:
    scenario_names = scenario_names or {}
    lines = []

    for cid in conversations:
        name = scenario_names.get(cid, cid)
        if name != cid:
            anchor = cid.lower().replace(" ", "-")
            lines.extend([f'<a id="{anchor}"></a>', ""])
        lines.append(f"## {name}")
        lines.append("")

        # Find description, tags, and query from any agent's data
        description = None
        tags = None
        query = None
        for agent in agent_names:
            for entries in agent_amended[agent]:
                for entry in entries:
                    if entry["conversation_group_id"] == cid:
                        if not description and entry.get("description"):
                            description = entry["description"]
                        if not tags and entry.get("tags"):
                            tags = entry["tags"]
                        if not query and entry.get("query"):
                            query = entry["query"]
                if description and tags and query:
                    break

        if description:
            lines.append(description.strip())
            lines.append("")

        if tags:
            lines.append(f"**Tags**: `{'`, `'.join(tags)}`")
            lines.append("")

        if query:
            lines.append("### Query")
            lines.append("")
            lines.append("```")
            lines.append(query.strip())
            lines.append("```")
            lines.append("")

        # Per agent, per run
        for agent in agent_names:
            runs = agent_runs[agent]
            amended_runs = agent_amended[agent]
            total_runs = len(runs)

            for run_idx, (results, amended_entries) in enumerate(zip(runs, amended_runs)):
                if results is None:
                    continue

                run_num = run_idx + 1
                if run_idx == 0:
                    aid = anchor_id(agent, cid)
                    lines.append(f'<a id="{aid}"></a>')
                    lines.append("")
                if total_runs > 1:
                    lines.append(f"### {agent} (run {run_num}/{total_runs})")
                else:
                    lines.append(f"### {agent}")
                lines.append("")

                # Metrics for this conversation
                conv_results = [r for r in results if r["conversation_group_id"] == cid]
                for r in conv_results:
                    result_icon = "✅" if r["result"] == "PASS" else "❌"
                    score = r.get("score")
                    score_str = f"{score:.2f}" if score is not None else "N/A"
                    lines.append(
                        f"**{metric_label(r['metric_identifier'])}**: "
                        f"{result_icon} {r['result']} (score: {score_str})"
                    )

                    for js in r.get("judge_scores") or []:
                        reason = js.get("reason", "")
                        if reason:
                            lines.append("")
                            lines.append(f"> {reason}")

                    lines.append("")

                if tags and "remediation" in tags:
                    phase_entries = [
                        entry for entry in amended_entries if entry["conversation_group_id"] == cid
                    ]
                    for label, condition_type in PHASE_CONDITIONS:
                        status = phase_status(phase_entries, cid, condition_type)
                        icon = "✅" if status == "Completed" else "❌"
                        lines.append(f"**{label}**: {icon} {status}")
                    lines.append("")

                # Analysis duration and tokens
                for entry in amended_entries:
                    if entry["conversation_group_id"] == cid and entry.get("analysis_duration") is not None:
                        lines.append(f"**Duration**: {format_duration(entry['analysis_duration'])}")
                        lines.append("")
                        break

                for entry in amended_entries:
                    if entry["conversation_group_id"] == cid:
                        inp = entry.get("agent_input_tokens")
                        out = entry.get("agent_output_tokens")
                        if inp is not None or out is not None:
                            lines.append(f"**Tokens**: in {inp or 0:,} out {out or 0:,}")
                            lines.append("")
                        break

                # Response
                response = None
                for entry in amended_entries:
                    if entry["conversation_group_id"] == cid and entry.get("response"):
                        response = entry["response"]
                        break

                errors = [
                    r["reason"] for r in conv_results
                    if r["result"] == "ERROR" and r.get("reason")
                ]
                response = append_outcome(response or "", errors)
                if response:
                    lines.append("````markdown")
                    lines.append(strip_request_section(response).strip())
                    lines.append("````")
                    lines.append("")

        lines.append("[Back to top](#evaluation-summary)")
        lines.append("")

    return "\n".join(lines)


def generate_report(eval_dir: Path, parallel_runs: str | None = None) -> str:
    progress = load_progress(eval_dir)
    agent_names = discover_agents(
        eval_dir,
        eval_dir / "system-ols-agentic.yaml"
        if (eval_dir / "system-ols-agentic.yaml").is_file()
        else Path(_SCRIPT_DIR).parent / "evals" / "system-ols-agentic.yaml"
    )

    # Load per-run data for each agent
    agent_runs: dict[str, list] = {}
    agent_amended: dict[str, list] = {}
    agent_run_dirs_map: dict[str, list[Path]] = {}
    for agent in agent_names:
        run_dirs = find_run_dirs(eval_dir, agent)
        agent_run_dirs_map[agent] = run_dirs
        runs = []
        amended = []
        for rd in run_dirs:
            runs.append(load_run_summary(rd))
            amended.append(load_amended_entries(rd))
        agent_runs[agent] = runs
        agent_amended[agent] = amended

    conversations = collect_conversations(agent_runs)
    scenario_names = load_scenario_names("evals-ols-agentic.yaml")
    repeat = max((len(find_run_dirs(eval_dir, a)) for a in agent_names), default=1)

    # Extract timestamp from first available summary JSON
    timestamp_str = ""
    for agent in agent_names:
        run_dirs = find_run_dirs(eval_dir, agent)
        for rd in run_dirs:
            files = sorted(rd.glob("*_summary.json"))
            if files:
                with open(files[0]) as f:
                    ts = json.load(f).get("timestamp", "")
                if ts:
                    timestamp_str = format_timestamp(ts)
                    break
        if timestamp_str:
            break

    judge = extract_judge_model(eval_dir, agent_names)

    # Build the report
    lines = ["# Evaluation Summary"]
    lines.append("")
    lines.append(format_report_metadata(
        "OLS Agentic",
        timestamp_str,
        len(conversations),
        len(agent_names),
        repeat,
        judge,
        parallel_runs=parallel_runs == "yes",
        config_link=True,
    ))
    lines.append("")

    if progress_line := format_progress(progress):
        lines.append(progress_line)
        lines.append("")

    # Overview table
    lines.append(generate_overview_table(
        conversations, agent_names, agent_runs, agent_amended
    ))
    lines.append("")

    # Results per scenario
    if failed_scenarios := format_failed_scenarios(progress):
        lines.append(failed_scenarios)
        lines.append("")

    lines.append("## Correctness")
    lines.append("")
    lines.append("Passed repeats / total repeats."
                 " Score: 0-1.00 (1.00 = perfect, 0.75 = minimum to pass)."
                 " Technical failures count as 0 in score averages.")
    lines.append("")
    lines.append(CORRECTNESS_LEGEND)
    lines.append("")
    lines.append(generate_summary_table(conversations, agent_names, agent_runs, scenario_names))
    lines.append("")

    remediation = remediation_conversations(conversations, agent_amended)
    if remediation:
        lines.append("## Correctness breakdown by Phase")
        lines.append("")
        lines.append("A = Analysis; E = Execution; V = Verification.")
        lines.append("")
        lines.append(generate_phase_breakdown_table(remediation, agent_names, agent_amended, scenario_names))
        lines.append("")

    # Duration per scenario
    lines.append("## Time")
    lines.append("")
    lines.append("Average duration across all repeats of a scenario per agent.")
    lines.append("")
    lines.append(generate_duration_table(conversations, agent_names, agent_amended, scenario_names))
    lines.append("")

    # Tokens per scenario
    lines.append("## Cost")
    lines.append("")
    lines.append("Average input/output token usage per evaluation.")
    lines.append("")
    lines.append(generate_tokens_table(conversations, agent_names, agent_amended, scenario_names))
    lines.append("")

    # Scenario details
    lines.append("# Scenarios")
    lines.append("")
    lines.append(
        generate_scenario_details(
            conversations, agent_names, agent_runs, agent_amended, agent_run_dirs_map, scenario_names
        )
    )

    lines.append(system_config_appendix(eval_dir, "system-ols-agentic.yaml"))

    return "\n".join(lines)


GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[0;33m"
RESET = "\033[0m"


def _scenario_pass_total(agent_runs: list, conversation_id: str) -> tuple[int, int]:
    passed = 0
    total = 0
    for results in agent_runs:
        if results is None:
            continue
        result, _ = get_performance_result(results, conversation_id)
        if result is not None:
            total += 1
            if result == "PASS":
                passed += 1
    return passed, total


def _colorize(passed: int, total: int, technical_failure: bool = False) -> str:
    text = f"{passed}/{total}"
    if not sys.stdout.isatty():
        return text + ("*" if technical_failure else "")
    if technical_failure:
        return f"{YELLOW}{text}{RESET}"
    if passed == total:
        return f"{GREEN}{text}{RESET}"
    if passed == 0:
        return f"{RED}{text}{RESET}"
    return text


def print_correctness_table(
    conversations: list[str],
    agent_names: list[str],
    agent_runs: dict[str, list],
    agent_amended: dict[str, list] | None = None,
    scenario_names: dict[str, str] | None = None,
) -> None:
    scenario_names = scenario_names or {}
    agent_amended = agent_amended or {}
    grid: list[list[tuple[int, int]]] = []
    for cid in conversations:
        row = [_scenario_pass_total(agent_runs[a], cid) for a in agent_names]
        grid.append(row)

    use_color = sys.stdout.isatty()
    technical_failures = {
        (cid, agent): any(
            results is not None and has_technical_failure(results, cid)
            for results in agent_runs[agent]
        )
        for cid in conversations
        for agent in agent_names
    }
    totals = [overall_score(agent_runs[a], conversations) for a in agent_names]
    avg_scores = [mean_score(agent_runs[a], conversations) for a in agent_names]
    avg_durations = [
        mean_duration(agent_amended.get(a, []), conversations)
        for a in agent_names
    ]
    avg_tokens = [
        format_token_pair(
            *mean_tokens(agent_amended.get(a, []), conversations)
        )
        for a in agent_names
    ]
    avg_score_cells = ["N/A" if score is None else f"{score:.2f}" for score in avg_scores]
    avg_duration_cells = [
        "N/A" if duration is None else format_duration(duration)
        for duration in avg_durations
    ]

    def _footer_plain(p, t):
        pct = round(100 * p / t) if t else 0
        return f"{pct}% ({p}/{t})"

    footer_labels = ["Pass rate", "Avg score", "Avg duration", "Avg tokens"]
    scenario_w = max(
        [len("Scenario"), *(len(label) for label in footer_labels)]
        + [len(scenario_names.get(c, c)) for c in conversations]
    )
    col_widths = []
    for index, (agent, total) in enumerate(zip(agent_names, totals, strict=True)):
        result_width = max(
            (
                len(f"{row[index][0]}/{row[index][1]}")
                + int(not use_color and technical_failures[cid, agent])
                for cid, row in zip(conversations, grid)
            ),
            default=0,
        )
        summary_width = max(
            len(avg_score_cells[index]),
            len(avg_duration_cells[index]),
            len(avg_tokens[index]),
        )
        col_widths.append(
            max(len(agent), result_width, len(_footer_plain(*total)), summary_width)
        )

    sep = "+-" + "-+-".join("-" * w for w in [scenario_w] + col_widths) + "-+"
    header = "| " + " | ".join(
        f"{h:<{w}}" for h, w in zip(["Scenario"] + agent_names, [scenario_w] + col_widths)
    ) + " |"

    print(sep)
    print(header)
    print(sep)
    for cid, row in zip(conversations, grid):
        cells = [f"{scenario_names.get(cid, cid):<{scenario_w}}"]
        for agent, (p, t), w in zip(agent_names, row, col_widths):
            plain = f"{p}/{t}"
            technical_failure = technical_failures[cid, agent]
            if technical_failure and not use_color:
                plain += "*"
            colored = _colorize(p, t, technical_failure)
            cells.append(f"{colored}{' ' * (w - len(plain))}")
        print("| " + " | ".join(cells) + " |")
    print(sep)
    footer_cells = [f"{'Pass rate':<{scenario_w}}"]
    for (p, t), w in zip(totals, col_widths):
        plain = _footer_plain(p, t)
        pct = round(100 * p / t) if t else 0
        colored = _colorize(p, t)
        text = f"{pct}% ({colored})"
        footer_cells.append(f"{text}{' ' * (w - len(plain))}")
    print("| " + " | ".join(footer_cells) + " |")
    for label, values in (
        ("Avg score", avg_score_cells),
        ("Avg duration", avg_duration_cells),
        ("Avg tokens", avg_tokens),
    ):
        cells = [f"{label:<{scenario_w}}"]
        cells.extend(f"{value:<{width}}" for value, width in zip(values, col_widths))
        print("| " + " | ".join(cells) + " |")
    print(sep)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Markdown report from NxM agentic evaluation output",
    )
    parser.add_argument(
        "eval_dir",
        help="Eval session directory containing {agent}/run_{N}/ subdirectories",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: EVAL_DIR/report.md)",
    )
    parser.add_argument(
        "--parallel-runs", choices=("yes", "no"),
        help="Whether evaluation runs were executed in parallel",
    )
    parser.add_argument("--quiet", action="store_true", help="Skip the console summary")
    args = parser.parse_args()

    eval_dir = Path(args.eval_dir)
    if not eval_dir.is_dir():
        print(f"ERROR: {eval_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    md = generate_report(eval_dir, args.parallel_runs)

    output = Path(args.output) if args.output else eval_dir / "report.md"
    write_atomic(output, md)
    if args.quiet:
        print(f"Report written to {output}")
        return

    agent_names = discover_agents(
        eval_dir,
        eval_dir / "system-ols-agentic.yaml"
        if (eval_dir / "system-ols-agentic.yaml").is_file()
        else Path(_SCRIPT_DIR).parent / "evals" / "system-ols-agentic.yaml"
    )
    agent_runs = {}
    agent_amended = {}
    for agent in agent_names:
        run_dirs = find_run_dirs(eval_dir, agent)
        agent_runs[agent] = [load_run_summary(rd) for rd in run_dirs]
        agent_amended[agent] = [load_amended_entries(rd) for rd in run_dirs]
    conversations = collect_conversations(agent_runs)
    scenario_names = load_scenario_names("evals-ols-agentic.yaml")

    print()
    print_correctness_table(conversations, agent_names, agent_runs, agent_amended, scenario_names)
    print()
    print(f"Report written to {output}")


if __name__ == "__main__":
    main()
