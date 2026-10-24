# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""A small agent loop over uni-llm-client: the contract, the loop, in-process memory."""

from importlib.metadata import PackageNotFoundError, version

from kataloop_core._contract import (
    AgentDefinition,
    CheckpointNotFoundError,
    Done,
    Engine,
    Event,
    KataloopError,
    ModelSpec,
    ReasoningDelta,
    SessionExistsError,
    SessionNotFoundError,
    TextDelta,
    ToolCall,
    ToolResult,
    ToolServer,
)
from kataloop_core._ports import Store, Toolbox, ToolOutput, ToolSpec

try:
    __version__ = version("kataloop-core")
except PackageNotFoundError:  # a source checkout on sys.path, not installed
    __version__ = "0+unknown"

__all__ = [
    "AgentDefinition",
    "CheckpointNotFoundError",
    "Done",
    "Engine",
    "Event",
    "KataloopError",
    "ModelSpec",
    "ReasoningDelta",
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
