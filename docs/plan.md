# Plan: from the contract to an engine in robinauts

Status of each step is in its heading. Steps run in order unless noted.

## 1. Scaffolding and contract (done)

The repository layout, the two Python packages in one uv workspace, the
TypeScript stub, CI, the specs `principles.md` and `engine.md`, and the
contract itself in `kataloop-core`: `Engine`, its values and events, its
errors, and the `Store` and `Toolbox` ports.

uni-llm-client is a git dependency pinned to a commit until it is released.

## 2. One turn (done)

The loop in `kataloop-core` over uni-llm-client's `stream`: the model call,
the tool calls it asks for through the `Toolbox`, parallel calls run together,
a failing call reported as an error result, the vendor's paused turns resumed,
rounds bounded (ENG-13), the deadline (ENG-6), cancellation that closes the
model's stream (ENG-5). An in-process `Toolbox` of Python callables, so that
the core runs and is tested without MCP. Specified in `docs/specs/turn.md`;
the unit tests of the core drive it through uni-llm-client against a fake
vendor.

## 3. Memory in the process (done)

The `Store` port's first implementation, in memory. A checkpoint per finished
turn, holding the conversation in uni-llm-client's JSON form; rounds saved as
they complete, for resume (ENG-7); fork (ENG-8); forget (ENG-9). Checkpoint
ids minted by the engine. Specified in `docs/specs/memory.md`.

## 4. The HTTP tests (done)

In `tests` at the root, as in uni-llm-client: a runner that starts each port's
test server, a mock vendor that serves vendor payloads in uni-llm-client's
forms, a mock MCP server on the MCP SDK's own server, and cases made of steps
that assert the JSON payloads of every request and reply. The Python test
server lives in `packages/python/tests` and exposes the `Engine` over HTTP; it
ships in no package. Coverage of both packages comes from this suite alone. The
suite runs against `kataloop`, so it exercises the MCP toolbox too. The
protocol is in `tests/README.md`.

## 5. MCP tool servers (done)

The `Toolbox` over the MCP SDK, in `kataloop`: streamable HTTP, the headers
the caller resolved, the server's timeout, tools under their servers' own
names, `exclude` honoured (ENG-11). A session per listing and per call, so
that the port needs no open or close. Specified in `docs/specs/tools.md`.

## 6. Context management (done)

`fit`, the one place the policy lives, before every model call of a turn: the
window from the spec, else a default; tokens estimated from characters; tool
results above a fifth of the window cut; past 70% of the window, the newest
exchanges within 30% kept whole and the older ones folded into one summary by
a call to the same model, what it reads bounded to the difference; the
question never cut (ENG-12). Rewritten history replays without the vendor's
content, for the preserved-thinking rule of current Anthropic models, as do a
turn's rounds before a compaction in its middle, and the checkpoint keeps it
compacted. Specified in `docs/specs/context.md`. The model
table and cache breakpoints wait for uni-llm-client (Deferred).

## 7. The adapter in robinauts (done, on kataloop-core)

`agent_engines/kataloop_engine` implementing robinauts' `AgentEngine` over
`kataloop`: providers from its settings into uni-llm-client `ProviderConfig`s
with keys from `key_for`, tool servers into `ToolServer`s with headers from
`secret_for`, models into `ModelSpec`s, the storage kind into a `Store`. It
passes robinauts' engine contract tests and its licence gate.

The adapter is `agent_engines/kataloop_engine` on robinauts' branch. It
depends on `kataloop-core` alone: `kataloop` pins `mcp>=2.3`, and robinauts'
LangChain engine needs `langchain-mcp-adapters`, which requires `mcp<2`, so the
two cannot be installed together yet. The adapter reaches tool servers through
a toolbox of its own over mcp 1, written to tools.md. Memory lives in the
process until `kataloop[postgres]`. Step 8 lifts the constraint.

## 8. McpToolbox on mcp 1 and 2 (done)

`McpToolbox` runs on the major of the MCP SDK the environment holds:
`kataloop` depends on `mcp>=1.30,<3`, and its extras `mcp-1` and `mcp-2`,
declared to conflict so that one lock file resolves each on its own, narrow it
to one. The one public toolbox takes `_mcp1` or `_mcp2` when `kataloop` is
imported, by the version installed, and what the two share is one module. A
factory's client is the SDK's HTTP stack's, httpx on mcp 1 and httpx2 on mcp
2, exported as `McpHttpClient`. The checks run in an environment per major,
and the HTTP tests start the test server in each, as `python-mcp-1` and
`python-mcp-2`, against the mock MCP server on mcp 2. Specified in
`docs/specs/tools.md` (TOOLS-8 to TOOLS-10). robinauts' adapter can depend on
`kataloop[mcp-1]` and drop its own toolbox.

## Deferred

- `kataloop[postgres]`: the `Store` over asyncpg, tables prefixed `kataloop_`,
  idempotent setup, the pool handed in.
- A local store on disk.
- The TypeScript port.
- In uni-llm-client, in parallel: prompt caching, the OpenAI kinds, cache write
  tokens in usage, a model table with context windows. kataloop then places
  cache breakpoints and takes a model's window from the table (step 6).
