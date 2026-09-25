#!/usr/bin/env python3
"""Convert lightspeed-eval summary JSON files to JUnit XML for Sippy ingestion.

This script extracts test results and token usage metrics from lightspeed-eval
summary JSON files and converts them to JUnit XML format for Sippy dashboard ingestion.

Token metrics are embedded as JUnit properties for cost tracking and analysis.
"""

import json
import sys
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString


SUITE_NAME = "troubleshooting-scenarios"


def add_token_properties(parent: Element, data: dict) -> None:
    """Add token usage metrics as JUnit properties.

    Extracts token counts from the eval summary and embeds them as JUnit properties
    for downstream analysis in Sippy dashboards and cost tracking tools.

    Args:
        parent: Parent XML element to attach properties to
        data: Eval summary JSON data containing token metrics
    """
    props = SubElement(parent, "properties")

    stats = data.get("summary_stats", {}).get("overall", {})
    config = data.get("configuration", {})

    # Overall token metrics from the eval run
    SubElement(props, "property", name="total_tokens",
               value=str(stats.get("total_tokens", 0)))
    SubElement(props, "property", name="total_api_input_tokens",
               value=str(stats.get("total_api_input_tokens", 0)))
    SubElement(props, "property", name="total_api_output_tokens",
               value=str(stats.get("total_api_output_tokens", 0)))
    SubElement(props, "property", name="total_judge_llm_input_tokens",
               value=str(stats.get("total_judge_llm_input_tokens", 0)))
    SubElement(props, "property", name="total_judge_llm_output_tokens",
               value=str(stats.get("total_judge_llm_output_tokens", 0)))
    SubElement(props, "property", name="total_embedding_tokens",
               value=str(stats.get("total_embedding_tokens", 0)))

    # LLM provider configuration
    # Extract judge LLM info from llm_pool.models using judge_panel.judges selection
    llm_pool = config.get("llm_pool", {})
    models = llm_pool.get("models", {})
    judge_panel = config.get("judge_panel", {})
    judges = judge_panel.get("judges", [])

    judge_provider = "unknown"
    judge_model = "unknown"
    if judges and len(judges) > 0:
        judge_name = judges[0]
        judge_config = models.get(judge_name, {})
        judge_provider = judge_config.get("provider", "unknown")
        judge_model = judge_config.get("model", "unknown")

    SubElement(props, "property", name="judge_llm_provider", value=judge_provider)
    SubElement(props, "property", name="judge_llm_model", value=judge_model)

    # Agent info is not available in summary JSON, default to OLS
    # TODO: Pass agent provider/model from CI caller when available
    SubElement(props, "property", name="agent_llm_provider", value="openshift-lightspeed")
    SubElement(props, "property", name="agent_llm_model", value="unknown")

    # Timestamp and eval metadata
    SubElement(props, "property", name="eval_timestamp",
               value=data.get("timestamp", ""))
    SubElement(props, "property", name="total_evaluations",
               value=str(data.get("total_evaluations", 0)))


def add_testcase_properties(tc: Element, result: dict) -> None:
    """Add per-test token metrics as properties.

    Args:
        tc: Testcase XML element
        result: Individual test result from eval summary
    """
    tc_props = SubElement(tc, "properties")

    # Per-test token usage
    SubElement(tc_props, "property", name="api_input_tokens",
               value=str(result.get("api_input_tokens", 0)))
    SubElement(tc_props, "property", name="api_output_tokens",
               value=str(result.get("api_output_tokens", 0)))
    SubElement(tc_props, "property", name="judge_llm_input_tokens",
               value=str(result.get("judge_llm_input_tokens", 0)))
    SubElement(tc_props, "property", name="judge_llm_output_tokens",
               value=str(result.get("judge_llm_output_tokens", 0)))
    SubElement(tc_props, "property", name="embedding_tokens",
               value=str(result.get("embedding_tokens", 0)))

    # Test metadata
    tag = result.get("tag", "")
    if tag:
        SubElement(tc_props, "property", name="scenario_tag", value=tag)

    # Performance metrics
    agent_latency = result.get("agent_latency")
    if agent_latency is not None:
        SubElement(tc_props, "property", name="agent_latency_seconds",
                   value=f"{agent_latency:.3f}")

    eval_latency = result.get("evaluation_latency")
    if eval_latency is not None:
        SubElement(tc_props, "property", name="evaluation_latency_seconds",
                   value=f"{eval_latency:.3f}")


def build_junit(summary_files: list[Path]) -> Element:
    """Build a JUnit XML tree from one or more eval summary JSON files.

    Converts eval results to JUnit format with embedded token metrics for Sippy ingestion.

    Args:
        summary_files: List of paths to evaluation_*_summary.json files

    Returns:
        Root testsuites XML element
    """
    testsuites = Element("testsuites")

    for path in sorted(summary_files):
        with open(path) as f:
            data = json.load(f)

        results = data.get("results") or []
        if not results:
            continue

        suite = SubElement(testsuites, "testsuite", name=SUITE_NAME)

        # Add token usage metrics at suite level
        add_token_properties(suite, data)

        failures = 0
        errors = 0

        for r in results:
            scenario = r.get("conversation_group_id", "unknown")
            metric = r.get("metric_identifier", "unknown")
            name = f"{scenario}/{metric}"

            tc = SubElement(suite, "testcase", name=name, classname=scenario)

            # Add per-test token metrics and metadata
            add_testcase_properties(tc, r)

            status = r.get("result", "ERROR")
            score = r.get("score")
            reason = ""
            judges = r.get("judge_scores") or []
            if judges:
                reason = judges[0].get("reason", "")

            if status == "ERROR":
                errors += 1
                SubElement(tc, "error", message=f"score={score}").text = reason
            elif status == "FAIL":
                failures += 1
                SubElement(tc, "failure", message=f"score={score}").text = reason
            elif status == "SKIPPED":
                SubElement(tc, "skipped")

            exec_time = r.get("execution_time")
            if exec_time is not None:
                tc.set("time", f"{exec_time:.3f}")

        suite.set("tests", str(len(results)))
        suite.set("failures", str(failures))
        suite.set("errors", str(errors))

    return testsuites


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <output.xml> <summary.json> [summary2.json ...]", file=sys.stderr)
        sys.exit(1)

    output_path = Path(sys.argv[1])
    summary_files = [Path(p) for p in sys.argv[2:]]

    for p in summary_files:
        if not p.exists():
            print(f"Warning: {p} not found, skipping", file=sys.stderr)

    existing = [p for p in summary_files if p.exists()]
    if not existing:
        print("No summary files found, skipping JUnit generation", file=sys.stderr)
        sys.exit(0)

    tree = build_junit(existing)
    raw = tostring(tree, encoding="unicode", xml_declaration=True)
    pretty = parseString(raw).toprettyxml(indent="  ", encoding="UTF-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pretty)
    print(f"JUnit XML written to {output_path}")


if __name__ == "__main__":
    main()
