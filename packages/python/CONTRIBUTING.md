# The Python port

Two packages in one [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/):

| Package | Import name | Holds |
|---|---|---|
| `kataloop-core` | `kataloop_core` | The contract, the loop, the context management, memory in the process. Depends on uni-llm-client and nothing else. |
| `kataloop` | `kataloop` | The core's API, re-exported, plus the extras that need a dependency: MCP tool servers (`McpToolbox`, over the MCP SDK, on mcp 1 as `kataloop[mcp-1]` or on mcp 2 as `kataloop[mcp-2]`), and PostgreSQL memory as `kataloop[postgres]`, planned. |

A caller installs `kataloop`. The core is for callers that bring their own
tools and memory, and for the tests of the loop itself.

## Two environments

`McpToolbox` runs on both majors of the MCP SDK (docs/specs/tools.md, TOOLS-8),
and an environment holds one, so the checks run in one environment per major.
The workspace installs `kataloop` through its own extras `mcp-1` and `mcp-2`,
which uv resolves apart in the one `uv.lock`, as `kataloop`'s are declared to
conflict. `UV_PROJECT_ENVIRONMENT` keeps the two environments apart, as
`.venv-mcp-1` and `.venv-mcp-2` here; `uv sync --extra` installs the major, and
a later `uv run` without the extra leaves it as it is, since nothing else in
the workspace needs `mcp`. A plain `uv sync` installs the core and the tools,
without `kataloop`.

Run the checks from this directory; they cover both packages. For mcp 1:

    export UV_PROJECT_ENVIRONMENT=.venv-mcp-1
    uv sync --locked --extra mcp-1
    uv run --locked ruff check
    uv run --locked ruff format --check
    uv run --locked mypy --always-false MCP_2 --exclude '_mcp2\.py$'
    uv run --locked pytest

and for mcp 2:

    export UV_PROJECT_ENVIRONMENT=.venv-mcp-2
    uv sync --locked --extra mcp-2
    uv run --locked ruff check
    uv run --locked ruff format --check
    uv run --locked mypy --always-true MCP_2 --exclude '_mcp1\.py$'
    uv run --locked pytest

Ruff does not depend on the major, so CI runs it once.

The code of one major lives in modules whose names end in `_mcp1.py` or
`_mcp2.py`: `kataloop/src/kataloop/_mcp1.py` and `_mcp2.py`, and the MCP server
of `kataloop`'s unit tests, `kataloop/tests/serving_mcp1.py` and
`serving_mcp2.py`. Each imports its major's SDK and HTTP stack, so it can be
type-checked only where they are installed: `--exclude` leaves the other
major's modules out of mypy's files. The code that picks a major branches on
`MCP_2`, which `kataloop._mcp_toolbox` reads from the version of `mcp`
installed; `--always-true MCP_2` or `--always-false MCP_2` makes it a constant
for mypy, which then checks the branch the environment takes and skips the
other. Both runs are strict, and between them every module is checked.

`pytest` runs the unit tests of both packages, in `kataloop-core/tests` and
`kataloop/tests`. The core's drive the loop through uni-llm-client against a
fake vendor, and `kataloop`'s run `McpToolbox` against an MCP server of the
major's SDK in the process, served through an ASGI transport, with the same
tests and answers on each major; they report no coverage, which comes from the
language-agnostic tests alone.

Build one package at a time:

    uv build --package kataloop-core
    uv build --package kataloop

The test server of the language-agnostic tests is `tests/server.py` here, next
to the packages and outside both, so that it ships in neither. It exposes the
engine over HTTP with `McpToolbox`, and runs under `coverage` while the tests in
`tests` at the root of the repository drive it ([tests/README.md](../../tests/README.md)).
They start it twice, as the implementations `python-mcp-1` and `python-mcp-2`,
each with `uv run --extra` in its environment above, so that `uv run coverage
combine` here, in either environment, reads what both covered.
