# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The engine contract: `Engine`, its values and events, and the `Store` and
  `Toolbox` ports, in `kataloop-core`; `Engine.stream` is typed
  `AsyncGenerator[Event, None]`, so that a caller closes it without a cast.
  Specified in `docs/specs/engine.md`.
- `Kataloop`, the engine: one turn over uni-llm-client's `stream`, its tools
  offered under their servers' own names (a name two servers offer is a
  `ValueError`), its tool calls run together through the `Toolbox`, failures
  and timeouts as error results, a `tool_use` stop without a call ending the
  turn, paused turns sent back, rounds bounded by `RoundsExceededError`, the
  deadline, and cancellation that closes the model's stream. Specified in
  `docs/specs/turn.md`.
- `LocalToolbox`, the tools of the process's own, and `MemoryStore`, memory
  that lasts as long as the process.
- Memory: a checkpoint per finished turn holding the conversation in
  uni-llm-client's JSON form, each round of a turn in progress saved for
  resume (ENG-7), fork (ENG-8) and forget (ENG-9); `Store.latest_checkpoint`
  for resume. Specified in `docs/specs/memory.md`.
- `McpToolbox` in `kataloop`, the tools of MCP servers over the MCP SDK's
  streamable HTTP client: a session per listing and per call, the server's
  headers and timeout on every request, a result's content as text, and every
  timeout read as one. Specified in `docs/specs/tools.md`. `kataloop` now
  depends on the MCP SDK (`mcp`, MIT).
- Unit tests of the core and of `McpToolbox`, run with `uv run pytest`.

[Unreleased]: https://github.com/the-guish/kataloop/commits/main
