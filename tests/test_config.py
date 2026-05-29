from pathlib import Path

from agentplane_mcp_wrapper.config import load_config


def test_example_config_targets_agentplane_public_demo() -> None:
    config = load_config(Path(__file__).parents[1] / "examples" / "agentplane.tech.toml")

    assert config.mcp_local.gateway_url == "https://mcp.agentplane.tech/mcp"
    assert config.mcp_local.client_name == "agentplane-mcp-wrapper"
    assert config.mcp_local.oidc is not None
    assert config.mcp_local.oidc.issuer == "https://agentplane.tech/idp/realms/demo"
    assert "mcp:tools" in config.mcp_local.oidc.scopes
