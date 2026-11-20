"""Shared helpers for the Chat and Agentic evaluation reports."""

import json
import re
from datetime import datetime
from pathlib import Path

import yaml

MEDAL = "🥇"
STATUS_METRIC = "custom:openshift_agentic_run_status"
CORRECTNESS_LEGEND = (
    "Legend: 🟢 100% pass rate · 🔴 0% pass rate · "
    "⚠️ Error in 1+ run (including setup errors or missing results)"
)


def has_technical_failure(results: list[dict], conversation_id: str) -> bool:
    """Check for an evaluation error or a failed completion check."""
    return any(
        metric["conversation_group_id"] == conversation_id
        and (
            metric["result"] == "ERROR"
            or (metric["metric_identifier"] == STATUS_METRIC and metric["result"] == "FAIL")
        )
        for metric in results
    )


def performance_result(
    results: list[dict], conversation_id: str, metric_ids: tuple[str, ...]
) -> tuple[str | None, float | None]:
    """Classify the run and keep any available correctness score."""
    selected = next((
        metric
        for metric_id in metric_ids
        for metric in results
        if metric["conversation_group_id"] == conversation_id
        and metric["metric_identifier"] == metric_id
        and metric.get("result") is not None
    ), None)
    score = None
    if (selected and selected["metric_identifier"] != STATUS_METRIC
            and selected["result"] in {"PASS", "FAIL"}):
        score = selected.get("score")
    if has_technical_failure(results, conversation_id):
        return "ERROR", score
    return (selected["result"], score) if selected else (None, None)


def correctness_icon(passed: int, total: int, technical_failure: bool) -> str:
    if technical_failure:
        return "⚠️"
    return "🟢" if passed == total else ("🔴" if passed == 0 else "")


def winner_cell(text: str, is_winner: bool) -> str:
    """Format a winning cell with a medal marker."""
    return f"**{text}** {MEDAL}" if is_winner else text


def is_best_score(score: float | None, best: float | None) -> bool:
    """Award tied scores a medal using the displayed two decimal places."""
    return score is not None and best is not None and f"{score:.2f}" == f"{best:.2f}"


def discover_agents(eval_dir: Path, system_config: Path | None = None) -> list[str]:
    """List agents in config order, then unknown agents in alphabetical order."""
    agents = []
    for child in sorted(eval_dir.iterdir()):
        if child.is_dir() and any(child.glob("run_*")):
            agents.append(child.name)
    progress_path = eval_dir / "progress.json"
    if progress_path.is_file():
        planned = json.loads(progress_path.read_text()).get("agents", [])
        agents = list(dict.fromkeys([*planned, *agents]))
    if system_config is None or not system_config.is_file():
        return agents
    config = yaml.safe_load(system_config.read_text()) or {}
    order = config.get("agents", {}).get("default", {}).get("agent", [])
    if isinstance(order, str):
        order = [order]
    ordered = list(dict.fromkeys(name for name in order if name in agents))
    return ordered + [name for name in agents if name not in ordered]


def find_run_dirs(eval_dir: Path, agent_name: str) -> list[Path]:
    """Find run_N directories for an agent, sorted by index."""
    agent_dir = eval_dir / agent_name
    if not agent_dir.is_dir():
        return []
    return sorted(agent_dir.glob("run_*"), key=lambda path: int(path.name.split("_")[1]))


def extract_report_timestamp(eval_dir: Path, agent_names: list[str]) -> str:
    """Read the report timestamp from the first available run summary."""
    for agent in agent_names:
        for run_dir in find_run_dirs(eval_dir, agent):
            for path in sorted(run_dir.glob("*_summary.json")):
                timestamp = json.loads(path.read_text()).get("timestamp", "")
                if timestamp:
                    return format_timestamp(timestamp)
    return ""


