#!/usr/bin/env bash
# Common infrastructure cleanup for agentic evaluations.
# Sourced by per-scenario cleanup scripts — do NOT run directly.
#
# Deletes "eval-" prefixed operator resources (reverse order of creation).

OPERATOR_NS="${OPERATOR_NS:-openshift-lightspeed}"

oc delete agent eval-default --ignore-not-found
oc delete llmprovider eval-openai --ignore-not-found
oc delete secret eval-llm-credentials -n "$OPERATOR_NS" --ignore-not-found
