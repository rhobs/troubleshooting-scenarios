"""Track evaluation progress and write reports without losing the last copy."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile


PROGRESS_FILE = "progress.json"
FINISHED_STATES = {"completed", "error", "skipped"}


def write_atomic(path: Path, content: str) -> None:
    """Replace a file only after the new content has been written."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_progress(eval_dir: Path) -> dict | None:
    path = eval_dir / PROGRESS_FILE
    return json.loads(path.read_text()) if path.is_file() else None


def format_progress(progress: dict | None) -> str:
    """Add one progress line only while the report is partial."""
    if progress is None or progress["state"] == "completed":
        return ""
    states = {scenario: [] for scenario in progress["scenarios"]}
    for item in progress["items"]:
        states[item["scenario"]].append(item["state"])
    finished = sum(
        bool(items) and all(state in FINISHED_STATES for state in items)
        for items in states.values()
    )
    return f"Partial results: scenario {finished}/{len(states)}."


def format_failed_scenarios(progress: dict | None) -> str:
    """List scenarios whose runs all failed or were skipped after a setup error."""
    if progress is None:
        return ""
    scenarios = {}
    for item in progress["items"]:
        scenarios.setdefault(item["scenario"], []).append(item)
    lines = []
    for scenario, items in scenarios.items():
        if not all(item["state"] in {"error", "skipped"} for item in items):
            continue
        details = list(dict.fromkeys(
            item["detail"].replace("\n", " ") for item in items if item.get("detail")
        ))
        reason = "; ".join(details) or "No scenario run completed."
        name = scenario.removeprefix("scenarios/")
        lines.append(f"- `{name}`: {reason}")
    if not lines:
        return ""
    return "**Scenarios that failed completely:**\n\n" + "\n".join(lines)


def update_progress(args: argparse.Namespace) -> None:
    path = Path(args.eval_dir) / PROGRESS_FILE
    if args.action == "init":
        items = []
        for scenario in args.scenarios:
            if args.setup_mode == "run":
                for agent in args.agents:
                    for index in range(1, args.repeat + 1):
                        items.append({
                            "scenario": scenario, "agent": agent,
                            "run_index": index, "state": "pending",
                        })
            else:
                items.append({"scenario": scenario, "state": "pending"})
        progress = {
            "state": "running", "setup_mode": args.setup_mode,
            "scenarios": args.scenarios, "agents": args.agents,
            "repeat": args.repeat, "items": items,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        progress = load_progress(Path(args.eval_dir))
        if progress is None:
            raise ValueError("No evaluation progress file found")
        if args.action == "finalize":
            progress["exit_code"] = args.exit_code
            progress["state"] = (
                "completed" if args.finished else
                "interrupted" if args.exit_code in (130, 143) else "failed"
            )
            for item in progress["items"]:
                if item["state"] == "running":
                    item["state"] = "interrupted" if progress["state"] == "interrupted" else "error"
                    item["detail"] = f"Runner stopped (exit {args.exit_code})"
        else:
            matches = [
                item for item in progress["items"]
                if item["scenario"] == args.scenario
                and (args.agent is None or item.get("agent") == args.agent)
                and (args.run_index is None or item.get("run_index") == args.run_index)
            ]
            if not matches:
                raise ValueError(f"No progress entry for {args.scenario}")
            for item in matches:
                item["state"] = {
                    "start": "running", "skip": "skipped",
                    "finish": "error" if args.exit_code else "completed",
                }[args.action]
                item["detail"] = args.detail
    write_atomic(path, json.dumps(progress, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Save evaluation progress")
    parser.add_argument("action", choices=("init", "start", "finish", "skip", "finalize"))
    parser.add_argument("eval_dir")
    parser.add_argument("scenario", nargs="?")
    parser.add_argument("--scenarios", nargs="+", default=[])
    parser.add_argument("--agents", nargs="*", default=[])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--setup-mode", choices=("scenario", "run", "skip"), default="scenario")
    parser.add_argument("--agent")
    parser.add_argument("--run-index", type=int)
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--detail", default="")
    parser.add_argument("--finished", action="store_true")
    update_progress(parser.parse_args())


if __name__ == "__main__":
    main()
