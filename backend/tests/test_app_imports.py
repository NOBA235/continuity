"""
Nothing in test_agent_tools.py, test_auth_router.py, etc. imports app.main
together with app.agents.continuity_agent.agent -- each test module only
imports the one submodule it needs. That's exactly how a real dependency
conflict (google-adk's MCP client vs. mcp-clickhouse's server stack both
wanting incompatible major versions of the `mcp` package) slipped past the
whole suite until a manual `import app.main` caught it. This test exists so
that specific failure mode can't silently come back.
"""
from __future__ import annotations


def test_app_main_imports_cleanly():
    import app.main  # noqa: F401 -- import success is the assertion


def test_continuity_agent_builds_with_expected_tools():
    from app.agents.continuity_agent.agent import build_continuity_agent

    agent = build_continuity_agent()
    tool_type_names = {type(t).__name__ for t in agent.tools}
    assert "McpToolset" in tool_type_names
    assert "FunctionTool" in tool_type_names


def test_all_routers_registered_on_the_app():
    import app.main as m

    schema = m.app.openapi()
    expected_paths = {
        "/api/auth/register", "/api/auth/login", "/api/auth/refresh", "/api/auth/me",
        "/api/ingestion/upload", "/api/ingestion/jobs", "/api/ingestion/jobs/{job_id}",
        "/api/ingestion/jobs/{job_id}/video",
        "/api/frames", "/api/frames/scenes", "/api/frames/scenes/{scene_id}/takes",
        "/api/anomalies", "/api/anomalies/{anomaly_id}/resolve",
        "/api/agent/run", "/api/agent/executions", "/api/agent/executions/{execution_id}",
        "/api/health", "/api/health/live", "/api/health/ready",
    }
    assert expected_paths.issubset(schema["paths"].keys())
