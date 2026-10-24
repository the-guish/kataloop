# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""The `Toolbox` of tools of the process's own."""

from collections.abc import Mapping
from typing import Any

import pytest

from kataloop_core import LocalToolbox, ToolOutput, ToolServer, ToolSpec

SERVER = ToolServer("t", "local")


async def echo(arguments: Mapping[str, Any]) -> str:
    return str(arguments["word"])


async def refuse(arguments: Mapping[str, Any]) -> ToolOutput:
    return ToolOutput("No.", is_error=True)


ECHO = ToolSpec("echo", "Echoes a word.", {"type": "object"})
REFUSE = ToolSpec("refuse", "Refuses.", {"type": "object"})


async def test_it_lists_and_calls_the_tools_of_a_server() -> None:
    toolbox = LocalToolbox({"t": [(ECHO, echo), (REFUSE, refuse)]})

    assert await toolbox.tools(SERVER) == [ECHO, REFUSE]
    assert await toolbox.call(SERVER, "echo", {"word": "hi"}) == ToolOutput("hi")
    assert await toolbox.call(SERVER, "refuse", {}) == ToolOutput("No.", True)


async def test_it_refuses_what_it_does_not_have() -> None:
    toolbox = LocalToolbox({"t": [(ECHO, echo)]})

    with pytest.raises(LookupError, match="'other'"):
        await toolbox.tools(ToolServer("other", "local"))
    with pytest.raises(LookupError, match="'missing'"):
        await toolbox.call(SERVER, "missing", {})


def test_a_server_has_one_tool_of_a_name() -> None:
    with pytest.raises(ValueError, match="'echo'"):
        LocalToolbox({"t": [(ECHO, echo), (ECHO, echo)]})
