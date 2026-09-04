#!/usr/bin/env bash
set -euo pipefail

OLS_NS="${OLS_NS:-openshift-lightspeed}"
OLS_DEFAULT_PROVIDER="${OLS_DEFAULT_PROVIDER:-}"
OLS_DEFAULT_MODEL="${OLS_DEFAULT_MODEL:-}"

has_openai=false
has_gcp=false

[ -n "${OPENAI_API_KEY:-}" ] && has_openai=true

if [ -n "${GCP_SERVICE_ACCOUNT_JSON:-}" ] && [ -n "${GCP_PROJECT_ID:-}" ]; then
  if [ -f "${GCP_SERVICE_ACCOUNT_JSON}" ]; then
    has_gcp=true
  else
    echo "WARN: GCP_SERVICE_ACCOUNT_JSON file not found: ${GCP_SERVICE_ACCOUNT_JSON} — skipping google/anthropic"
  fi
fi

if ! $has_openai && ! $has_gcp; then
  printf '\033[0;31mERROR:\033[0m No LLM credentials found. Set at least one of:\n'
  printf '  OPENAI_API_KEY                              (for OpenAI)\n'
  printf '  GCP_SERVICE_ACCOUNT_JSON + GCP_PROJECT_ID   (for Google + Anthropic)\n'
  exit 1
fi

# Default to first available provider
if [ -z "$OLS_DEFAULT_PROVIDER" ]; then
  if $has_openai; then
    OLS_DEFAULT_PROVIDER=openai
  else
    OLS_DEFAULT_PROVIDER=google
  fi
fi
case "$OLS_DEFAULT_PROVIDER" in
  openai)    OLS_DEFAULT_MODEL="${OLS_DEFAULT_MODEL:-gpt-5.4}" ;;
  google)    OLS_DEFAULT_MODEL="${OLS_DEFAULT_MODEL:-gemini-2.5-pro}" ;;
  anthropic) OLS_DEFAULT_MODEL="${OLS_DEFAULT_MODEL:-claude-opus-4-6}" ;;
esac

providers_summary=""
$has_openai && providers_summary+="openai "
$has_gcp && providers_summary+="google anthropic "
echo "==> Providers: ${providers_summary}"
echo "==> Default: ${OLS_DEFAULT_PROVIDER}/${OLS_DEFAULT_MODEL}"

# Skip operator installation if OLS is already installed and healthy
ols_installed=false
if oc get deployment lightspeed-app-server -n "$OLS_NS" -o name >/dev/null 2>&1; then
  if oc rollout status deployment/lightspeed-app-server -n "$OLS_NS" --timeout=10s >/dev/null 2>&1; then
    echo "OLS operator already installed and running in ${OLS_NS}"
    ols_installed=true
  fi
fi

if ! $ols_installed; then
echo "==> Installing OLS operator in ${OLS_NS}..."

# 1. Namespace
oc apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: ${OLS_NS}
  labels:
    openshift.io/cluster-monitoring: "true"
EOF

# 2. OperatorGroup
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-lightspeed
  namespace: ${OLS_NS}
spec:
  targetNamespaces:
    - ${OLS_NS}
EOF

# 3. Subscription
oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: lightspeed-operator
  namespace: ${OLS_NS}
spec:
  channel: stable
  name: lightspeed-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF

# 4. Wait for operator
echo "==> Waiting for Subscription to resolve..."
oc wait --for=jsonpath='{.status.state}'=AtLatestKnown \
  subscription/lightspeed-operator -n "$OLS_NS" --timeout=480s

CSV=$(oc get subscription lightspeed-operator -n "$OLS_NS" \
  -o jsonpath='{.status.currentCSV}')
echo "==> Waiting for CSV ${CSV}..."
oc wait --for=jsonpath='{.status.phase}'=Succeeded \
  csv/"${CSV}" -n "$OLS_NS" --timeout=480s
fi

# 5. LLM credentials
echo "==> Creating credentials secrets..."
if $has_openai; then
  oc create secret generic credentials-openai \
    --namespace "$OLS_NS" \
    --from-literal=apitoken="${OPENAI_API_KEY}" \
    --type=Opaque \
    --dry-run=client -o yaml | oc apply -f -
fi
if $has_gcp; then
  oc create secret generic credentials-gcp-google \
    --namespace "$OLS_NS" \
    --from-file=apitoken="${GCP_SERVICE_ACCOUNT_JSON}" \
    --type=Opaque \
    --dry-run=client -o yaml | oc apply -f -
  oc create secret generic credentials-gcp-anthropic \
    --namespace "$OLS_NS" \
    --from-file=apitoken="${GCP_SERVICE_ACCOUNT_JSON}" \
    --type=Opaque \
    --dry-run=client -o yaml | oc apply -f -
fi

# 6. Build providers list — include each provider whose credentials are set
providers=""
if $has_openai; then
  providers+="
    - name: openai
      type: openai
      credentialsSecretRef:
        name: credentials-openai
      url: https://api.openai.com/v1
      models:
      - name: gpt-5.4
        parameters:
          tool_budget_ratio: 0.5
      - name: gpt-5.5
        parameters:
          tool_budget_ratio: 0.5
      - name: gpt-5.4-nano"
fi
if $has_gcp; then
  providers+="
    - name: google
      type: google_vertex
      credentialsSecretRef:
        name: credentials-gcp-google
      credentialKey: apitoken
      googleVertexConfig:
        projectID: ${GCP_PROJECT_ID}
        location: ${GCP_GOOGLE_LOCATION:-${GCP_LOCATION:-global}}
      models:
      - name: gemini-2.5-flash
      - name: gemini-3.5-flash
      - name: gemini-2.5-pro
    - name: anthropic
      type: google_vertex_anthropic
      credentialsSecretRef:
        name: credentials-gcp-anthropic
      credentialKey: apitoken
      googleVertexAnthropicConfig:
        projectID: ${GCP_PROJECT_ID}
        location: ${GCP_ANTHROPIC_LOCATION:-${GCP_LOCATION:-us-east5}}
      models:
      - name: claude-opus-4-6
      - name: claude-opus-4-8"
fi

# 7. Apply OLSConfig
echo "==> Applying OLSConfig..."
oc apply -f - <<EOF
apiVersion: ols.openshift.io/v1alpha1
kind: OLSConfig
metadata:
  name: cluster
spec:
  llm:
    providers:${providers}
  ols:
    defaultModel: "${OLS_DEFAULT_MODEL}"
    defaultProvider: "${OLS_DEFAULT_PROVIDER}"
EOF

# 8. Wait for OLS to be ready
if ! $ols_installed; then
  echo "==> Waiting for lightspeed-app-server deployment to appear..."
  elapsed=0
  while ! oc get deployment lightspeed-app-server -n "$OLS_NS" -o name >/dev/null 2>&1; do
    if [ "$elapsed" -ge 480 ]; then
      echo "ERROR: lightspeed-app-server not created after 480s"
      exit 1
    fi
    echo "  ... waiting for lightspeed-app-server (${elapsed}/480s)"
    sleep 5
    elapsed=$((elapsed + 5))
  done
fi
echo "==> Waiting for rollout..."
oc rollout status deployment/lightspeed-app-server -n "$OLS_NS" --timeout=480s
echo "==> OLS installed and ready in ${OLS_NS}."
