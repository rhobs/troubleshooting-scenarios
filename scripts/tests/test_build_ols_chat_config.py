"""Check OLS Chat defaults and provider selection without a cluster."""

import importlib.util
from pathlib import Path

import pytest
import yaml


spec = importlib.util.spec_from_file_location(
    "build_ols_chat_config",
    Path(__file__).resolve().parents[1] / "build-ols-chat-config.py",
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def build_config(tmp_path, monkeypatch, capsys):
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}")
    monkeypatch.setenv("EVAL_VERTEX_CREDENTIALS", str(credentials))
    monkeypatch.setenv("EVAL_VERTEX_PROJECT_ID", "test-project")

    def build(active_agents, judges):
        agents = {"default": {"agent": list(active_agents)}, **active_agents}
        config = {
            "agents": agents,
            "judge_panel": {"judges": list(judges)},
            "llm_pool": {"models": judges},
        }
        path = tmp_path / "system.yaml"
        path.write_text(yaml.safe_dump(config))
        builder.main(str(path))
        output = capsys.readouterr()
        return yaml.safe_load(output.out)["spec"], output.err

    return build


@pytest.mark.parametrize("provider", ["openai", "google", "anthropic"])
@pytest.mark.parametrize("mixed", [False, True])
def test_first_agent_sets_defaults(build_config, provider, mixed):
    agents = {"first": {"provider": provider, "model": "first-model"}}
    if mixed:
        agents.update({
            name: {"provider": name, "model": f"{name}-model"}
            for name in ("openai", "google", "anthropic")
        })
    spec, diagnostics = build_config(
        agents, {"judge": {"provider": "openai", "model": "judge-model"}},
    )

    assert spec["ols"] == {"defaultProvider": provider, "defaultModel": "first-model"}
    assert f"==> Default: {provider}/first-model" in diagnostics
    providers = {entry["name"]: entry for entry in spec["llm"]["providers"]}
    expected_names = {"openai", "google", "anthropic"} if mixed else {provider, "openai"}
    assert providers.keys() == expected_names
    assert {"name": "first-model"} in providers[provider]["models"]
    assert {"name": "judge-model"} in providers["openai"]["models"]
    assert all(entry["models"] for entry in providers.values())
    for name in expected_names - {"openai"}:
        field = "googleVertexConfig" if name == "google" else "googleVertexAnthropicConfig"
        assert providers[name][field] == {"projectID": "test-project", "location": "global"}


@pytest.mark.parametrize("provider", ["google", "anthropic"])
def test_openai_is_omitted_when_unused(build_config, provider):
    spec, _ = build_config(
        {"agent": {"provider": provider, "model": "test-model"}},
        {"judge": {"provider": provider, "model": "test-model"}},
    )

    providers = spec["llm"]["providers"]
    assert len(providers) == 1
    assert providers[0]["name"] == provider
    assert providers[0]["models"] == [{"name": "test-model"}]


def test_openai_only_needs_no_vertex_credentials(build_config, monkeypatch):
    monkeypatch.delenv("EVAL_VERTEX_CREDENTIALS")
    monkeypatch.delenv("EVAL_VERTEX_PROJECT_ID")
    spec, _ = build_config(
        {"agent": {"provider": "openai", "model": "test-model"}},
        {"judge": {"provider": "openai", "model": "judge-model"}},
    )
    assert [entry["name"] for entry in spec["llm"]["providers"]] == ["openai"]


@pytest.mark.parametrize("provider", ["google", "anthropic"])
def test_vertex_default_still_needs_credentials(build_config, monkeypatch, provider):
    monkeypatch.delenv("EVAL_VERTEX_CREDENTIALS")
    with pytest.raises(ValueError, match="EVAL_VERTEX_CREDENTIALS"):
        build_config(
            {"agent": {"provider": provider, "model": "test-model"}},
            {"judge": {"provider": "openai", "model": "judge-model"}},
        )


def test_unsupported_default_provider_is_rejected(build_config):
    with pytest.raises(ValueError, match="agent 'agent' needs a supported provider and model"):
        build_config(
            {"agent": {"provider": "unsupported", "model": "test-model"}},
            {"judge": {"provider": "openai", "model": "judge-model"}},
        )
