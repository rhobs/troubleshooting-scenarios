#!/usr/bin/env python3
"""Generate a Markdown report from NxM OLS Chat evaluation output.

Reads the eval session directory produced by lightspeed-eval and
generates a comparative report across agents and runs.

Unlike agentic evals, chat evals use a single metric
(custom:answer_correctness) and derive duration from agent_latency
in the results JSON.

Usage:
    python3 generate-report-chat.py EVAL_DIR [--output FILE] [--parallel-runs yes|no]

EVAL_DIR is the eval session directory
(e.g., results/ols-chat/20260904_124503/).
"""

import json
import sys
from pathlib import Path

import yaml

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from report_common import (  # noqa: E402
    CORRECTNESS_LEGEND,
    SCORING_LEGEND,
    prepare_planned_runs,
    report_stats,
    summary_rows,
    average_score_cell,
    correctness_icon,
    performance_result,
    anchor_id,
    collect_conversations as collect_conversations,
    load_scenario_names,
    discover_agents,
    extract_judge_model,
    extract_report_timestamp,
    find_run_dirs,
    format_duration,
    format_report_metadata,
    format_report_note,
    format_token_pair,
    mean_tokens,
    scenario_tokens,
    winner_cell,
    is_best_score,
    system_config_appendix,
)

from report_progress import format_failed_scenarios, format_progress, load_progress, write_atomic  # noqa: E402

CORRECTNESS_METRIC = "custom:answer_correctness"


def load_run_summary(run_dir: Path) -> list[dict] | None:
    """Load results from all summary JSONs in a run directory."""
    files = sorted(run_dir.glob("*_summary.json"))
    if not files:
        return None
    results = []
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        results.extend(data.get("results", []))
    return results


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
            agent_input_tok = turn.get("api_input_tokens")
            agent_output_tok = turn.get("api_output_tokens")

            entries.append({
                "conversation_group_id": cid,
                "description": entry.get("description", ""),
                "query": turn.get("query", ""),
                "response": turn.get("response", ""),
                "tags": tags,
                "agent_latency": turn.get("agent_latency"),
                "agent_input_tokens": agent_input_tok,
                "agent_output_tokens": agent_output_tok,
            })
    return entries


def get_score(results: list[dict], conversation_id: str) -> float | None:
    for r in results:
        if r["conversation_group_id"] == conversation_id and r["metric_identifier"] == CORRECTNESS_METRIC:
            return r.get("score")
    return None


def get_result(results: list[dict], conversation_id: str) -> str | None:
    for r in results:
        if r["conversation_group_id"] == conversation_id and r["metric_identifier"] == CORRECTNESS_METRIC:
            return r.get("result")
    return None


def get_judge_reason(results: list[dict], conversation_id: str) -> str:
    for r in results:
        if r["conversation_group_id"] == conversation_id and r["metric_identifier"] == CORRECTNESS_METRIC:
            for js in r.get("judge_scores") or []:
                reason = js.get("reason", "")
                if reason:
                    return reason
    return ""


def get_agent_latency(results: list[dict], conversation_id: str) -> float | None:
    for r in results:
        if r["conversation_group_id"] == conversation_id and r["metric_identifier"] == CORRECTNESS_METRIC:
            return r.get("agent_latency")
    return None


def get_performance_result(
    results: list[dict], conversation_id: str
) -> tuple[str | None, float | None]:
    """Return the run outcome and any available correctness score."""
    return performance_result(results, conversation_id, (CORRECTNESS_METRIC,))


def score_cell(agent_runs: list, conversation_id: str, agent: str) -> str:
    stats = report_stats(agent_runs, [conversation_id], get_performance_result)
    if not stats["total"]:
        return "N/A"
    icon = correctness_icon(stats["PASS"], stats["total"], bool(stats["ERROR"]))
    label = f"{icon} {stats['PASS']}/{stats['total']}".strip()
    avg = f" ({stats['mean']:.2f})" if stats["mean"] is not None else ""
    return f"[{label}](#{anchor_id(agent, conversation_id)}){avg}"


def overall_score(agent_runs: list, conversations: list[str]) -> tuple[int, int]:
    stats = report_stats(agent_runs, conversations, get_performance_result)
    return stats["PASS"], stats["total"]


def scenario_mean_score(agent_runs: list, conversation_id: str) -> float | None:
    return mean_score(agent_runs, [conversation_id])