def extract_judge_model(eval_dir: Path, agent_names: list[str]) -> str:
    """Extract the judge model name from the first available summary JSON."""
    for agent in agent_names:
        for run_dir in find_run_dirs(eval_dir, agent):
            for path in sorted(run_dir.glob("*_summary.json")):
                with path.open() as file:
                    data = json.load(file)
                config = data.get("configuration", {})
                judges = config.get("judge_panel", {}).get("judges", [])
                if not judges:
                    continue
                models = config.get("llm_pool", {}).get("models", {})
                model = models.get(judges[0], {}).get("model", "")
                if model:
                    return model
    return ""


def collect_conversations(agent_runs: dict[str, list]) -> list[str]:
    """Collect ordered unique conversation IDs across all agents and runs."""
    seen = set()
    conversations = []
    for runs in agent_runs.values():
        for results in runs:
            if results is None:
                continue
            for result in results:
                cid = result["conversation_group_id"]
                if cid not in seen:
                    seen.add(cid)
                    conversations.append(cid)
    return conversations


def load_scenario_names(
    evals_filename: str, scenarios_dir: Path | None = None,
) -> dict[str, str]:
    """Map unique conversation IDs to paths relative to evals/scenarios."""
    if scenarios_dir is None:
        scenarios_dir = Path(__file__).resolve().parent.parent / "evals" / "scenarios"
    candidates: dict[str, set[str]] = {}
    for path in sorted(scenarios_dir.rglob(evals_filename)):
        entries = yaml.safe_load(path.read_text()) or []
        name = path.parent.relative_to(scenarios_dir).as_posix()
        for entry in entries:
            cid = entry["conversation_group_id"]
            candidates.setdefault(cid, set()).add(name)
    # Keep the original ID when more than one directory matches.
    return {cid: next(iter(names)) for cid, names in candidates.items() if len(names) == 1}


def anchor_id(agent: str, conversation_id: str) -> str:
    return f"{agent}--{conversation_id}"


