#!/usr/bin/env bash
# Shared report updates for the Classic and Agentic runners.

report_update() {
  local quiet_args=()
  if [ "$REPORT_FINISHED" -eq 0 ] && [ "${1:-quiet}" = "quiet" ]; then
    quiet_args=(--quiet)
  fi
  "$PYTHON" "$REPORT_GENERATOR" \
    --parallel-runs "$PARALLEL_RUNS" "${quiet_args[@]}" \
    "$EVAL_DIR" --output "$EVAL_DIR/report.md"
}

report_event() {
  local event="$1"
  local output="$2"
  shift 2
  if "$PYTHON" "$SCRIPT_DIR/report_progress.py" "$event" "$EVAL_DIR" "$@"; then
    report_update "$output" || echo "WARNING: report update failed; keeping the last report." >&2
  else
    echo "WARNING: progress update failed; keeping the last report." >&2
  fi
}

report_init() {
  REPORT_GENERATOR="$SCRIPT_DIR/generate-report-$1.py"
  REPORT_FINISHED=0
  report_event init quiet --setup-mode "$SETUP_MODE" --repeat "$REPEAT" \
    --agents "${AGENTS[@]}" --scenarios "${SCENARIOS[@]}"
}

report_finalize() {
  local finished_args=()
  if [ "$REPORT_FINISHED" -eq 1 ]; then finished_args=(--finished); fi
  "$PYTHON" "$SCRIPT_DIR/report_progress.py" finalize "$EVAL_DIR" \
    --exit-code "$1" "${finished_args[@]}" || return $?
  echo "==> Updating final report..."
  report_update
}