def mean_score(agent_runs: list, conversations: list[str]) -> float | None:
    return report_stats(agent_runs, conversations, get_performance_result)["mean"]


def scenario_latency(agent_runs: list, conversation_id: str) -> float | None:
    """Mean agent_latency for a single scenario across runs."""
    latencies = []
    for results in agent_runs:
        if results is None:
            continue
        lat = get_agent_latency(results, conversation_id)
        if lat is not None:
            latencies.append(lat)
    return sum(latencies) / len(latencies) if latencies else None


def mean_latency(agent_runs: list, conversations: list[str]) -> float | None:
    latencies = []
    for results in agent_runs:
        if results is None:
            continue
        for cid in conversations:
            lat = get_agent_latency(results, cid)
            if lat is not None:
                latencies.append(lat)
    if not latencies:
        return None
    return sum(latencies) / len(latencies)


def generate_overview_table(
    conversations: list[str],
    agent_names: list[str],
    agent_runs: dict[str, list],
    agent_amended: dict[str, list],
) -> str:
    header = "| | " + " | ".join(agent_names) + " |"
    separator = "|---|" + "|".join("---" for _ in agent_names) + "|"
    lines = [header, separator]

    lines.extend(summary_rows(conversations, agent_names, agent_runs, get_performance_result))

    # Mean latency
    mean_latencies = {a: mean_latency(agent_runs[a], conversations) for a in agent_names}
    best_lat = min((d for d in mean_latencies.values() if d is not None), default=None)
    cells = []
    for a in agent_names:
        d = mean_latencies[a]
        if d is None:
            cells.append("N/A")
        else:
            text = format_duration(d)
            cells.append(winner_cell(text, best_lat is not None and d == best_lat))
    lines.append(f"| Avg duration | {' | '.join(cells)} |")

    # Avg tokens
    avg_tok = {a: mean_tokens(agent_amended[a], conversations) for a in agent_names}
    cells = [format_token_pair(*avg_tok[a]) for a in agent_names]
    lines.append(f"| Avg tokens | {' | '.join(cells)} |")

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
            cell = winner_cell(cell, is_best_score(avg_scores[a], best))
            cells.append(cell)
        lines.append(f"| [{scenario_names.get(cid, cid)}](#{anchor}) | {' | '.join(cells)} |")
    lines.extend(summary_rows(
        conversations, agent_names, agent_runs, get_performance_result, bold=True,
    ))
    return "\n".join(lines)


