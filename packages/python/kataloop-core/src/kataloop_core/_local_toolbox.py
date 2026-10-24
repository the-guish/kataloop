# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""The `Toolbox` of tools of the process's own."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any

from kataloop_core._contract import ToolServer
from kataloop_core._ports import Toolbox, ToolOutput, ToolSpec

LocalTool = Callable[[Mapping[str, Any]], Awaitable[str | ToolOutput]]
"""A tool of the process's own: it takes the call's arguments and answers text,
or a `ToolOutput` for a failure it reports itself."""


class LocalToolbox(Toolbox):
    """Tools of the process's own, by server id, for the core without MCP.

    ``LocalToolbox({"weather": [(ToolSpec("forecast", ...), forecast)]})`` gives
    an agent with ``ToolServer("weather", url="local")`` the tool
    ``weather_forecast``. A server's `url` and `headers` are not used; its
    `timeout` and `exclude` are, by the engine.

    Raises:
        ValueError: A server has two tools of one name.
    """

    def __init__(
        self, servers: Mapping[str, Iterable[tuple[ToolSpec, LocalTool]]]
    ) -> None:
        self._servers: dict[str, dict[str, tuple[ToolSpec, LocalTool]]] = {}
        for server_id, tools in servers.items():
            named: dict[str, tuple[ToolSpec, LocalTool]] = {}
            for spec, run in tools:
                if spec.name in named:
                    raise ValueError(
                        f"Server {server_id!r} has two tools named {spec.name!r}"
                    )
                named[spec.name] = (spec, run)
            self._servers[server_id] = named

    async def tools(self, server: ToolServer) -> Sequence[ToolSpec]:
        """The server's tools, in the order they were given.

        Raises:
            LookupError: The toolbox has no server of that id.
        """
        return [spec for spec, _ in self._tools_of(server).values()]

    async def call(
        self, server: ToolServer, name: str, arguments: Mapping[str, Any]
    ) -> ToolOutput:
        """What the tool answered; what it raises, the engine reports (ENG-11).

        Raises:
            LookupError: The server has no tool of that name.
        """
        tools = self._tools_of(server)
        if name not in tools:
            raise LookupError(f"Server {server.id!r} has no tool named {name!r}")
        _, run = tools[name]
        output = await run(arguments)
        return output if isinstance(output, ToolOutput) else ToolOutput(output)

    def _tools_of(self, server: ToolServer) -> dict[str, tuple[ToolSpec, LocalTool]]:
        if server.id not in self._servers:
            raise LookupError(f"No tools for server {server.id!r}")
        return self._servers[server.id]