def format_timestamp(timestamp: str) -> str:
    if not timestamp:
        return ""
    dt = datetime.fromisoformat(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_tokens_compact(number: int) -> str:
    if number >= 1_000_000:
        value = number / 1_000_000
        return f"{value:.1f}M".replace(".0M", "M")
    if number >= 1_000:
        value = number / 1_000
        return f"{value:.0f}K"
    return str(number)


def format_token_pair(input_tokens: int | None, output_tokens: int | None) -> str:
    if input_tokens is None and output_tokens is None:
        return "N/A"
    return (
        f"{format_tokens_compact(input_tokens or 0)}"
        f"/{format_tokens_compact(output_tokens or 0)}"
    )


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    return f"{minutes}m {remaining_seconds}s"


def overall_score_cell(passed: int, total: int, bold: bool = False) -> str:
    if total == 0:
        return "N/A"
    percentage = round(100 * passed / total)
    return winner_cell(f"{percentage}% ({passed}/{total})", bold)


def scenario_tokens(
    agent_amended: list, conversation_id: str
) -> tuple[int | None, int | None]:
    """Return mean input/output tokens for one scenario across runs."""
    inputs = []
    outputs = []
    for entries in agent_amended:
        for entry in entries:
            if entry["conversation_group_id"] != conversation_id:
                continue
            input_tokens = entry.get("agent_input_tokens")
            output_tokens = entry.get("agent_output_tokens")
            if input_tokens is not None:
                inputs.append(input_tokens)
            if output_tokens is not None:
                outputs.append(output_tokens)
    mean_input = round(sum(inputs) / len(inputs)) if inputs else None
    mean_output = round(sum(outputs) / len(outputs)) if outputs else None
    return mean_input, mean_output


def mean_tokens(
    agent_amended: list, conversations: list[str]
) -> tuple[int | None, int | None]:
    """Return mean input/output tokens across runs and conversations."""
    inputs = []
    outputs = []
    for entries in agent_amended:
        for entry in entries:
            if entry["conversation_group_id"] not in conversations:
                continue
            input_tokens = entry.get("agent_input_tokens")
            output_tokens = entry.get("agent_output_tokens")
            if input_tokens is not None:
                inputs.append(input_tokens)
            if output_tokens is not None:
                outputs.append(output_tokens)
    mean_input = round(sum(inputs) / len(inputs)) if inputs else None
    mean_output = round(sum(outputs) / len(outputs)) if outputs else None
    return mean_input, mean_output


def format_report_metadata(
    report_type: str,
    timestamp: str,
    scenario_count: int,
    agent_count: int,
    repeat_count: int,
    judge: str,
    parallel_runs: bool = False,
    config_link: bool = False,
    markdown: bool = True,
) -> str:
    """Format the report type, dimensions, timestamp, and optional judge."""
    stats = (
        f"{scenario_count} scenario{'s' if scenario_count != 1 else ''}, "
        f"{agent_count} agent{'s' if agent_count != 1 else ''}, "
        f"{repeat_count} repeat{'s' if repeat_count > 1 else ''}"
    )
    if parallel_runs:
        stats += " (parallel)"
    parts = [timestamp] if timestamp else []
    parts.extend((f"**{report_type}**" if markdown else report_type, stats))
    if judge:
        parts.append(f"Judge: {judge}")
    if config_link:
        parts.append("[System config](#system-config)")
    return " | ".join(parts)


def format_report_note(note: str) -> str:
    """Format the note as italic text inside a block quote."""
    paragraphs = re.split(r"\n(?:[ \t]*\n)+", note)
    text = "\n\n".join(f"_{paragraph}_" for paragraph in paragraphs)
    return "> Note: " + text.replace("\n", "\n> ")


def system_config_appendix(eval_dir: Path, filename: str) -> str:
    """Include the saved input YAML without substituting the current config."""
    lines = ["", '<a id="system-config"></a>', "## Appendix: System config", ""]
    path = eval_dir / filename
    if path.is_file():
        content = path.read_text()
        # Keep YAML comments containing Markdown fences inside the code block.
        fence = "```"
        while fence in content:
            fence += "`"
        lines.extend([
            f"Saved input file: `{filename}`. Run mode can override agent, repeat, and parallel settings.",
            "", f"{fence}yaml", content.rstrip("\n"), fence,
        ])
    else:
        lines.append("The original YAML was not saved for this session.")
    lines.extend(["", "[Back to top](#evaluation-summary)", ""])
    return "\n".join(lines)


SCORING_LEGEND = (
    "PASS: passed / finished runs.\n"
    "FAIL: failed quality checks without technical errors / finished runs.\n"
    "ERROR: technical errors, including setup errors and missing results / finished runs.\n"
    "Avg score: mean of available correctness scores (scored / finished runs).\n"
    "Pending runs are excluded from tables and totals."
)


class PlannedRuns(list):
    """Run results with the state of each missing planned result."""

    def __init__(self, runs, missing):
        super().__init__(runs)
        self.missing = missing


def prepare_planned_runs(
    eval_dir: Path,
    filename: str,
    agent_names: list[str],
    agent_runs: dict[str, list],
    agent_amended: dict[str, list],
) -> tuple[list[str], dict[str, str], int]:
    """Use saved session data to identify finished scenarios and repeats.

    Results and amended entries keep their original run numbers. No metric is
    created for a missing result. Old sessions use the available run data when
    the saved plan is not present.
    """
    progress_path = eval_dir / "progress.json"
    progress = json.loads(progress_path.read_text()) if progress_path.is_file() else {}
    config_path = eval_dir / filename.replace("evals-", "system-")
    config = (yaml.safe_load(config_path.read_text()) or {}) if config_path.is_file() else {}
    observed = collect_conversations(agent_runs)
    conversations = []
    names = load_scenario_names(filename, eval_dir / "scenarios")
    scenario_for = {}
    for scenario in progress.get("scenarios", []):
        path = eval_dir / scenario / filename
        entries = (yaml.safe_load(path.read_text()) or []) if path.is_file() else []
        ids = [entry["conversation_group_id"] for entry in entries]
        if not ids:
            ids = [scenario.removeprefix("scenarios/")]
        for cid in ids:
            scenario_for[cid] = scenario
            names[cid] = scenario.removeprefix("scenarios/")
            if cid not in conversations:
                conversations.append(cid)
    conversations.extend(cid for cid in observed if cid not in conversations)
    repeat = progress.get("repeat", config.get("agents", {}).get("default", {}).get("repeat", 0))
    repeat = max(int(repeat or 0), max((
        int(rd.name.split("_")[1])
        for agent in agent_names for rd in find_run_dirs(eval_dir, agent)
    ), default=0))
    for agent in agent_names:
        dirs = find_run_dirs(eval_dir, agent)
        runs = [None] * repeat
        amended = [[] for _ in range(repeat)]
        for rd, results, entries in zip(dirs, agent_runs[agent], agent_amended[agent]):
            index = int(rd.name.split("_")[1]) - 1
            runs[index] = results
            amended[index] = entries
        missing = {}
        for cid in conversations:
            for index in range(repeat):
                item = next((item for item in progress.get("items", [])
                             if item["scenario"] == scenario_for.get(cid)
                             and item.get("agent", agent) == agent
                             and item.get("run_index", index + 1) == index + 1), {})
                # A live report must not call unfinished work an error.
                pending = (item.get("state") == "pending"
                           or (progress.get("state") == "running"
                               and item.get("state", "pending") in {"pending", "running"}))
                missing[index, cid] = "PENDING" if pending else "ERROR"
        agent_runs[agent] = PlannedRuns(runs, missing)
        agent_amended[agent] = amended
    conversations = [cid for cid in conversations if any(
        any(
            any(metric["conversation_group_id"] == cid for metric in (results or []))
            or agent_runs[agent].missing[index, cid] != "PENDING"
            for index, results in enumerate(agent_runs[agent])
        )
        for agent in agent_names
    ) or (not agent_names and any(
        item["scenario"] == scenario_for.get(cid)
        and item.get("state") not in {"pending", "running"}
        for item in progress.get("items", [])
    ))]
    return conversations, names, repeat


def report_stats(runs, conversations, get_result):
    """Count finished outcomes and average available scores."""
    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0, "PENDING": 0}
    scores = []
    for index, results in enumerate(runs):
        for cid in conversations:
            result, score = get_result(results or [], cid)
            if result is None:
                result = getattr(runs, "missing", {}).get((index, cid), "ERROR")
            counts[result] += 1
            if score is not None:
                scores.append(score)
    return {
        **counts, "total": sum(counts[s] for s in ("PASS", "FAIL", "ERROR")), "scored": len(scores),
        "mean": sum(scores) / len(scores) if scores else None,
    }


