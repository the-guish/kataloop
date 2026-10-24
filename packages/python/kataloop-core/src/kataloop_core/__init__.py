# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""A small agent loop over uni-llm-client: the contract, the loop, in-process memory."""

from importlib.metadata import PackageNotFoundError, version

from kataloop_core._context import DEFAULT_CONTEXT_WINDOW
from kataloop_core._contract import (
    AgentDefinition,
    CheckpointNotFoundError,
    Done,
    Engine,
    Event,
    KataloopError,
    ModelSpec,
    ReasoningDelta,
    RoundsExceededError,
    SessionExistsError,
    SessionNotFoundError,
    TextDelta,
    ToolCall,
    ToolResult,
    ToolServer,
)
from kataloop_core._engine import Kataloop
from kataloop_core._local_toolbox import LocalTool, LocalToolbox
from kataloop_core._memory_store import MemoryStore
from kataloop_core._ports import Store, Toolbox, ToolOutput, ToolSpec

try:
    __version__ = version("kataloop-core")
except PackageNotFoundError:  # a source checkout on sys.path, not installed
    __version__ = "0+unknown"

__all__ = [
    "DEFAULT_CONTEXT_WINDOW",
    "AgentDefinition",
    "CheckpointNotFoundError",
    "Done",
    "Engine",
    "Event",
    "Kataloop",
    "KataloopError",
    "LocalTool",
    "LocalToolbox",
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
