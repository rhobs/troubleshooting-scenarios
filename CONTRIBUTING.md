# Adding a Scenario

Scenarios live under `evals/scenarios/`. Each scenario is a self-contained directory that deploys a fault on a live OpenShift cluster.

## Naming conventions

Directory names use underscores (`_`), not hyphens. Names should describe the observable symptom in `adjective_noun` form (e.g., `pending_pvc`, `crashlooping_pod`, `failing_api`). Name what an operator would see, not the underlying root cause.

Alert-triggered scenarios use an `_alert` suffix; remediation variants use `_alert_remediation`.

## Scenario directory structure

```
my_scenario/
  setup.sh                     Deploys fixtures to the cluster
  cleanup.sh                   Removes everything the scenario created
  fixtures/
    manifest.yaml              Kubernetes manifests (Deployments, Services, etc.)
    prometheusrule.yaml        PrometheusRules for alert-based scenarios
  evals-ols-agentic.yaml       Eval definitions for OLS Agentic
  evals-ols-classic.yaml       Eval definitions for OLS Classic (optional)
```

### setup.sh

Creates the namespace and deploys all resources. Must be idempotent and executable (`chmod +x`). Typically applies fixtures with `oc apply -f fixtures/` and waits for the fault to manifest (e.g., pod enters CrashLoopBackOff, alert fires).

### cleanup.sh

Deletes the namespace and any cluster-scoped resources the scenario created. Must be executable and tolerate resources that don't exist (use `--ignore-not-found`).

### fixtures/

Kubernetes manifests that reproduce the fault. Use business-domain names (e.g., `warehouse-ops`, `payments`, `report-generator`), not names that encode the diagnosis or test intent.

### evals-ols-agentic.yaml

Eval definitions for OLS Agentic. Each entry defines:

- `conversation_group_id`: must match the scenario directory name
- `description`: symptom, `RCA:` (root cause), `Expected:` (what the agent should do)
- `tag`: workflow, difficulty, and optional selection tags (see below)
- `turns`: the AgenticRun spec, expected status, and scoring metrics

### evals-ols-classic.yaml

Eval definitions for OLS Classic. Same structure but with `query`/`expected_response` instead of AgenticRun specs. Only add this file if the scenario is meaningful as a text Q&A.

### Tags

Use `investigation` for cases that investigate a problem and recommend a fix.
Use `remediation` for Agentic cases that include analysis, a fix, and
verification. Alert investigation cases also use `alert`; remediation
variants use `remediation` instead of `alert`.

Add one difficulty tag: `difficulty_normal`, `difficulty_medium`, or
`difficulty_high`. Use `core` only for cases selected for the baseline suite.
Grouped cases also use their group tag: `kiali-ossm`, `kubevirt`, or `netobserv`.

The file name selects the eval mode, so do not add `agentic` or `classic` tags.
For example, an alert investigation case may use:

```yaml
tag:
  - investigation
  - alert
  - difficulty_normal
```

See the [tag guide](evals/README.md#tags) for tag meanings and filtering.
When changing difficulty, move the scenario row to the matching section in
`evals/README.md`. Check both eval files when a scenario supports both modes.

## Scenario groups

Scenarios that require shared infrastructure (operators, MCP toolsets) can be organized into groups. A group is a directory under `evals/scenarios/` that contains individual scenario subdirectories plus group-level setup and cleanup:

```
group_name/
  setup.sh            Provisions shared infrastructure (runs once per group)
  cleanup.sh          Tears down shared infrastructure (runs once per group)
  scripts/            Group-specific helpers
  scenario1/          Individual scenario (same structure as above)
  scenario2/
```

The Classic eval runner runs group `setup.sh` before the first scenario in
the group and group `cleanup.sh` after the full scenario loop.
`SETUP_MODE=skip` skips both. The manual setup and cleanup targets also handle
group resources.

Grouped scenario names use the `group/scenario` format (e.g., `kubevirt/vm_crashloop`) in the Makefile variables and README tables.

## Registering the scenario

After creating the scenario directory:

1. Add the scenario name to the appropriate variable (`_ALL_OLS_AGENTIC` and/or `_ALL_OLS_CLASSIC`) in the root `Makefile`
2. Add a row to the scenario table in `evals/README.md`
3. Run the `review-scenario` skill (`.agents/skills/review-scenario/SKILL.md`, symlinked as `.claude/skills/review-scenario/`) to check for naming leaks, revealing comments, and unrealistic fault setups. In Claude Code: `/review-scenario my_scenario`

## Checks

Run all linters from the repository root:

```bash
make lint
```

This installs the pinned lint tools into `.tools/` when needed. To install them without running lint, use `make tools`.

For changes to shared scripts or reports, also run the script tests in an
environment with pytest and PyYAML:

```bash
python3 -m pytest scripts/tests -q
```

Check that usage examples and README instructions still match the changed
behavior. Keep generated eval output in `evals/results/`; only copy selected
reports to `evals/reports/`.
