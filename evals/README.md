# Evals

Fault scenarios for OpenShift troubleshooting. Automated evaluations use
[lightspeed-evaluation](https://github.com/lightspeed-core/lightspeed-evaluation)
to query the tool under test and score its response. You can also deploy the
faults for manual investigation. See the [scenario catalog](scenarios/README.md)
for scenarios grouped by difficulty and links to scenario groups.

## Running a scenario manually

From the repository root:

```bash
make setup-scenario SCENARIO=blocked_deployment
# Investigate the fault.
make cleanup-scenario SCENARIO=blocked_deployment
```

For a single scenario without group dependencies, you can also run its
`setup.sh` and `cleanup.sh` from the scenario directory.

## Running automated evals

Follow the [root README](../README.md) to set up OLS Agentic or OLS Classic.
Run Make commands from the repository root.

| Option | Purpose |
|--------|---------|
| `SCENARIO=a,b` | Select named scenarios supported by the eval mode. |
| `TAG=core,alert` | Select scenarios with at least one of these tags. |
| `PREVIEW=1` | Show the selection without running setup, evaluation, or cleanup. |
| `SETUP_MODE=scenario` | Control when resources are set up and removed; see below. |

Both eval targets and the manual `setup-scenario` and `cleanup-scenario` targets
require `SCENARIO`, `TAG`, or both, including with `PREVIEW=1`. Without a filter,
Make stops before setup or evaluation starts. With both `SCENARIO` and `TAG`,
tags filter the named scenarios.

```bash
make eval-ols-agentic TAG=core PREVIEW=1
make eval-ols-agentic TAG=investigation PREVIEW=1
make eval-ols-agentic TAG=remediation SETUP_MODE=run
make eval-ols-classic TAG=difficulty_medium PREVIEW=1
make eval-ols-agentic SCENARIO=blocked_deployment,refused_service
make eval-ols-classic SCENARIO=crashlooping_pod_alert PREVIEW=1
```

The preview and real run show the same summary: setup mode, repeat count,
effective parallel setting, judge, agents, and scenarios. Preview needs no
cluster connection or eval environment. Without Python 3 or PyYAML, config
values appear as placeholders.

Before a real run, both runners check cluster access, evaluation tools, and
`EVAL_OPENAI_API_KEY`. Agentic also checks that Agent CRs match the config;
Classic checks its operator CRD and server deployment.

### Setup modes

| Mode | Setup and cleanup | Parallel runs |
|------|-------------------|---------------|
| `scenario` (default) | Once per scenario. Use for agents that only read resources. | Uses the system config. |
| `run` | Once per scenario, agent, and repeat. Use for agents that change resources. | Disabled. |
| `skip` | None. Use resources already deployed on the cluster. | Uses the system config. |

```bash
make eval-ols-agentic SCENARIO=blocked_deployment_alert_remediation SETUP_MODE=run
make eval-ols-classic SCENARIO=crashlooping_pod_alert SETUP_MODE=skip
```

Classic group setup and cleanup run once per selected group in `scenario` and
`run` modes. In `skip` mode, group setup and cleanup are skipped too.

### Failures and cleanup

In `scenario` and `run` modes, cleanup runs after each setup attempt, even if
setup or evaluation fails. The runner logs the failure and continues with the
next run or scenario. Cleanup failures are logged without stopping the loop.
The runner updates the report from available results and returns a failure
status if setup or evaluation failed.

If Classic group setup fails, the runner skips that group's scenarios and
continues with other groups. Group cleanup runs after the full scenario loop.

## Reports

Runners save Markdown reports to `evals/results/<session>/report.md`,
in the same directory as the session results and system config.
Before setup starts, runners also copy the selected `evals-ols-*.yaml` files
to `<session>/scenarios/`, keeping scenario and group subdirectories.
Evaluations use these saved copies, so later edits to the source files do not
change the definitions used by the session.
The report is created before evaluation starts and updated at the start and
end of each scenario. With `SETUP_MODE=run`, it is updated for each agent and
repeat. You can open the file during `make eval-ols-agentic` or
`make eval-ols-classic` to see partial results.
The CLI prints the results table after each scenario. With `SETUP_MODE=run`,
it prints the table after all agents and repeats for that scenario finish.
CLI cells are yellow when the Markdown correctness table shows ❌, meaning
at least one evaluation error or failed completion check (when output is not
a terminal, these cells use `*` instead of color).

Partial reports add one line, such as `Partial results: scenario 2/47.`
The count shows scenarios whose agents and repeats have all finished.
Completed reports use the normal format without that line. Scores use saved
results only. Scenarios whose runs all failed or were skipped after a setup
error are listed with the reason before Correctness. Progress details remain
in `progress.json` in the session directory.

Runners try a final report update on exit, including Ctrl+C or termination.
Completed results remain available if a later scenario fails. Report files
are replaced only after the new report is fully written. If an update fails,
the last valid report stays available and the runner logs a warning. A failed
final update returns an error without replacing an earlier evaluation error.

To regenerate a report from saved results, run from the repository root:

```bash
venv/bin/python3 scripts/generate-report-classic.py "evals/results/<session>" \
  --output "evals/results/<session>/report.md"
```

Use `generate-report-agentic.py` for Agentic results. Pass
`--parallel-runs yes` if that session used parallel runs.

Both report types use the same scoring rules:

- Technical errors count as failed runs with score 0 in averages.
- ❌ marks a technical error in at least one run. Otherwise, 🟢 means all runs
  passed and 🔴 means none passed. Mixed results have no icon.
- Score medals compare values rounded to two decimal places.
- Model columns follow `agents.default.agent` in the matching
  `system-ols-*.yaml`. Models absent from the list appear last, alphabetically.

## Conventions

Alert investigation scenarios (specific to lightspeed-agentic-alerts-adapter) have:

- Tag `alert` in their `evals-ols-agentic.yaml`
- Directory name with `_alert` suffix; remediation variants use `_alert_remediation`
- Request in the template format defined by lightspeed-agentic-alerts-adapter

## Tags

Each `evals-*.yaml` file has tags under `tag`. Use `TAG=...` with an eval Make
target to select matching scenarios. The two eval definitions for one scenario
may have different tags.

Eval mode is selected by the Make target and file name (`evals-ols-agentic.yaml`
or `evals-ols-classic.yaml`). `agentic` and `classic` are no longer tags.
Use `investigation` for investigation and `remediation` for cases that apply a fix.
Each case also has one difficulty tag. `core`, `alert`, and group tags add
other ways to select cases.

Comma-separated tags use OR: `TAG=core,alert` selects cases with either tag.
It does not require both. `TAG=alert` selects alert investigation cases;
alert remediation variants use `remediation` instead.

| Tag | Meaning |
|-----|---------|
| `investigation` | Investigation cases that ask for a diagnosis or recommended fix. |
| `core` | Representative baseline cases across eval modes and difficulty levels. |
| `alert` | Alert investigation cases, also tagged `investigation`. |
| `remediation` | OLS Agentic cases that include analysis, a fix, and verification. |
| `difficulty_normal` | One isolated problem with a direct link between symptom and cause. |
| `difficulty_medium` | More reasoning is needed, such as several steps, a decoy, or domain knowledge. |
| `difficulty_high` | A complex cause chain that can lead to varied results across runs. |
| `kiali-ossm` | Classic service mesh cases that use Kiali and OSSM. |
| `kubevirt` | Classic OpenShift Virtualization cases. |
| `netobserv` | Classic network observability cases. |
