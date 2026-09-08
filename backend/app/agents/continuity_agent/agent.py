"""
The Continuity Anomaly Agent: an ADK LlmAgent with two tool surfaces --

  1. A McpToolset connected (over stdio) to the official ClickHouse MCP
     server (`mcp-clickhouse`, see requirements.txt), giving the agent
     `list_databases` / `list_tables` / `run_query` tools to read
     frame_metadata directly, as specified: "MCP server integration for
     GCP Agent Builder to query ClickHouse directly". The server is started
     with CLICKHOUSE_ALLOW_WRITE_ACCESS=false -- this toolset is read-only.

  2. A native ADK FunctionTool, flag_continuity_anomaly, which is the only
     way the agent can write. This keeps writes schema-validated instead of
     trusting LLM-generated SQL INSERTs.

google.adk.agents.LlmAgent handles the ReAct-style tool-calling loop itself
once these tools are attached -- nothing here special-cases "call a tool,
then reason, then call another tool"; that orchestration is ADK's job.
"""
from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from mcp import StdioServerParameters

from app.agents.continuity_agent.prompts import CONTINUITY_AGENT_INSTRUCTION
from app.agents.continuity_agent.tools import flag_continuity_anomaly
from app.config import Settings, get_settings

AGENT_NAME = "continuity_anomaly_agent"


def _build_clickhouse_mcp_toolset(settings: Settings) -> McpToolset:
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=settings.mcp_clickhouse_command,
                args=settings.mcp_clickhouse_args,
                env={
                    "CLICKHOUSE_HOST": settings.clickhouse_host,
                    "CLICKHOUSE_PORT": str(settings.clickhouse_port),
                    "CLICKHOUSE_USER": settings.clickhouse_user,
                    "CLICKHOUSE_PASSWORD": settings.clickhouse_password,
                    "CLICKHOUSE_DATABASE": settings.clickhouse_database,
                    "CLICKHOUSE_SECURE": str(settings.clickhouse_secure).lower(),
                    "CLICKHOUSE_ALLOW_WRITE_ACCESS": str(
                        settings.mcp_clickhouse_allow_write
                    ).lower(),
                },
            ),
            timeout=60,
        ),
    )


def build_continuity_agent(settings: Settings | None = None) -> LlmAgent:
    """Construct the continuity agent. Call once per process; ADK agents are
    stateless definitions -- per-run state lives in the Session, not here."""
    settings = settings or get_settings()
    # google-genai accepts the explicit api_key used by gemini_vision.py,
    # while Google ADK resolves its client credentials from GOOGLE_API_KEY.
    # Bridge the project's single GEMINI_API_KEY into ADK before the model is
    # constructed so both paths use the same credential.
    os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
    return LlmAgent(
        model=settings.gemini_agent_model,
        name=AGENT_NAME,
        description=(
            "Compares Gemini-extracted frame descriptors across takes of a "
            "scene in ClickHouse and flags visual continuity breaks."
        ),
        instruction=CONTINUITY_AGENT_INSTRUCTION,
        tools=[
            _build_clickhouse_mcp_toolset(settings),
            FunctionTool(flag_continuity_anomaly),
        ],
    )


# Module-level singleton, built lazily so importing this module never
# requires a live ClickHouse/Gemini connection (useful for tests / linting).
_agent_instance: LlmAgent | None = None


def get_continuity_agent() -> LlmAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = build_continuity_agent()
    return _agent_instance
