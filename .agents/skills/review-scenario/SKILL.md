---
name: review-scenario
description: Audit a fault scenario under evals/scenarios/ for leakage from resource names, comments, manifest values and request text that reveal the diagnosis without cluster investigation, and check fault realism, conversation_group_id consistency and the description/RCA/Expected block. Use when a scenario is added, modified or renamed, before committing one, or when the user says "review scenario". Takes a scenario directory path (e.g. blocked_deployment or kubevirt/vm_storage_failure) or a scenario group name. Not for labs/ scenarios or debugging eval results.
---

# Review scenario

Audit a single scenario under `evals/scenarios/` for **leakage**: anything that lets an LLM solve the problem without genuine cluster investigation.

Three leakage vectors, checked in order:

1. **Naming** - resource names that encode the diagnosis
2. **Disclosure** - YAML comments or inline values that hand over the answer
3. **Realism** - faults an LLM can diagnose from the manifest alone

The argument is a scenario directory path under `evals/scenarios/` (e.g. `blocked_deployment` or `kubevirt/vm_storage_failure`), or a scenario group name.

## 1. Inventory

Read every file in `evals/scenarios/$SCENARIO/`:

- `fixtures/` (all files, including YAML and Python)
- `setup.sh`
- `cleanup.sh`
- every `evals-*.yaml` present (`evals-ols-agentic.yaml` and/or `evals-ols-classic.yaml`)
- `image/` and `README.md` where present

For a scenario group (`kiali-ossm`, `kubevirt`, `netobserv`), read the group's own
`setup.sh`, `cleanup.sh`, `Makefile`, `README.md` and `scripts/`, then each case
directory the same way. When reviewing a single nested case, also read these
shared files from its parent group.

Collect every Kubernetes resource name, label value, and shell variable assignment (`NS=`, `APP=`, `DEPLOY=`).

## 2. Consistency check

Verify that every `conversation_group_id` in each `evals-*.yaml` matches the case directory name, or that name with a trailing `_alert` removed (`crashlooping_pod_alert` → `crashlooping_pod`, `unready_pod_alert` → `unready_pod`). For nested cases, use the case directory's basename, not the group path. Flag any other mismatch as a **FAIL**-level issue.

## 3. Description check

Verify that the `description:` field exists in each `evals-*.yaml`, placed before `tag:`. It must follow this structure:

```
description: |
  [One or two sentences describing the observable symptom.]
  RCA: [root cause analysis, what is actually wrong.]
  Expected: [what the agent should do or report.]
```

Flag as **FAIL** if:
- `description:` is missing entirely
- `description:` appears after `tag:`
- The description does not contain both `RCA:` and `Expected:` on separate lines
- The symptom, RCA, or Expected sections are empty

Flag as **NEEDS WORK** if:
- The symptom section describes the root cause instead of the observable behavior
- The RCA section is vague or does not match the `expected_outcome` (Agentic) or `expected_response` (Classic)
- The Expected section does not match the `expected_outcome` (Agentic) or `expected_response` (Classic)

## 4. Naming check

For each name collected, answer: **does this name tell an LLM what the problem is before it runs a single cluster command?**

Flag names that:
- Describe the fault mechanism (`antiaffinity-demo`, `missing-pvc-test`, `default-deny-egress`)
- Describe the expected answer (`healthy-app`, `nothing-wrong`, `quota-victim`)
- Reveal the test intent (`trap-demo`, `herring-app`, `fragile-app`)
- Carry test-context markers: `-demo`, `-test`, `eval-` prefixes/suffixes
- Use temporal hints that encode the answer: `old-`, year stamps, `legacy-` (when the scenario tests orphan detection)
- Reveal the scenario is synthetic: container names like `log-emitter`, `fault-injector`; script filenames like `generate_logs.py`, `simulate_*.py`; Secret/ConfigMap names containing `log-script`, `logs-script`, or `fault`
- Include `eval/scenario` or similar annotations that label the test case

Neutral names are business-domain names that a real team would use: `payments`, `warehouse-ops`, `report-generator`, `media-processing`.

## 5. Comment and disclosure check

Search fixture YAML for `#` comment lines. Flag comments that:
- Explain the root cause or the fault
- State the expected error message or behavior
- Reveal the fix
- Give away structural information an LLM should discover (e.g. "6 workloads here, 9 there")

Check Python scripts in `fixtures/` for docstrings or comments that describe the fault, the simulation intent, or the expected diagnosis (e.g. `"""Simulate a gateway that reloads config"""`, `# Root cause: config drift`). The LLM can read these via `oc get configmap -o yaml` or `oc get secret -o yaml`.

Also check for inline values that disclose the answer without needing a comment:
- Image tags containing `does-not-exist`, `fake`, `broken`, `invalid`, or impossible version numbers
- `replicas: 0` directly in the YAML (vs. scaling to zero at runtime in setup.sh)
- PrometheusRule annotations (`summary`, `description`) that contain troubleshooting instructions (e.g. "Check resource limits", "Inspect application logs", "Verify storage class"). Annotations should state what is happening, not how to fix it.

## 6. Realism check

For each fault in the scenario, answer: **can an LLM diagnose this by reading `oc get <resource> -o yaml` without needing runtime signals (events, logs, pod status, describe, metrics)?**

Classify:

- **CRITICAL**: the YAML alone is the complete diagnosis. Hardcoded `exit 1`, explicit memory bombs (`data.append("x" * 1000000)`), arithmetic that screams (64Mi write into 10Mi limit with both numbers in the command).
- **MODERATE**: the YAML is a strong hint but cluster signals add information. Port mismatches, missing referenced resources, suspicious nodeSelectors. Note whether reading the YAML IS the realistic diagnostic path for this type of issue (it often is for selector mismatches, probe ports, RBAC bindings).
- **OK**: the fault requires runtime investigation. Log analysis, connection behavior, metrics comparison, runtime state changes.

## 7. Request text check

Read the `openshift_agentic_run_spec.request` field in `evals-ols-agentic.yaml`
and the `query:` fields in `evals-ols-classic.yaml`. Flag if any of them:
- States the root cause outright
- Names the exact broken resource when the scenario has multiple candidates
- Uses terminology that narrows the search space to one possibility

The request should describe **symptoms** (alerts, user reports, observed behavior), not causes.

Also read Classic's `expected_response:` fields for consistency with the fault
and description. These are scoring references and may state the diagnosis;
apply the symptom-only leakage rule to the agent-facing request or query.

## 8. Report

Output a structured report:

```
## Scenario: <name>

### Consistency
[conversation_group_id vs directory name: match or mismatch]

### Description
[structure and content check: present, correct position, has RCA/Expected]

### Naming
[list each problematic name -> what it hints at -> suggested fix]

### Disclosure
[quote each problematic comment or value -> suggested fix]

### Realism
[each fault -> CRITICAL/MODERATE/OK -> rationale]
[for MODERATE: note if reading YAML is the realistic diagnostic path]

### Request text
[issues found, or "clean"]

### Verdict: PASS | NEEDS WORK | FAIL
[one-line summary of what to fix, or "no issues found"]
```

Severity guide:
- **FAIL**: naming encodes the diagnosis, OR a CRITICAL realism issue makes the scenario solvable from YAML alone
- **NEEDS WORK**: MODERATE issues that weaken the eval but don't invalidate it
- **PASS**: no significant leakage; the scenario requires genuine cluster investigation
