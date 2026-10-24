# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""A small agent loop over uni-llm-client, with MCP tool servers.

The API is kataloop-core's, re-exported here; this package adds what needs a
dependency (docs/specs/principles.md): `McpToolbox`, the tools of MCP servers.
"""

from importlib.metadata import PackageNotFoundError, version

from kataloop._mcp_toolbox import HttpClientFactory, McpToolbox
from kataloop_core import (
    AgentDefinition,
    CheckpointNotFoundError,
    Done,
    Engine,
    Event,
    Kataloop,
    KataloopError,
    LocalTool,
    LocalToolbox,
    MemoryStore,
    ModelSpec,
    ReasoningDelta,
    RoundsExceededError,
    SessionExistsError,
    SessionNotFoundError,
    Store,
    TextDelta,
    Toolbox,
    ToolCall,
    ToolOutput,
    ToolResult,
    ToolServer,
    ToolSpec,
)

try:
    __version__ = version("kataloop")
except PackageNotFoundError:  # a source checkout on sys.path, not installed
    __version__ = "0+unknown"

__all__ = [
    "AgentDefinition",
    "CheckpointNotFoundError",
    "Done",
    "Engine",
    "Event",
    "HttpClientFactory",
    "Kataloop",
    "KataloopError",
    "LocalTool",
    "LocalToolbox",
    "McpToolbox",
    "MemoryStore",
    "ModelSpec",
    "ReasoningDelta",
    "RoundsExceededError",
    "SessionExistsError",
    "SessionNotFoundError",
    "Store",
    "TextDelta",
    "ToolCall",
    "ToolOutput",
    "ToolResult",
    "ToolServer",
    "ToolSpec",
    "Toolbox",
    "__version__",
]
