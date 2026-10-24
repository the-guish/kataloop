# The Python port

Two packages in one [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/):

| Package | Import name | Holds |
|---|---|---|
| `kataloop-core` | `kataloop_core` | The contract, the loop, the context management, memory in the process. Depends on uni-llm-client and nothing else. |
| `kataloop` | `kataloop` | The core's API, re-exported, plus the extras that need a dependency: MCP tool servers, and PostgreSQL memory as `kataloop[postgres]`. |

A caller installs `kataloop`. The core is for callers that bring their own
tools and memory, and for the tests of the loop itself.

Run the checks from this directory; they cover both packages:

    uv sync --locked
    uv run ruff check
    uv run ruff format --check
    uv run mypy
    uv run pytest

`pytest` runs the unit tests of both packages, in `kataloop-core/tests` and
`kataloop/tests`. The core's drive the loop through uni-llm-client against a
fake vendor; they report no coverage, which comes from the language-agnostic
tests alone.

Build one package at a time:

    uv build --package kataloop-core
    uv build --package kataloop

The test server of the language-agnostic tests will live in `tests` here, next
to the packages and outside both, so that it ships in neither.