def average_score_cell(stats: dict) -> str:
    value = f"{stats['mean']:.2f}" if stats["mean"] is not None else "N/A"
    return f"{value} ({stats['scored']}/{stats['total']})"


def summary_rows(conversations, agent_names, agent_runs, get_result, bold=False):
    """Build the same scoring rows for both Markdown summary tables."""
    stats = {a: report_stats(agent_runs[a], conversations, get_result) for a in agent_names}
    best_pass = max((s["PASS"] / s["total"] for s in stats.values() if s["total"]), default=None)
    best_mean = max((s["mean"] for s in stats.values() if s["mean"] is not None), default=None)
    lines = []
    for outcome in ("PASS", "FAIL", "ERROR"):
        cells = []
        for s in stats.values():
            winner = (outcome == "PASS" and bool(s["total"])
                      and s["PASS"] / s["total"] == best_pass)
            cells.append(overall_score_cell(s[outcome], s["total"], winner))
        label = outcome
        if bold:
            label = f"**{label}**"
        lines.append(f"| {label} | {' | '.join(cells)} |")
    cells = [winner_cell(average_score_cell(s), is_best_score(s["mean"], best_mean))
             for s in stats.values()]
    label = "**Avg score**" if bold else "Avg score"
    lines.append(f"| {label} | {' | '.join(cells)} |")
    return lines
