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
- Context management, so that a conversation stays within the model's window
  (ENG-12): the window is `ModelSpec.context_window`, else
  `DEFAULT_CONTEXT_WINDOW` (128,000 tokens, exported), and one that is not
  positive is a `ValueError`; tokens are estimated as characters over four; a
  tool result longer than a fifth of the window is cut, with a note, for the
  model, the `ToolResult` event and the memory alike. Before a model call whose
  prompt passes 70% of the window, the newest exchanges within 30% are kept
  whole and the older history, an earlier summary included, is folded into one
  summary written by the same model, which counts as one of the turn's calls
  and in its usage; the question is never cut. A compacted history replays
  without the vendor's content, and the turn's checkpoint keeps it compacted;
  a turn compacted between its rounds replays its earlier rounds from their
  blocks too, from then on. Specified in `docs/specs/context.md`.
- Unit tests of the core and of `McpToolbox`, run with `uv run pytest`.
- The language-agnostic HTTP tests in `tests`: a mock vendor, a mock MCP server
  on the MCP SDK's own server, and cases of steps that compare every vendor
  request, every tool server request and every reply with their payloads. The
  Python test server in `packages/python/tests` exposes the engine over HTTP;
  the suite's coverage of both packages is the coverage CI reports. The
  protocol is in `tests/README.md`.

[Unreleased]: https://github.com/the-guish/kataloop/commits/main
