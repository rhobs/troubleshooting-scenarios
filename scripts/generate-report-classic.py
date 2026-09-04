#!/usr/bin/env python3
"""Generate a Markdown report from NxM OLS Classic evaluation output.

Reads the eval session directory produced by lightspeed-eval and
generates a comparative report across agents and runs.

Unlike agentic evals, classic evals use a single metric
(custom:answer_correctness) and derive duration from agent_latency
in the results JSON.

Usage:
    python3 generate-report-classic.py EVAL_DIR [--output FILE]

EVAL_DIR is the eval session directory
(e.g., results/ols-classic/20260904_124503/).
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

CORRECTNESS_METRIC = "custom:answer_correctness"


def discover_agents(eval_dir: Path) -> list[str]:
    """Discover agent names from subdirectories containing run_* dirs."""
    agents = []
    for child in sorted(eval_dir.iterdir()):
        if child.is_dir() and any(child.glob("run_*")):
            agents.append(child.name)
    return agents


def find_run_dirs(eval_dir: Path, agent_name: str) -> list[Path]:
    """Find run_N directories for an agent, sorted by index."""
    agent_dir = eval_dir / agent_name
    if not agent_dir.is_dir():
        return []
    dirs = sorted(agent_dir.glob("run_*"), key=lambda p: int(p.name.split("_")[1]))
    return dirs


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


def extract_judge_model(eval_dir: Path, agent_names: list[str]) -> str:
    """Extract the judge model name from the first available summary JSON."""
    for agent in agent_names:
        for rd in find_run_dirs(eval_dir, agent):
            for f in sorted(rd.glob("*_summary.json")):
                with open(f) as fh:
                    data = json.load(fh)
                config = data.get("configuration", {})
                judges = config.get("judge_panel", {}).get("judges", [])
                if not judges:
                    continue
                models = config.get("llm_pool", {}).get("models", {})
                model = models.get(judges[0], {}).get("model", "")
                if model:
                    return model
    return ""


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
            agent_tok = (turn.get("api_input_tokens") or 0) + (turn.get("api_output_tokens") or 0)

            entries.append({
                "conversation_group_id": cid,
                "description": entry.get("description", ""),
                "query": turn.get("query", ""),
                "response": turn.get("response", ""),
                "tags": tags,
                "agent_latency": turn.get("agent_latency"),
                "agent_tokens": agent_tok,
            })
    return entries


def collect_conversations(agent_runs: dict[str, list]) -> list[str]:
    """Collect ordered unique conversation IDs across all agents/runs."""
    seen = set()
    conversations = []
    for runs in agent_runs.values():
        for results in runs:
            if results is None:
                continue
            for r in results:
                cid = r["conversation_group_id"]
                if cid not in seen:
                    seen.add(cid)
                    conversations.append(cid)
    return conversations


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


def anchor_id(agent: str, conversation_id: str) -> str:
    return f"{agent}--{conversation_id}"


def score_cell(agent_runs: list, conversation_id: str, agent: str) -> str:
    scores = []
    for results in agent_runs:
        if results is None:
            continue
        score = get_score(results, conversation_id)
        result = get_result(results, conversation_id)
        if result is not None:
            scores.append((result, score))

    if not scores:
        return "N/A"

    anchor = anchor_id(agent, conversation_id)

    if len(scores) == 1:
        result, score = scores[0]
        icon = "✅" if result == "PASS" else "❌"
        score_str = f"{score:.2f}" if score is not None else "N/A"
        return f"[{icon} {score_str}](#{anchor})"

    passed = sum(1 for r, _ in scores if r == "PASS")
    total = len(scores)
    valid_scores = [s for _, s in scores if s is not None]
    avg = sum(valid_scores) / len(valid_scores) if valid_scores else None
    icon = "✅" if passed == total else ("❌" if passed == 0 else "")
    avg_str = f" ({avg:.2f})" if avg is not None else ""
    return f"[{icon} {passed}/{total}](#{anchor}){avg_str}"


def format_timestamp(timestamp: str) -> str:
    if not timestamp:
        return ""
    dt = datetime.fromisoformat(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_tokens(n: int) -> str:
    return f"{n:,}"


def format_tokens_compact(n: int) -> str:
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{v:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        v = n / 1_000
        return f"{v:.0f}K"
    return str(n)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"


def overall_score(agent_runs: list, conversations: list[str]) -> tuple[int, int]:
    passed = 0
    total = 0
    for results in agent_runs:
        if results is None:
            continue
        for cid in conversations:
            result = get_result(results, cid)
            if result is not None:
                total += 1
                if result == "PASS":
                    passed += 1
    return passed, total


def overall_score_cell(passed: int, total: int, bold: bool = False) -> str:
    if total == 0:
        return "N/A"
    pct = round(100 * passed / total)
    if passed == total:
        icon = "✅ "
    elif passed == 0:
        icon = "❌ "
    else:
        icon = ""
    text = f"{icon}{pct}% ({passed}/{total})"
    if bold:
        text = f"**{text}**"
    return text


def scenario_mean_score(agent_runs: list, conversation_id: str) -> float | None:
    scores = []
    for results in agent_runs:
        if results is None:
            continue
        s = get_score(results, conversation_id)
        if s is not None:
            scores.append(s)
    return sum(scores) / len(scores) if scores else None


def mean_score(agent_runs: list, conversations: list[str]) -> float | None:
    scores = []
    for results in agent_runs:
        if results is None:
            continue
        for cid in conversations:
            s = get_score(results, cid)
            if s is not None:
                scores.append(s)
    if not scores:
        return None
    return sum(scores) / len(scores)


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


def scenario_tokens(agent_amended: list, cid: str) -> int:
    total = 0
    for entries in agent_amended:
        for entry in entries:
            if entry["conversation_group_id"] == cid:
                total += entry.get("agent_tokens", 0)
    return total


def total_tokens(agent_amended: list, conversations: list[str]) -> int:
    total = 0
    for entries in agent_amended:
        for entry in entries:
            if entry["conversation_group_id"] in conversations:
                total += entry.get("agent_tokens", 0)
    return total


def mean_tokens(agent_amended: list, conversations: list[str]) -> int | None:
    tokens = []
    for entries in agent_amended:
        for entry in entries:
            if entry["conversation_group_id"] in conversations and entry.get("agent_tokens") is not None:
                tokens.append(entry["agent_tokens"])
    if not tokens:
        return None
    return round(sum(tokens) / len(tokens))


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
                text = f"**{text}**"
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
            if best_mean is not None and s == best_mean:
                text = f"**{text}**"
            cells.append(text)
    lines.append(f"| Avg score | {' | '.join(cells)} |")

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
            if best_lat is not None and d == best_lat:
                text = f"**{text}**"
            cells.append(text)
    lines.append(f"| Avg latency | {' | '.join(cells)} |")

    # Avg tokens
    avg_tok = {a: mean_tokens(agent_amended[a], conversations) for a in agent_names}
    cells = [format_tokens_compact(avg_tok[a]) if avg_tok[a] is not None else "N/A" for a in agent_names]
    lines.append(f"| Avg tokens | {' | '.join(cells)} |")

    return "\n".join(lines)


def generate_summary_table(
    conversations: list[str],
    agent_names: list[str],
    agent_runs: dict[str, list],
) -> str:
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
            if best is not None and avg_scores[a] is not None and avg_scores[a] == best:
                cell = f"**{cell}**"
            cells.append(cell)
        lines.append(f"| [{cid}](#{anchor}) | {' | '.join(cells)} |")
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
    return "\n".join(lines)


def generate_latency_table(
    conversations: list[str],
    agent_names: list[str],
    agent_runs: dict[str, list],
) -> str:
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
                if best is not None and d == best:
                    text = f"**{text}**"
                cells.append(text)
        cid_anchor = cid.lower().replace(" ", "-")
        lines.append(f"| [{cid}](#{cid_anchor}) | {' | '.join(cells)} |")

    mean_latencies = {a: mean_latency(agent_runs[a], conversations) for a in agent_names}
    best_mean = min((d for d in mean_latencies.values() if d is not None), default=None)
    cells = []
    for a in agent_names:
        d = mean_latencies[a]
        if d is None:
            cells.append("N/A")
        else:
            text = format_duration(d)
            if best_mean is not None and d == best_mean:
                text = f"**{text}**"
            cells.append(text)
    lines.append(f"| **Average** | {' | '.join(cells)} |")

    return "\n".join(lines)


def generate_tokens_table(
    conversations: list[str],
    agent_names: list[str],
    agent_amended: dict[str, list],
) -> str:
    header = "| Scenario | " + " | ".join(agent_names) + " |"
    separator = "|---|" + "|".join("---" for _ in agent_names) + "|"
    lines = [header, separator]
    for cid in conversations:
        cells = []
        for a in agent_names:
            t = scenario_tokens(agent_amended[a], cid)
            anc = anchor_id(a, cid)
            cells.append(f"[{format_tokens_compact(t)}](#{anc})")
        cid_anchor = cid.lower().replace(" ", "-")
        lines.append(f"| [{cid}](#{cid_anchor}) | {' | '.join(cells)} |")

    avg_tok = {a: mean_tokens(agent_amended[a], conversations) for a in agent_names}
    cells = [format_tokens_compact(avg_tok[a]) if avg_tok[a] is not None else "N/A" for a in agent_names]
    lines.append(f"| **Average** | {' | '.join(cells)} |")

    return "\n".join(lines)


def generate_scenario_details(
    conversations: list[str],
    agent_names: list[str],
    agent_runs: dict[str, list],
    agent_amended: dict[str, list],
) -> str:
    lines = []

    for cid in conversations:
        lines.append(f"## {cid}")
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

                conv_results = [r for r in results if r["conversation_group_id"] == cid]
                for r in conv_results:
                    result_icon = "✅" if r["result"] == "PASS" else "❌"
                    score_str = f"{r['score']:.2f}" if r["score"] is not None else "N/A"
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
                        lines.append(f"**Latency**: {format_duration(lat)}")
                        lines.append("")

                # Tokens
                for entry in amended_entries:
                    if entry["conversation_group_id"] == cid and entry.get("agent_tokens"):
                        lines.append(f"**Tokens**: {format_tokens(entry['agent_tokens'])}")
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


def generate_report(eval_dir: Path) -> str:
    agent_names = discover_agents(eval_dir)

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

    conversations = collect_conversations(agent_runs)
    repeat = max((len(find_run_dirs(eval_dir, a)) for a in agent_names), default=1)

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

    lines = ["# Evaluation Summary"]
    lines.append("")
    stats = (
        f"{len(conversations)} scenario{'s' if len(conversations) != 1 else ''}, "
        f"{len(agent_names)} agent{'s' if len(agent_names) != 1 else ''}, "
        f"{repeat} repeat{'s' if repeat > 1 else ''}"
    )
    parts = []
    if timestamp_str:
        parts.append(timestamp_str)
    parts.append(stats)
    if judge:
        parts.append(f"Judge: {judge}")
    lines.append(" | ".join(parts))
    lines.append("")

    lines.append(generate_overview_table(
        conversations, agent_names, agent_runs, agent_amended
    ))
    lines.append("")

    lines.append("## Correctness")
    lines.append("")
    lines.append("Passed repeats / total repeats."
                 " Score: 0-1.00 (1.00 = perfect, 0.75 = minimum to pass).")
    lines.append("")
    lines.append(generate_summary_table(conversations, agent_names, agent_runs))
    lines.append("")

    lines.append("## Latency")
    lines.append("")
    lines.append("Average agent latency across all repeats of a scenario per agent.")
    lines.append("")
    lines.append(generate_latency_table(conversations, agent_names, agent_runs))
    lines.append("")

    lines.append("## Cost")
    lines.append("")
    lines.append("Total token usage for each scenario across all repeats per agent;"
                 " the Average row shows average usage per evaluation.")
    lines.append("")
    lines.append(generate_tokens_table(conversations, agent_names, agent_amended))
    lines.append("")

    lines.append("# Scenarios")
    lines.append("")
    lines.append(
        generate_scenario_details(
            conversations, agent_names, agent_runs, agent_amended
        )
    )

    return "\n".join(lines)


GREEN = "\033[0;32m"
RED = "\033[0;31m"
RESET = "\033[0m"


def _scenario_pass_total(agent_runs: list, conversation_id: str) -> tuple[int, int]:
    passed = 0
    total = 0
    for results in agent_runs:
        if results is None:
            continue
        result = get_result(results, conversation_id)
        if result is not None:
            total += 1
            if result == "PASS":
                passed += 1
    return passed, total


def _colorize(passed: int, total: int) -> str:
    text = f"{passed}/{total}"
    if passed == total:
        return f"{GREEN}{text}{RESET}"
    if passed == 0:
        return f"{RED}{text}{RESET}"
    return text


def print_correctness_table(
    conversations: list[str],
    agent_names: list[str],
    agent_runs: dict[str, list],
) -> None:
    grid: list[list[tuple[int, int]]] = []
    for cid in conversations:
        row = [_scenario_pass_total(agent_runs[a], cid) for a in agent_names]
        grid.append(row)

    totals = [overall_score(agent_runs[a], conversations) for a in agent_names]

    def _footer_plain(p, t):
        pct = round(100 * p / t) if t else 0
        return f"{pct}% ({p}/{t})"

    scenario_w = max(len("Scenario"), len("Pass rate"), *(len(c) for c in conversations))
    col_widths = [
        max(len(a), max(len(f"{r[0]}/{r[1]}") for r in col_vals), len(_footer_plain(t[0], t[1])))
        for a, col_vals, t in zip(agent_names, zip(*grid), totals)
    ]

    sep = "+-" + "-+-".join("-" * w for w in [scenario_w] + col_widths) + "-+"
    header = "| " + " | ".join(
        f"{h:<{w}}" for h, w in zip(["Scenario"] + agent_names, [scenario_w] + col_widths)
    ) + " |"

    print(sep)
    print(header)
    print(sep)
    for cid, row in zip(conversations, grid):
        cells = [f"{cid:<{scenario_w}}"]
        for (p, t), w in zip(row, col_widths):
            plain = f"{p}/{t}"
            colored = _colorize(p, t)
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
    print(sep)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Markdown report from NxM OLS Classic evaluation output",
    )
    parser.add_argument(
        "eval_dir",
        help="Eval session directory containing {agent}/run_{N}/ subdirectories",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: EVAL_DIR/results.md)",
    )
    args = parser.parse_args()

    eval_dir = Path(args.eval_dir)
    if not eval_dir.is_dir():
        print(f"Error: {eval_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    md = generate_report(eval_dir)

    output = Path(args.output) if args.output else eval_dir / "results.md"
    output.write_text(md)

    agent_names = discover_agents(eval_dir)
    agent_runs = {}
    for agent in agent_names:
        agent_runs[agent] = [load_run_summary(rd) for rd in find_run_dirs(eval_dir, agent)]
    conversations = collect_conversations(agent_runs)

    print()
    print_correctness_table(conversations, agent_names, agent_runs)
    print()
    print(f"Report written to {output}")


if __name__ == "__main__":
    main()
