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
Classic needs OpenShift 4.22 or newer; Agentic needs OpenShift 5.0 or newer.
Run Make commands from the repository root.

| Option | Purpose |
|--------|---------|
| `SCENARIO=a,b` | Select named scenarios supported by the eval mode. |
| `TAG=core,alert` | Select scenarios with at least one of these tags. |
| `PREVIEW=1` | Show the selection without running setup, evaluation, or cleanup. |
| `NOTE="..."` | Add an optional memo before the first table in the Markdown report. |
| `SETUP_MODE=auto` | Choose setup and cleanup based on the selected scenarios; see below. |

Both eval targets and the manual `setup-scenario` and `cleanup-scenario` targets
require `SCENARIO`, `TAG`, or both, including with `PREVIEW=1`. Without a filter,
Make stops before setup or evaluation starts. With both `SCENARIO` and `TAG`,
tags filter the named scenarios.

```bash
make eval-ols-agentic TAG=core PREVIEW=1
make eval-ols-agentic TAG=investigation PREVIEW=1
make eval-ols-agentic TAG=remediation
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
| `auto` (default) | Uses `run` if any selected scenario has the `remediation` tag; otherwise uses `scenario`. | Based on the selected mode. |
| `scenario` | Once per scenario. Use for agents that only read resources. | Uses the system config. |
| `run` | Once per scenario, agent, and repeat. Use for agents that change resources. | Disabled. |
| `skip` | None. Use resources already deployed on the cluster. | Uses the system config. |

```bash
make eval-ols-agentic SCENARIO=blocked_deployment_alert_remediation
make eval-ols-classic SCENARIO=crashlooping_pod_alert SETUP_MODE=skip
```

The automatic choice applies to the whole session, including selections that
mix investigation and remediation scenarios. Each agent and repeat gets a
fresh fault, so a previous fix does not change the next evaluation. An explicit
`SETUP_MODE=run`, `scenario`, or `skip` overrides the automatic choice. Preview
and real runs show the selected mode.

Classic group setup and cleanup run once per selected group in `scenario` and
`run` modes. In `skip` mode, group setup and cleanup are skipped too.

MCP setup applies the config and Deployment before waiting for the rollout.
Set `MCP_IMAGE` to use a specific image. Otherwise, setup reads the image of
container `openshift-mcp-server` from Deployment `openshift-mcp-server` in
`openshift-lightspeed`. It prints the selected image and its source. If the
image cannot be read, setup stops before changing cluster resources and asks
for `MCP_IMAGE`. The image must support the selected toolsets. Config changes
trigger a rollout through a config hash in the pod template. `MCP_ROLLOUT_TIMEOUT`
sets the rollout timeout (default: `120s`), including standalone runs of
`scripts/mcp-config.sh`. A failed rollout prints pod status and recent logs.

### Failures and cleanup

In `scenario` and `run` modes, cleanup runs after each setup attempt, even if
setup or evaluation fails. The runner logs the failure and continues with the
next run or scenario. Cleanup failures are logged without stopping the loop.
The runner updates the report from available results and returns a failure
status if setup or evaluation failed.

If Classic group setup fails, the runner skips that group's scenarios and
continues with other groups. Group cleanup runs after the full scenario loop.

## Classic app-server logs

`make eval-ols-classic` downloads logs from the `lightspeed-service-api`
container after each evaluation, before scenario cleanup. It also downloads
logs before group setup and group cleanup can replace the app pod, and at
session start and exit, including failure, Ctrl+C, or termination. It uses
snapshots, without a background watcher, and keeps the current logging level.

Files include the scenario path, agent name, and repeat number:

```text
evals/results/<session>/logs/netobserv/dns_latency/openai-gpt-6-luna-run_1.log
```

Each file covers scenario setup and the whole evaluation call. When a call
contains several agents or repeats, each named file contains the same shared
log window. Its header states this limit. The collector does not separate
requests by model, including when agents run in parallel. `SETUP_MODE=run`
uses a separate evaluation call for each agent and repeat.

Other session, group setup, and cleanup logs go to
`logs/lightspeed-app-server-setup.log`. Each line
has a timestamp, pod name, and container restart number. The collector reads
all matching app-server pods and requests both current and previous container
logs after a restart. A cursor per pod UID and container instance avoids
duplicate lines across downloads. Cursor data is saved in
`.classic-log-state.json`; capture status and errors go to `capture-logs.log`.
Capture errors produce warnings and do not change the evaluation exit status.

Snapshots cannot recover logs lost through rotation, deleted pods, or several
container restarts between downloads. These gaps can still occur during long
DEBUG runs or unexpected pod replacement. Preview runs do not capture logs.

## Sandbox logs

`make eval-ols-agentic` automatically captures logs from the `agent` container
of new sandbox pods in `openshift-lightspeed` during the session. The watcher
starts before the first scenario and skips pods already present at startup.
It stops at the end of the session, including on failure, Ctrl+C, or termination.
This capture applies to Agentic evaluations; Classic and preview runs do not
start a watcher.

Sandbox logs are saved in `evals/results/<session>/logs/` alongside all existing
evaluation output. Filenames use the AgenticRun name and phase, for example
`eval-51a465db-analysis.log`. Phases are `analysis`, `execution`, and
`verification`. If the run name or phase is missing, the filename is `POD.log`.
Existing files are kept; another pod for the same run and phase gets a numbered
file, such as `eval-51a465db-analysis-1.log`.

Watcher status and errors are saved in
`evals/results/<session>/capture-logs.log`. If capture cannot start, the runner
prints a warning and continues. Capture failures do not change the evaluation
exit status. The pod watch reconnects after connection failures, but a failed
log stream is not retried. Pods deleted during a connection gap and logs from
earlier container restarts cannot be recovered.

For manual capture, run the standalone command from the repository root before
starting AgenticRuns:

```bash
./scripts/capture-logs
./scripts/capture-logs --output-dir ./logs
./scripts/capture-logs --help
```

It checks `oc` login before startup. The output directory defaults to the
current directory and is created if needed. Press Ctrl+C to stop capture.
Both the standalone command and the Agentic runner use the shared
`capture_logs()` function in [scripts/sandbox_logs.py](../scripts/sandbox_logs.py).

## Reports

Both Classic and Agentic runners save full `OLSConfig` CRs at session start
under `<session>/crs/`. Agentic also saves full `LLMProvider` and `Agent` CRs.
These configuration snapshots are read across namespaces, once per session,
before scenario setup. Cluster-scoped CRs use `KIND-NAME.yaml`; namespaced
configuration CRs use `KIND-NAMESPACE__NAME.yaml`, with the kind in lowercase.
The `__` separator keeps namespace and resource names distinct.
Secret resources are not collected. Capture status and errors are saved in
`capture-config-crs.log`. A failed read does not block other resource types
or stop the evaluation.

Agentic sessions save full `AgenticRun`, `AnalysisResult`, `ExecutionResult`,
`VerificationResult`, and `EscalationResult` CRs under `<session>/crs/`, one YAML file per CR (`KIND-NAME.yaml`).
Capture starts before evaluation and keeps updates and deletion events. At the
end of each eval, the runner collects a final snapshot before cleanup and
freezes that run's CR files. `crs/eval-stops.json` records the stop time and
eval outcome. Later CR updates cannot replace that snapshot. Existing runs
are skipped. Watch errors appear in `capture-logs.log`; final snapshot errors
appear in the evaluator output. Capture errors do not replace the eval outcome.

The phase breakdown reads these saved result CRs first. It checks the
`Completed` condition's reason, since `Completed=True` also applies to a
failed phase. Missing evidence is `Unknown`, and an active phase is `Running`.
The reader also supports JSON CRs from older sessions. Without saved CRs, it
uses result statuses in amended YAML, then AgenticRun conditions.
The report can be regenerated without cluster access. CR links let you inspect
the evidence. When available, duration covers the full AgenticRun, from its
creation to its terminal time.

Eval outcomes still use the saved metrics. An eval timeout is a failed test
and remains an ERROR even if the AgenticRun continues and completes later.
The framework timeout covers the full run, across all phases; `timeout: 900`
means 900 seconds (15 minutes). A phase still running when this timeout expires
is shown as timed out, even if its result CR does not exist yet. The frozen
parent CR records the active sandbox. Later completion is excluded from the
phase breakdown.
For recovered CRs from older sessions, the report uses the timeout result's
timestamp as the stop time; it does not count phase completions after that time.

To recover CRs for an older session while they still exist on the cluster:

```bash
venv/bin/python3 scripts/agentic_crs.py "evals/results/<session>"
```

This uses the run names in the saved log filenames. Use `--runs NAME ...` to
select run names explicitly when logs are missing. It saves only those runs
and their result CRs, matched by parent UID.

Runners save Markdown reports to `evals/results/<session>/report.md`,
in the same directory as the session results and system config.
Use `NOTE` to describe the purpose of a run. It works for both eval targets:

```bash
make eval-ols-agentic TAG=investigation NOTE="testing alerts investigation without the skill"
```

The note is saved in `progress.json` and appears before the first report table,
including when you regenerate the report. Without `NOTE`, no memo is added.

Before setup starts, runners also copy the selected `evals-ols-*.yaml` files
to `<session>/scenarios/`, keeping scenario and group subdirectories.
Evaluations use these saved copies, so later edits to the source files do not
change the definitions used by the session.
The report is created before evaluation starts and updated at the end of each
scenario. With `SETUP_MODE=run`, it is updated for each agent and
repeat. You can open the file during `make eval-ols-agentic` or
`make eval-ols-classic` to see partial results.
Run starts update only `progress.json`, which records the active run.
The CLI prints the results table after each scenario, before cleanup starts.
With `SETUP_MODE=run`, it prints the updated table after each agent and repeat,
before cleanup starts for that run.
CLI cells are yellow when the Markdown correctness table shows ⚠️, meaning
at least one technical error, including a setup failure or missing results
after the session ends (when output is not a terminal, these cells use `*`
instead of color).

Partial reports add one line, such as `Partial results: scenario 2/47.`
The count shows scenarios whose agents and repeats have all finished.
Completed reports use the normal format without that line. Scores use saved
results only. Scenarios whose runs all failed or were skipped after a setup
error are listed with the reason before the result tables. Progress details remain
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

- Correctness uses a default threshold of 0.75 from the matching
  `system-ols-*.yaml`. Scenarios can override it with `turn_metrics_metadata`;
  the Agentic `failing_api_alert` case requires 0.80. Remediation cases use
  status checks without a correctness score.
- PASS, FAIL, and ERROR rates use finished runs as the denominator, including
  finished runs with no results. FAIL means a failed quality check without a technical
  error. ERROR includes setup failures, evaluation errors, failed completion
  checks, and missing results after the session ends. Pending runs are excluded from tables and totals, also after a session stops.
  Scenarios with no finished runs are hidden.
- Avg score uses available correctness scores, including scores below the
  threshold. It shows `(scored runs / finished runs)`. No zero is added for a
  missing score. A real judge score is kept even if the run has a technical
  error. Completion status alone does not provide a correctness score.
- Saved progress and scenario definitions provide the planned runs. For older
  sessions without a saved plan, reports use the saved repeat setting and
  available results. Percentages are rounded and may not sum to exactly 100%.
- In the CLI summary, nonzero FAIL rates are red and ERROR rates are yellow.
  Numeric Avg score values are bright white; N/A keeps the default color.
  The CLI includes Avg score when a correctness metric is recorded, even if
  all scores are N/A. Status-only Agentic results do not add this row.
  The Markdown overview and Correctness tables show the same counts. Token
  usage appears under Tokens. Above the CLI table, a metadata line shows the
  same date, system, scenario and agent counts, repeats, parallel mode, and
  judge as the Markdown report.
- ⚠️ marks a technical error in at least one run. Otherwise, 🟢 means all runs
  passed and 🔴 means none passed. Mixed results have no icon.
- Score medals compare values rounded to two decimal places.
- Model columns follow `agents.default.agent` in the matching
  `system-ols-*.yaml`. Models absent from the list appear last, alphabetically.

Agentic reports show **Correctness** only when at least one correctness score
is available, including a score of zero. The table and its totals include only
scenarios with scores. A partial report adds this table when the first score
arrives. Status scores are never shown or used as correctness scores.

The CLI summary shows one table with no title and one row per scenario. It uses
correctness results when available, with completion status as a fallback.
The footer shows PASS, FAIL, ERROR, average duration, and average tokens.
Avg score appears only when at least one correctness score is available.

**Phase completion** appears in Markdown reports. Investigation
scenarios show Analysis; remediation scenarios also show Execution and
Verification. Saved scenario definitions select the phases, with recorded tags
as a fallback for older sessions. Each phase has its own completion count and
rate. Execution and Verification totals exclude investigation scenarios.
Completion means a phase succeeded; it does not measure answer correctness.
Missing, unknown, running, and timed out states stay distinct.

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
