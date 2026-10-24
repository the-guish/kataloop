# Language-agnostic tests

These tests check that every port runs the engine the same way: the same
requests to the model vendor and to the tool servers, the same replies back.
Each port ships a test server that exposes the engine over HTTP. The tests start
a mock vendor and a mock MCP server, start the port's test server, and drive it
through each case, step by step. The mocks record each request they receive,
and each step compares those requests, and the test server's reply, with the
case's payloads, as uni-llm-client's tests do.

The test server is test code. It lives in the port's `tests` directory, next to
its packages and outside them, and ships in no package. Coverage comes from
this suite alone: each port runs its test server under its coverage tool.

## Running

The tests need [uv](https://docs.astral.sh/uv/). Run every implementation, or
one with `--impl`, or those of a package with `--package`:

    cd tests
    uv run pytest
    uv run pytest --impl python

The Python server runs under `coverage`; combine and read its data in
`packages/python`:

    cd packages/python
    uv run coverage combine
    uv run coverage report

## Cases

Cases live in `cases/*.json`. Each case has a `name`, the test id, and `steps`,
which run in order against one test server. A step names payloads instead of
holding them:

| Key | Meaning |
|---|---|
| `setup`, `create`, `exists`, `stream`, `fork` or `forget` | The operation, and the payload of its arguments. |
| `vendor` | The vendor exchanges expected, in order. Each has a `request` and a `response`. |
| `mcp` | The tool server exchanges expected, in any order. Each has a `request` and a `response`. |
| `reply` | The reply of the test server expected. |

`vendor` and `mcp` may be left out when nothing is expected.

The engine mints the checkpoint ids, so a case names them by the step that
minted them. `{"$checkpoint": N}` stands for the `checkpoint_id` of the `done`
event step `N` replied, in arguments and in replies. In a reply,
`{"$checkpoint": "new"}` stands for an id that no earlier step of the case
replied, which the step's own `done` mints.

Session ids are fixed UUIDs in the payloads. The test server keeps its memory
for its lifetime, across cases, so after each case the runner forgets every
session the case's arguments named, under `session_id`, `source_id` or
`target_id`.

A new behaviour usually needs a new case. Reuse a payload when one fits.

## Payloads

Payloads live in `reusable_payloads/<party>/<request or response>/`, one JSON
file each. A case names a payload by its path, without `.json`.

| Payload | Content |
|---|---|
| `kataloop/request` | The arguments of an operation, in the forms below. |
| `kataloop/response` | The reply of the test server, without error messages. |
| `anthropic/request`, `openrouter/request` | A vendor request: `method`, `url`, `headers` and `json`. |
| `anthropic/response`, `openrouter/response` | The `status`, optional `headers`, and the `body` or the `events` the mock vendor serves; or `disconnect`. An optional `delay` in seconds holds the response back. |
| `mcp/request` | A tool server request: the JSON-RPC `method` (`tools/list` or `tools/call`), the `url`, `headers` and `params`. |
| `mcp/response` | The `result` the mock MCP server answers, in MCP's JSON form, or the JSON-RPC `error` with its `code` and `message`. An optional `delay` in seconds holds it back. |

A vendor request matches when its `method`, `url` and `json` are equal. Its
`headers` must be present with these values, and other headers are allowed.
JSON text under an `arguments` key is compared parsed, since ports format it
differently. Every turn passes the API key `test-key` for each provider, unless
its arguments set `api_keys`.

A tool server request matches the same way, on its `method`, `url` and
`params`, its `headers` a subset. `params` is in MCP's JSON form without
`_meta`, which a client's SDK fills with its own. The calls of a round run
together, so a step's tool server requests are compared in any order.

A reply matches when it is equal, except that an error matches on its type
alone, since messages differ between ports.

## The mocks

The mock vendor serves the step's vendor responses in order. A response with
`events` is a stream of server-sent events. Each event has a `data`, a JSON
value or text, and an optional `event` name. An event with a `comment` is a
comment line. A stream that stops early is cut short. A response with a `body`
answers a call that does not stream, such as the summary call of a compaction
([context.md](../docs/specs/context.md)). `{"disconnect": true}`
closes the connection without an answer, as a network fault would. A request
that finds no response left gets a 500.

The mock MCP server is the MCP SDK's low-level server over streamable HTTP,
without sessions. It records every `tools/list` and `tools/call` it receives,
and answers each with the response of the first exchange of the step whose
request matches it, once. A request that matches none gets a JSON-RPC error.
The tool servers of a case are told apart by their URLs, such as
`https://weather.example.com/mcp`, whose host the test server keeps.

## Test server protocol

Each port's test server lives in its own `tests/` directory and is listed in
`implementations.json`. The runner starts the `command` in `cwd`, relative to
the repository root, and appends `--vendor-url URL` and `--mcp-url URL`. It
removes every environment variable ending in `_API_KEY` before it starts a
server.

1. The server listens on a free port of `127.0.0.1`. Its first line on stdout
   is `listening on http://127.0.0.1:PORT`.
2. The server sends every vendor request to the vendor URL and every tool
   server request to the MCP URL. Each request keeps its method, path, query,
   headers and body; the `Host` header keeps the original host, such as
   `api.anthropic.com` or `weather.example.com`.
3. The server keeps one engine for its lifetime, over memory in the process
   and the port's MCP toolbox, so that a case's steps share sessions and
   checkpoints.
4. `POST /setup`, `/create`, `/exists`, `/stream`, `/fork` and `/forget` take
   the operation's arguments as a JSON object, and reply with status 200.
5. `/stream` runs the turn on a uni-llm-client client made from the vendor URL
   and the arguments' `api_keys`, `providers` and `max_retries`, as
   uni-llm-client's test server makes one. It reads the whole turn and replies
   `{"events": [EVENT, ...]}`. An error ends the turn with the events so far,
   plus `error`: `{"events": [...], "error": {"type": "...", "message":
   "..."}}`, even when the turn yielded nothing.
6. `/exists` replies `{"exists": true}` or `{"exists": false}`; the other
   operations reply `{}`. An error replies `{"error": {"type": "...",
   "message": "..."}}`.
7. Any other failure replies with status 500. Its body helps debugging.

### Arguments

| Operation | Arguments |
|---|---|
| `setup` | none |
| `create`, `exists`, `forget` | `session_id` |
| `stream` | `session_id`, `agent`, `prompt`, `model`, `timeout`, and optionally `checkpoint_id` (default `null`), `resume` (default `false`), `api_keys`, `providers` and `max_retries` |
| `fork` | `source_id`, `target_id`, `checkpoint_id` |

### JSON forms

The names are those of [docs/specs/engine.md](../docs/specs/engine.md).
Arguments may leave out a field that has a default; replies hold every field,
defaults included.

| Value | JSON |
|---|---|
| Session id | A UUID string. |
| Agent | `system_prompt`, and optionally `tool_servers`, a list (default empty). |
| Tool server | `id`, `url`, and optionally `headers` (default `{}`), `timeout` in seconds (default `60`) and `exclude`, a list of tool names (default empty). |
| Model | `id`, a uni-llm-client model id, and optionally `timeout` in seconds (default `120`), `max_output_tokens`, `context_window` and `effort` (each default `null`). |
| Providers | By name: `kind`, and optionally `api_key` and `base_url`, as uni-llm-client's tests have them. |
| `EVENT` | `type` and the event's fields. |
| `text_delta`, `reasoning_delta` | `text`. |
| `tool_call` | `call_id`, `name`, `arguments`, an object. |
| `tool_result` | `call_id`, `name`, `output`, `is_error`. |
| `done` | `text`, `checkpoint_id`, and `usage` with uni-llm-client's four counts: `input_tokens`, `output_tokens`, `cached_input_tokens`, `reasoning_tokens`. |

### Error types

Error types are the same in every port:

| Type | Raised when |
|---|---|
| `session_exists` | `create` or `fork` names a session that exists. |
| `session_not_found` | A turn or a fork names a session the engine does not have. |
| `checkpoint_not_found` | The checkpoint is not held for that session. |
| `rounds_exceeded` | The turn needed more model calls than its timeout allows (ENG-13). |
| `timeout` | The turn passed its deadline (ENG-6). |
| `invalid_argument` | An argument is invalid, such as a timeout or a context window that is not positive, a model id, or a tool name two servers offer. |
| `authentication` | The API key is missing or rejected. |
| `rate_limit` | The vendor rate-limits the request. |
| `refusal` | The model declines to answer. |
| `incomplete_response` | The response contains no complete answer, such as one the output limit cut. |
| `transport` | The connection to the vendor failed or timed out. |
| `provider` | Any other vendor error. |

## Coverage of the cases

The cases cover a plain turn, a tool turn over MCP through Anthropic and
through OpenRouter, the model spec reaching the vendor, `tool_use` without a
call, a paused turn; two servers with `exclude`, a paged listing and parallel
calls, failing tools (an error the tool reports, an error of the server, a
timeout), a tool name two servers offer; a turn from a checkpoint, fork, resume
after a saved round and of a finished turn, resume with nothing saved; the
refusals; the rounds bound, a cut answer, a vendor error and the deadline; and
context management in a small window: a long tool result cut, a conversation
summarised past the threshold, its kept exchange replayed without the vendor's
content and the compacted history stored, then summarised again with the
earlier summary folded in; a short conversation replayed as it came; a long
question sent whole, then the bound on what is summarised; a window that is
not positive.
