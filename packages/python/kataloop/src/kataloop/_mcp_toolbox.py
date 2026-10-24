# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""`McpToolbox` on the major of the MCP SDK the environment holds
(docs/specs/tools.md, TOOLS-8).

`_mcp1` and `_mcp2` each import their major's SDK and HTTP stack, so only the
one chosen here is imported. Type checkers cannot see the version: mypy reads
`MCP_2` as the constant that `--always-true MCP_2` or `--always-false MCP_2`
makes it (packages/python/CONTRIBUTING.md), and without either reads the
toolbox as on mcp 2, the first branch.
"""

from importlib.metadata import version

MCP_2 = version("mcp").partition(".")[0] != "1"
"""Whether the MCP SDK installed is mcp 2, which `McpToolbox` then runs on; it
runs on mcp 1 otherwise."""

if MCP_2:
    from kataloop._mcp2 import (
        HttpClientFactory,
        McpHttpClient,
        McpHttpTimeout,
        McpToolbox,
    )
else:
    from kataloop._mcp1 import (
        HttpClientFactory,
        McpHttpClient,
        McpHttpTimeout,
        McpToolbox,
    )

__all__ = [
    "MCP_2",
    "HttpClientFactory",
    "McpHttpClient",
    "McpHttpTimeout",
    "McpToolbox",
]
