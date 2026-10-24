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

## 4. The HTTP tests (next)

In `tests` at the root, as in uni-llm-client: a runner that starts each port's
test server, a mock vendor that serves uni-llm-client's vendor payloads, a
mock MCP server, and cases made of steps that assert the JSON payloads of
every request and reply. The Python test server lives in
`packages/python/tests` and exposes the `Engine` over HTTP; it ships in no
package. Coverage comes from this suite alone. The suite runs against
`kataloop`, so it exercises the MCP toolbox too.

## 5. MCP tool servers

The `Toolbox` over the MCP SDK, in `kataloop`: streamable HTTP, the headers
the caller resolved, the server's timeout, tools under their servers' own
names, `exclude` honoured (ENG-11).

## 6. Context management

The window from the spec, else the model table, else a default. Summarise
older turns past a share of the window and keep the newest; cut tool results
above a fifth of the window; never cut the question (ENG-12). Rewritten
history replays without the vendor's thinking blocks, for the preserved
thinking rule of current Anthropic models. Cache breakpoints once
uni-llm-client places them.

## 7. The adapter in robinauts

`agent_engines/kataloop_engine` implementing robinauts' `AgentEngine` over
`kataloop`: providers from its settings into uni-llm-client `ProviderConfig`s
with keys from `key_for`, tool servers into `ToolServer`s with headers from
`secret_for`, models into `ModelSpec`s, the storage kind into a `Store`. It
passes robinauts' engine contract tests and its licence gate.

## Deferred

- `kataloop[postgres]`: the `Store` over asyncpg, tables prefixed `kataloop_`,
  idempotent setup, the pool handed in.
- A local store on disk.
- The TypeScript port.
- In uni-llm-client, in parallel: prompt caching, the OpenAI kinds, cache write
  tokens in usage, a model table with context windows.
