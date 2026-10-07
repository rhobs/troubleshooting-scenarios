#!/usr/bin/env python3
"""Print the same evaluation summary for previews and real runs."""

import argparse
import os
import sys

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required to show the evaluation summary.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Show an evaluation summary")
    parser.add_argument("--system-config", required=True)
    parser.add_argument("--setup-mode", choices=("run", "scenario", "skip"), required=True)
    parser.add_argument("--agents", nargs="+")
    parser.add_argument("--scenarios", nargs="*", required=True)
    args = parser.parse_args()

    with open(args.system_config, encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}

    agents_config = config.get("agents") or {}
    defaults = agents_config.get("default") or {}
    agent_names = args.agents if args.agents is not None else defaults.get("agent", [])
    repeat = defaults.get("repeat", 1)
    parallel = False if args.setup_mode == "run" else defaults.get("parallel", False)
    judge_ids = (config.get("judge_panel") or {}).get("judges") or []
    if isinstance(judge_ids, str):
        judge_ids = [judge_ids]
    llm_models = (config.get("llm_pool") or {}).get("models") or {}
    judge_models = [
        (llm_models.get(judge_id) or {}).get("model", "unknown")
        for judge_id in judge_ids
    ]
    judge = ", ".join(judge_models) or "not configured"

    # Display relative path from current directory (repo root)
    config_path = args.system_config
    try:
        config_path = os.path.relpath(config_path, os.getcwd())
    except ValueError:
        # If path can't be made relative (e.g., different drives on Windows), use as-is
        pass

    print(f"config:     {config_path}")
    print(f"setup_mode: {args.setup_mode}")
    print(f"repeats:    {repeat}")
    print(f"parallel:   {str(parallel).lower()}")
    print(f"judge:      {judge}")
    print(f"agents:     {len(agent_names)}")
    for name in agent_names:
        agent = agents_config.get(name) or {}
        print(f"  {agent.get('description') or name}")

    print(f"scenarios:  {len(args.scenarios)}")
    for scenario in args.scenarios:
        print(f"  {scenario.removeprefix('scenarios/')}")
    if not args.scenarios:
        print("No scenarios match the given filters.")


if __name__ == "__main__":
    main()
