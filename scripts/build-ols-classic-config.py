#!/usr/bin/env python3
"""Build an OLS Classic config from active agents and judges."""

import os
import sys
import yaml


DEFAULT_PROVIDER = "openai"
PROVIDER_ORDER = ("openai", "google", "anthropic")


def main(config_path: str) -> None:
    with open(config_path, encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}

    if not isinstance(config, dict):
        raise ValueError("system config must be a YAML mapping")
    agents = config.get("agents") or {}
    if not isinstance(agents, dict):
        raise ValueError("agents must be a YAML mapping")
    active_names = (agents.get("default") or {}).get("agent") or []
    if not isinstance(active_names, list) or not active_names:
        raise ValueError("agents.default.agent must be a non-empty list")

    models = {provider: [] for provider in PROVIDER_ORDER}
    for index, name in enumerate(active_names):
        agent = agents.get(name)
        if not isinstance(agent, dict):
            raise ValueError(f"active agent '{name}' is not defined")
        provider = agent.get("provider")
        model = agent.get("model")
        if (
            not isinstance(provider, str)
            or provider not in models
            or not isinstance(model, str)
            or not model
        ):
            raise ValueError(f"agent '{name}' needs a supported provider and model")
        if index == 0 and provider != DEFAULT_PROVIDER:
            raise ValueError("the first active agent must use OpenAI as the default provider")
        if model not in models[provider]:
            models[provider].append(model)

    default_model = models[DEFAULT_PROVIDER][0]

    # A judge may use a model that no active agent uses.
    judge_panel = config.get("judge_panel") or {}
    llm_pool = config.get("llm_pool") or {}
    if not isinstance(judge_panel, dict) or not isinstance(llm_pool, dict):
        raise ValueError("judge_panel and llm_pool must be YAML mappings")
    judge_names = judge_panel.get("judges") or []
    judge_models = llm_pool.get("models") or {}
    if not isinstance(judge_names, list) or not judge_names:
        raise ValueError("judge_panel.judges must be a non-empty list")
    if not isinstance(judge_models, dict):
        raise ValueError("llm_pool.models must be a YAML mapping")
    for name in judge_names:
        judge = judge_models.get(name)
        if not isinstance(judge, dict):
            raise ValueError(f"judge '{name}' is not defined in llm_pool.models")
        provider = judge.get("provider")
        model = judge.get("model")
        if (
            not isinstance(provider, str)
            or provider not in models
            or not isinstance(model, str)
            or not model
        ):
            raise ValueError(f"judge '{name}' needs a supported provider and model")
        if model not in models[provider]:
            models[provider].append(model)

    uses_vertex = any(models[provider] for provider in ("google", "anthropic"))
    project_id = os.environ.get("EVAL_VERTEX_PROJECT_ID")
    credentials = os.environ.get("EVAL_VERTEX_CREDENTIALS")
    if uses_vertex and (not project_id or not credentials or not os.path.isfile(credentials)):
        raise ValueError(
            "Google or Anthropic agents or judges need EVAL_VERTEX_CREDENTIALS "
            "(an existing file) and EVAL_VERTEX_PROJECT_ID"
        )

    providers = [
        {
            "name": "openai",
            "type": "openai",
            "credentialsSecretRef": {"name": "creds-classic-openai"},
            "credentialKey": "apitoken",
            "url": "https://api.openai.com/v1",
            "models": [{"name": model} for model in models["openai"]],
        }
    ]
    if models["google"]:
        providers.append({
            "name": "google",
            "type": "google_vertex",
            "credentialsSecretRef": {"name": "creds-classic-vertex-google"},
            "credentialKey": "apitoken",
            "googleVertexConfig": {"projectID": project_id, "location": "global"},
            "models": [{"name": model} for model in models["google"]],
        })
    if models["anthropic"]:
        providers.append({
            "name": "anthropic",
            "type": "google_vertex_anthropic",
            "credentialsSecretRef": {"name": "creds-classic-vertex-anthropic"},
            "credentialKey": "apitoken",
            "googleVertexAnthropicConfig": {"projectID": project_id, "location": "global"},
            "models": [{"name": model} for model in models["anthropic"]],
        })

    ols_config = {
        "apiVersion": "ols.openshift.io/v1alpha1",
        "kind": "OLSConfig",
        "metadata": {"name": "cluster"},
        "spec": {
            "llm": {"providers": providers},
            "ols": {"defaultModel": default_model, "defaultProvider": DEFAULT_PROVIDER},
        },
    }
    print("==> Providers: " + " ".join(provider["name"] for provider in providers), file=sys.stderr)
    print(f"==> Default: {DEFAULT_PROVIDER}/{default_model}", file=sys.stderr)
    print(yaml.safe_dump(ols_config, sort_keys=False).rstrip())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: build-ols-classic-config.py SYSTEM_CONFIG")
    try:
        main(sys.argv[1])
    except (OSError, ValueError, yaml.YAMLError) as error:
        sys.exit(f"ERROR: Cannot build OLS Classic config: {error}")