def generate_duration_table(
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
        latencies = {a: scenario_latency(agent_runs[a], cid) for a in agent_names}
        best = min((d for d in latencies.values() if d is not None), default=None)
        cells = []
        for a in agent_names:
            d = latencies[a]
            if d is None:
                cells.append("N/A")
            else:
                anc = anchor_id(a, cid)
                text = f"[{format_duration(d)}](#{anc})"
                cells.append(winner_cell(text, best is not None and d == best))
        cid_anchor = cid.lower().replace(" ", "-")
        lines.append(f"| [{scenario_names.get(cid, cid)}](#{cid_anchor}) | {' | '.join(cells)} |")

    mean_latencies = {a: mean_latency(agent_runs[a], conversations) for a in agent_names}
    best_mean = min((d for d in mean_latencies.values() if d is not None), default=None)
    cells = []
    for a in agent_names:
        d = mean_latencies[a]
        if d is None:
            cells.append("N/A")
        else:
            text = format_duration(d)
            cells.append(winner_cell(text, best_mean is not None and d == best_mean))
    lines.append(f"| **Average** | {' | '.join(cells)} |")

    return "\n".join(lines)


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
        cells = []
        for a in agent_names:
            inp, out = scenario_tokens(agent_amended[a], cid)
            anc = anchor_id(a, cid)
            cells.append(f"[{format_token_pair(inp, out)}](#{anc})")
        cid_anchor = cid.lower().replace(" ", "-")
        lines.append(f"| [{scenario_names.get(cid, cid)}](#{cid_anchor}) | {' | '.join(cells)} |")

    avg_tok = {a: mean_tokens(agent_amended[a], conversations) for a in agent_names}
    cells = [format_token_pair(*avg_tok[a]) for a in agent_names]
    lines.append(f"| **Average** | {' | '.join(cells)} |")

    return "\n".join(lines)


def generate_scenario_details(
    conversations: list[str],
    agent_names: list[str],
    agent_runs: dict[str, list],
    agent_amended: dict[str, list],
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

        for agent in agent_names:
            runs = agent_runs[agent]
            amended_runs = agent_amended[agent]
            total_runs = len(runs)

            for run_idx, (results, amended_entries) in enumerate(zip(runs, amended_runs)):
                results = results or []

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

                conv_results = [r for r in results if r["conversation_group_id"] == cid]
                if not conv_results:
                    state = getattr(runs, "missing", {}).get((run_idx, cid), "ERROR")
                    lines.extend([f"**Result**: {state}. No evaluation result is available.", ""])
                for r in conv_results:
                    result_icon = "✅" if r["result"] == "PASS" else "⚠️"
                    score = r.get("score")
                    score_str = f"{score:.2f}" if score is not None else "N/A"
                    lines.append(
                        f"**Correctness**: "
                        f"{result_icon} {r['result']} (score: {score_str})"
                    )

                    for js in r.get("judge_scores") or []:
                        reason = js.get("reason", "")
                        if reason:
                            lines.append("")
                            lines.append(f"> {reason}")

                    lines.append("")

                    lat = r.get("agent_latency")
                    if lat is not None:
                        lines.append(f"**Duration**: {format_duration(lat)}")
                        lines.append("")

                # Tokens
                for entry in amended_entries:
                    if entry["conversation_group_id"] == cid:
                        inp = entry.get("agent_input_tokens")
                        out = entry.get("agent_output_tokens")
                        if inp is not None or out is not None:
                            lines.append(f"**Tokens**: in {inp or 0:,} out {out or 0:,}")
                            lines.append("")
                        break

                response = None
                for entry in amended_entries:
                    if entry["conversation_group_id"] == cid and entry.get("response"):
                        response = entry["response"]
                        break

                if response:
                    lines.append("````markdown")
                    lines.append(response.strip())
                    lines.append("````")
                    lines.append("")

        lines.append("[Back to top](#evaluation-summary)")
        lines.append("")

    return "\n".join(lines)


def generate_report(eval_dir: Path, parallel_runs: str | None = None) -> str:
    progress = load_progress(eval_dir)
    agent_names = discover_agents(
        eval_dir,
        eval_dir / "system-ols-chat.yaml"
        if (eval_dir / "system-ols-chat.yaml").is_file()
        else Path(_SCRIPT_DIR).parent / "evals" / "system-ols-chat.yaml"
    )

    agent_runs: dict[str, list] = {}
    agent_amended: dict[str, list] = {}
    for agent in agent_names:
        run_dirs = find_run_dirs(eval_dir, agent)
        runs = []
        amended = []
        for rd in run_dirs:
            runs.append(load_run_summary(rd))
            amended.append(load_amended_entries(rd))
        agent_runs[agent] = runs
        agent_amended[agent] = amended

    conversations, saved_names, repeat = prepare_planned_runs(
        eval_dir, "evals-ols-chat.yaml", agent_names, agent_runs, agent_amended,
    )
    scenario_names = load_scenario_names("evals-ols-chat.yaml")
    scenario_names.update(saved_names)

    timestamp_str = extract_report_timestamp(eval_dir, agent_names)
    judge = extract_judge_model(eval_dir, agent_names)

    lines = ["# Evaluation Summary"]
    lines.append("")
    lines.append(format_report_metadata(
        "OLS Chat",
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

    if note := (progress or {}).get("note", ""):
        lines.append(format_report_note(note))
        lines.append("")

    lines.append(generate_overview_table(
        conversations, agent_names, agent_runs, agent_amended
    ))
    lines.append("")

    if failed_scenarios := format_failed_scenarios(progress):
        lines.append(failed_scenarios)
        lines.append("")

    lines.append("## Correctness")
    lines.append("")
    lines.append(SCORING_LEGEND)
    lines.append("")
    lines.append(CORRECTNESS_LEGEND)
    lines.append("")
    lines.append(generate_summary_table(conversations, agent_names, agent_runs, scenario_names))
    lines.append("")

    lines.append("## Duration")
    lines.append("")
    lines.append("Average duration across all repeats of a scenario per agent.")
    lines.append("")
    lines.append(generate_duration_table(conversations, agent_names, agent_runs, scenario_names))
    lines.append("")

    lines.append("## Tokens")
    lines.append("")
    lines.append("Average input/output token usage per evaluation.")
    lines.append("")
    lines.append(generate_tokens_table(conversations, agent_names, agent_amended, scenario_names))
    lines.append("")

    lines.append("# Scenarios")
    lines.append("")
    lines.append(
        generate_scenario_details(
            conversations, agent_names, agent_runs, agent_amended, scenario_names
        )
    )

    lines.append(system_config_appendix(eval_dir, "system-ols-chat.yaml"))

    return "\n".join(lines)


GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[0;33m"
BRIGHT_WHITE = "\033[97m"
RESET = "\033[0m"


def _scenario_pass_total(agent_runs: list, conversation_id: str) -> tuple[int, int]:
    return overall_score(agent_runs, [conversation_id])


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
    scenario_stats = {
        (cid, agent): report_stats(agent_runs[agent], [cid], get_performance_result)
        for cid in conversations for agent in agent_names
    }
    technical_failures = {key: bool(value["ERROR"]) for key, value in scenario_stats.items()}
    stats = [report_stats(agent_runs[a], conversations, get_performance_result) for a in agent_names]
    totals = [(s["PASS"], s["total"]) for s in stats]
    avg_durations = [mean_latency(agent_runs[a], conversations) for a in agent_names]
    avg_tokens = [
        format_token_pair(
            *mean_tokens(agent_amended.get(a, []), conversations)
        )
        for a in agent_names
    ]
    avg_score_cells = [average_score_cell(s) for s in stats]
    avg_duration_cells = [
        "N/A" if duration is None else format_duration(duration)
        for duration in avg_durations
    ]

    def _footer_plain(p, t):
        pct = round(100 * p / t) if t else 0
        return f"{pct}% ({p}/{t})"

    footer_labels = ["PASS", "FAIL", "ERROR", "Avg score", "Avg duration", "Avg tokens"]
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
            max(len(agent), result_width, summary_width, *(
                len(_footer_plain(stats[index][outcome], total[1]))
                for outcome in ("PASS", "FAIL", "ERROR")
            ))
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
    for outcome in ("PASS", "FAIL", "ERROR"):
        footer_cells = [f"{outcome:<{scenario_w}}"]
        for s, w in zip(stats, col_widths):
            plain = _footer_plain(s[outcome], s["total"]) if s["total"] else "N/A"
            text = plain
            if use_color and outcome in {"FAIL", "ERROR"} and s[outcome] > 0:
                color = YELLOW if outcome == "ERROR" else RED
                text = f"{color}{plain}{RESET}"
            footer_cells.append(f"{text}{' ' * (w - len(plain))}")
        print("| " + " | ".join(footer_cells) + " |")
    for label, values in (
        ("Avg score", avg_score_cells),
        ("Avg duration", avg_duration_cells),
        ("Avg tokens", avg_tokens),
    ):
        cells = [f"{label:<{scenario_w}}"]
        for value, width in zip(values, col_widths):
            text = value
            if use_color and label == "Avg score" and not value.startswith("N/A"):
                text = f"{BRIGHT_WHITE}{value}{RESET}"
            cells.append(f"{text}{' ' * (width - len(value))}")
        print("| " + " | ".join(cells) + " |")
    print(sep)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Markdown report from NxM OLS Chat evaluation output",
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
        eval_dir / "system-ols-chat.yaml"
        if (eval_dir / "system-ols-chat.yaml").is_file()
        else Path(_SCRIPT_DIR).parent / "evals" / "system-ols-chat.yaml"
    )
    agent_runs = {}
    agent_amended = {}
    for agent in agent_names:
        run_dirs = find_run_dirs(eval_dir, agent)
        agent_runs[agent] = [load_run_summary(rd) for rd in run_dirs]
        agent_amended[agent] = [load_amended_entries(rd) for rd in run_dirs]
    conversations, saved_names, repeat = prepare_planned_runs(
        eval_dir, "evals-ols-chat.yaml", agent_names, agent_runs, agent_amended,
    )
    scenario_names = load_scenario_names("evals-ols-chat.yaml")
    scenario_names.update(saved_names)

    print()
    print(format_report_metadata(
        "OLS Chat",
        extract_report_timestamp(eval_dir, agent_names),
        len(conversations),
        len(agent_names),
        repeat,
        extract_judge_model(eval_dir, agent_names),
        parallel_runs=args.parallel_runs == "yes",
        markdown=False,
    ))
    print()
    print_correctness_table(conversations, agent_names, agent_runs, agent_amended, scenario_names)
    print()
    print(f"Report written to {output}")


if __name__ == "__main__":
    main()
